-- R2.10.5: Safe additions for Supplier -> Client Supabase ingestion.
-- This migration DOES NOT recreate or alter existing Supplier/device/package tables.
-- Those tables and ingest_supplier_package() already exist in the live Client project.
-- Run only after reviewing the matching live schema supplied in the preflight output.

BEGIN;

-- Keep the ingestion RPC private to the trusted Edge Function's service_role client.
REVOKE ALL ON FUNCTION public.ingest_supplier_package(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ingest_supplier_package(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB)
  TO service_role;

-- Edge Function reads registered public keys and consumes single-use nonces.
GRANT SELECT ON TABLE public.device_keys TO service_role;
GRANT INSERT ON TABLE public.device_nonces TO service_role;
DO $sequence_grant$
DECLARE
  v_nonce_sequence TEXT;
BEGIN
  v_nonce_sequence := pg_get_serial_sequence('public.device_nonces', 'id');
  IF v_nonce_sequence IS NOT NULL THEN
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO service_role', v_nonce_sequence);
  END IF;
END;
$sequence_grant$;

-- Reconcile get_package_info with the live Client schema. The original R2.10.4
-- SQL file referred to legacy supplier/tanggal columns; the live table instead
-- contains device_id, kode_pengiriman, created_at, catatan, and manifest_hash.
-- Keep the original tenant check and never return verification_code.
CREATE OR REPLACE FUNCTION public.get_package_info(p_package_id BIGINT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
  v_user_id UUID;
  v_membership_count INTEGER;
  v_min_hospital_id BIGINT;
  v_max_hospital_id BIGINT;
  v_user_hospital_id BIGINT;
  v_pkg RECORD;
  v_supplier_name TEXT;
  v_items JSONB;
BEGIN
  IF p_package_id IS NULL THEN
    RETURN jsonb_build_object('status', 'ERROR', 'code', 'INVALID_ARGUMENTS', 'message', 'Parameter p_package_id wajib diisi.');
  END IF;

  v_user_id := auth.uid();
  IF v_user_id IS NULL THEN
    RETURN jsonb_build_object('status', 'ERROR', 'code', 'UNAUTHENTICATED', 'message', 'Pengguna harus terautentikasi.');
  END IF;

  SELECT COUNT(*), MIN(hm.hospital_id), MAX(hm.hospital_id)
    INTO v_membership_count, v_min_hospital_id, v_max_hospital_id
  FROM public.hospital_memberships hm
  JOIN public.rumah_sakit rs ON rs.id = hm.hospital_id
  WHERE hm.user_id = v_user_id
    AND hm.is_active = TRUE
    AND rs.is_active = TRUE;

  IF v_membership_count <> 1
     OR v_min_hospital_id IS NULL
     OR v_min_hospital_id IS DISTINCT FROM v_max_hospital_id THEN
    RETURN jsonb_build_object('status', 'FORBIDDEN', 'code', 'INVALID_HOSPITAL_MEMBERSHIP', 'message', 'Pengguna tidak memiliki tepat satu membership rumah sakit aktif.');
  END IF;
  v_user_hospital_id := v_min_hospital_id;

  SELECT * INTO v_pkg
  FROM public.pengiriman_linen pl
  WHERE pl.id = p_package_id;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('status', 'NOT_FOUND', 'code', 'PACKAGE_NOT_FOUND', 'message', 'Paket pengiriman tidak ditemukan.');
  END IF;

  IF v_pkg.hospital_id IS NULL THEN
    RETURN jsonb_build_object('status', 'FORBIDDEN', 'code', 'PACKAGE_NOT_BOUND', 'message', 'Paket belum terikat pada rumah sakit tujuan.');
  END IF;
  IF v_pkg.hospital_id <> v_user_hospital_id THEN
    RETURN jsonb_build_object('status', 'FORBIDDEN', 'code', 'CROSS_TENANT_ACCESS_DENIED', 'message', 'Paket ini milik rumah sakit lain.');
  END IF;

  SELECT s.supplier_name INTO v_supplier_name
  FROM public.registered_devices rd
  LEFT JOIN public.suppliers s ON s.supplier_id = rd.supplier_id
  WHERE rd.device_id = v_pkg.device_id;

  SELECT COALESCE(
    jsonb_agg(
      jsonb_build_object(
        'epc', public.clean_epc(d.epc),
        'kategori', COALESCE(d.kategori, ''),
        'nama_linen', COALESCE(d.nama_linen, '')
      ) ORDER BY convert_to(public.clean_epc(d.epc), 'UTF8') ASC
    ),
    '[]'::JSONB
  ) INTO v_items
  FROM public.detail_pengiriman_linen d
  WHERE d.pengiriman_id = p_package_id;

  RETURN jsonb_build_object(
    'status', 'ok',
    'paket_id', v_pkg.id,
    'package_id', v_pkg.id,
    'hospital_id', v_pkg.hospital_id,
    'supplier', COALESCE(v_supplier_name, ''),
    'status_paket', v_pkg.status,
    'tanggal', v_pkg.created_at,
    'created_at', v_pkg.created_at,
    'kode_pengiriman', v_pkg.kode_pengiriman,
    'catatan', v_pkg.catatan,
    'manifest_hash', v_pkg.manifest_hash,
    'manifest_items', v_items
  );
END;
$function$;

REVOKE ALL ON FUNCTION public.get_package_info(BIGINT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_package_info(BIGINT) TO authenticated, service_role;

-- Tenant-scoped package list. hospital_id is derived from auth.uid(); the caller
-- cannot choose another hospital_id. verification_code and payload digests are omitted.
CREATE OR REPLACE FUNCTION public.list_hospital_packages(
  p_status_filter TEXT DEFAULT NULL,
  p_limit INTEGER DEFAULT 50
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
  v_user_id UUID;
  v_membership_count INTEGER;
  v_min_hospital_id BIGINT;
  v_max_hospital_id BIGINT;
  v_hospital_id BIGINT;
  v_status_filter TEXT;
  v_limit INTEGER;
  v_packages JSONB;
BEGIN
  v_user_id := auth.uid();
  IF v_user_id IS NULL THEN
    RETURN jsonb_build_object('status', 'ERROR', 'code', 'UNAUTHENTICATED', 'message', 'Sesi pengguna tidak terautentikasi.');
  END IF;

  v_status_filter := NULLIF(lower(btrim(coalesce(p_status_filter, ''))), '');
  IF v_status_filter IS NOT NULL AND v_status_filter NOT IN ('pending', 'claimed', 'confirmed', 'cancelled') THEN
    RETURN jsonb_build_object('status', 'ERROR', 'code', 'INVALID_STATUS_FILTER', 'message', 'Filter status paket tidak valid.');
  END IF;
  v_limit := LEAST(GREATEST(COALESCE(p_limit, 50), 1), 200);

  SELECT COUNT(*), MIN(hm.hospital_id), MAX(hm.hospital_id)
    INTO v_membership_count, v_min_hospital_id, v_max_hospital_id
  FROM public.hospital_memberships hm
  JOIN public.rumah_sakit rs ON rs.id = hm.hospital_id
  WHERE hm.user_id = v_user_id
    AND hm.is_active = TRUE
    AND rs.is_active = TRUE;

  IF v_membership_count <> 1
     OR v_min_hospital_id IS NULL
     OR v_min_hospital_id IS DISTINCT FROM v_max_hospital_id THEN
    RETURN jsonb_build_object('status', 'FORBIDDEN', 'code', 'INVALID_HOSPITAL_MEMBERSHIP', 'message', 'Akun harus memiliki tepat satu membership rumah sakit yang aktif.');
  END IF;

  v_hospital_id := v_min_hospital_id;

  SELECT COALESCE(
    jsonb_agg(
      jsonb_build_object(
        'id', p.id,
        'kode_pengiriman', p.kode_pengiriman,
        'status', p.status,
        'hospital_id', p.hospital_id,
        'device_id', p.device_id,
        'catatan', p.catatan,
        'manifest_hash', p.manifest_hash,
        'created_at', p.created_at,
        'updated_at', p.updated_at,
        'claim_expires_at', p.claim_expires_at,
        'claimed_at', p.claimed_at,
        'claimed_by_operation_id', p.claimed_by_operation_id,
        'claimed_by_installation_uid', p.claimed_by_installation_uid,
        'confirmed_at', p.confirmed_at,
        'confirmed_by_operation_id', p.confirmed_by_operation_id,
        'confirmed_by_installation_uid', p.confirmed_by_installation_uid
      ) ORDER BY p.created_at DESC
    ),
    '[]'::JSONB
  ) INTO v_packages
  FROM (
    SELECT pl.*
    FROM public.pengiriman_linen pl
    WHERE pl.hospital_id = v_hospital_id
      AND (v_status_filter IS NULL OR pl.status = v_status_filter)
    ORDER BY pl.created_at DESC
    LIMIT v_limit
  ) p;

  RETURN jsonb_build_object(
    'status', 'ok',
    'hospital_id', v_hospital_id,
    'total', jsonb_array_length(v_packages),
    'packages', v_packages
  );
END;
$function$;

REVOKE ALL ON FUNCTION public.list_hospital_packages(TEXT, INTEGER) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_hospital_packages(TEXT, INTEGER) TO authenticated;

COMMIT;
