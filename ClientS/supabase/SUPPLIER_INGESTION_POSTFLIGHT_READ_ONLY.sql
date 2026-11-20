-- Read-only verification after migration 08 and Supplier/device registration.
-- Run in the Client Supabase SQL Editor. It does not change data.

-- 1. Required function signatures and SECURITY DEFINER posture.
SELECT
  p.proname,
  pg_get_function_identity_arguments(p.oid) AS arguments,
  p.prosecdef AS security_definer,
  p.proconfig AS function_config
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname IN ('ingest_supplier_package', 'get_package_info', 'list_hospital_packages')
ORDER BY p.proname;

-- 2. Execution rights: ingestion only service_role; package list for authenticated users.
SELECT
  has_function_privilege('service_role', 'public.ingest_supplier_package(text,text,text,text,text,text,jsonb)', 'EXECUTE') AS service_role_can_ingest,
  has_function_privilege('authenticated', 'public.ingest_supplier_package(text,text,text,text,text,text,jsonb)', 'EXECUTE') AS authenticated_can_ingest,
  has_function_privilege('anon', 'public.ingest_supplier_package(text,text,text,text,text,text,jsonb)', 'EXECUTE') AS anon_can_ingest,
  has_function_privilege('authenticated', 'public.get_package_info(bigint)', 'EXECUTE') AS authenticated_can_get_package_info,
  has_function_privilege('authenticated', 'public.list_hospital_packages(text,integer)', 'EXECUTE') AS authenticated_can_list_packages,
  has_column_privilege('authenticated', 'public.pengiriman_linen', 'verification_code', 'SELECT') AS authenticated_can_read_verification_code;

-- 3. Minimum privileges required by the Edge Function.
SELECT
  has_table_privilege('service_role', 'public.device_keys', 'SELECT') AS service_role_can_read_device_keys,
  has_table_privilege('service_role', 'public.device_nonces', 'INSERT') AS service_role_can_insert_device_nonces,
  CASE
    WHEN pg_get_serial_sequence('public.device_nonces', 'id') IS NULL THEN TRUE
    ELSE has_sequence_privilege('service_role', pg_get_serial_sequence('public.device_nonces', 'id'), 'USAGE')
  END AS service_role_can_use_nonce_sequence;

-- 4. Active device/key/contract registrations. Public key bytes and private secrets are not selected.
SELECT
  s.supplier_code,
  s.supplier_name,
  s.is_active AS supplier_active,
  rd.device_id,
  rd.status AS device_status,
  dk.key_algorithm,
  dk.status AS key_status,
  dk.valid_from AS key_valid_from,
  dk.valid_until AS key_valid_until,
  rs.kode_rs,
  rs.nama_rs,
  rs.is_active AS hospital_active,
  shc.contract_number,
  shc.is_active AS contract_active,
  shc.valid_from AS contract_valid_from,
  shc.valid_until AS contract_valid_until
FROM public.registered_devices rd
JOIN public.suppliers s ON s.supplier_id = rd.supplier_id
JOIN public.device_keys dk ON dk.device_id = rd.device_id AND dk.status = 'ACTIVE'
JOIN public.supplier_hospital_contracts shc ON shc.supplier_id = s.supplier_id AND shc.is_active = TRUE
JOIN public.rumah_sakit rs ON rs.id = shc.hospital_id
ORDER BY s.supplier_code, rd.device_id, rs.kode_rs;

-- 5. Tenant membership invariant used by list_hospital_packages and claim/confirm.
SELECT
  hm.user_id,
  COUNT(*) FILTER (WHERE hm.is_active AND rs.is_active) AS active_hospital_memberships
FROM public.hospital_memberships hm
JOIN public.rumah_sakit rs ON rs.id = hm.hospital_id
GROUP BY hm.user_id
ORDER BY hm.user_id;
