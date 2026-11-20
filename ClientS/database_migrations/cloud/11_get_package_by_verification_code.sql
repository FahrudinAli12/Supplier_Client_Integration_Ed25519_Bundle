-- =============================================================================
-- MIGRATION: 11_get_package_by_verification_code.sql
-- PURPOSE: Mengambil manifest paket pengiriman linen berdasarkan kode verifikasi
--          dari supplier dengan penegakan tenant isolation multi-rumah sakit.
-- ATURAN KEAMANAN:
-- 1. SECURITY DEFINER: Mengakses kolom rahasia verification_code tanpa mengeksposnya ke publik.
-- 2. Tenant Scoping: Memeriksa auth.uid() dan mencocokkan keanggotaan tunggal di hospital_memberships.
-- 3. Non-Leakage: Tidak mengembalikan nilai verification_code ke client.
-- =============================================================================

CREATE OR REPLACE FUNCTION public.get_package_by_verification_code(p_verification_code TEXT)
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
  v_clean_code TEXT;
BEGIN
  IF p_verification_code IS NULL OR btrim(p_verification_code) = '' THEN
    RETURN jsonb_build_object('status', 'ERROR', 'code', 'INVALID_ARGUMENTS', 'message', 'Kode verifikasi wajib diisi.');
  END IF;

  v_clean_code := btrim(p_verification_code);
  v_user_id := auth.uid();
  IF v_user_id IS NULL THEN
    RETURN jsonb_build_object('status', 'ERROR', 'code', 'UNAUTHENTICATED', 'message', 'Pengguna harus terautentikasi.');
  END IF;

  -- 1. Verifikasi Keanggotaan Rumah Sakit Aktif (Single-Tenant Multi-Hospital)
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

  -- 2. Cari paket berdasarkan verification_code ATAU kode_pengiriman ATAU idempotency_key
  SELECT * INTO v_pkg
  FROM public.pengiriman_linen pl
  WHERE pl.hospital_id = v_user_hospital_id
    AND (
      pl.verification_code = v_clean_code
      OR pl.kode_pengiriman = v_clean_code
      OR pl.kode_pengiriman ILIKE '%' || v_clean_code || '%'
      OR pl.idempotency_key ILIKE '%' || v_clean_code || '%'
    )
  ORDER BY pl.id DESC
  LIMIT 1;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('status', 'NOT_FOUND', 'code', 'PACKAGE_NOT_FOUND', 'message', 'Paket tidak ditemukan untuk kode verifikasi tersebut.');
  END IF;

  -- 3. Cari nama supplier jika ada
  SELECT s.supplier_name INTO v_supplier_name
  FROM public.registered_devices rd
  LEFT JOIN public.suppliers s ON s.supplier_id = rd.supplier_id
  WHERE rd.device_id = v_pkg.device_id;

  -- 4. Ambil item linen dari detail pengiriman
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
  WHERE d.pengiriman_id = v_pkg.id;

  -- 5. Return paket info AMAN tanpa verification_code
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

REVOKE ALL ON FUNCTION public.get_package_by_verification_code(TEXT) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.get_package_by_verification_code(TEXT) TO authenticated, service_role;

