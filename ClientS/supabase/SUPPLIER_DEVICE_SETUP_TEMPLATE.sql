-- TEMPLATE REGISTRASI SUPPLIER / DEVICE / PUBLIC KEY / KONTRAK RS
-- Ganti semua nilai CHANGE_ME sebelum menjalankan.
-- Jalankan di SQL Editor project Supabase CLIENT, bukan project Supplier.
-- Jangan pernah memasukkan private key di sini. Yang disimpan hanya public key Ed25519.

DO $$
DECLARE
  v_supplier_code TEXT := 'CHANGE_ME_SUPPLIER_CODE';
  v_supplier_name TEXT := 'CHANGE_ME_SUPPLIER_NAME';
  v_contact_email TEXT := NULL;
  v_device_id TEXT := 'CHANGE_ME_DEVICE_ID';
  v_device_name TEXT := 'SILARIS Supplier Gateway';
  v_public_key_hex TEXT := 'CHANGE_ME_PUBLIC_KEY_64_HEX';
  v_hospital_code TEXT := 'CHANGE_ME_HOSPITAL_KODE_RS';
  v_contract_number TEXT := 'CHANGE_ME_UNIQUE_CONTRACT_NUMBER';
  v_supplier_id UUID;
  v_hospital_id BIGINT;
  v_contract_id UUID;
BEGIN
  IF v_supplier_code LIKE 'CHANGE_ME%'
     OR v_supplier_name LIKE 'CHANGE_ME%'
     OR v_device_id LIKE 'CHANGE_ME%'
     OR v_hospital_code LIKE 'CHANGE_ME%'
     OR v_contract_number LIKE 'CHANGE_ME%'
     OR v_public_key_hex LIKE 'CHANGE_ME%'
     OR v_public_key_hex !~ '^[0-9a-fA-F]{64}$' THEN
    RAISE EXCEPTION 'Ganti seluruh placeholder CHANGE_ME dan isi public key Ed25519 64 karakter hex.';
  END IF;

  SELECT rs.id INTO v_hospital_id
  FROM public.rumah_sakit rs
  WHERE rs.kode_rs = v_hospital_code
    AND rs.is_active = TRUE;
  IF v_hospital_id IS NULL THEN
    RAISE EXCEPTION 'Rumah sakit dengan kode_rs % tidak ditemukan atau tidak aktif pada Supabase Client.', v_hospital_code;
  END IF;

  INSERT INTO public.suppliers AS existing_supplier (supplier_code, supplier_name, contact_email, is_active)
  VALUES (v_supplier_code, v_supplier_name, v_contact_email, TRUE)
  ON CONFLICT (supplier_code) DO UPDATE
    SET supplier_name = EXCLUDED.supplier_name,
        contact_email = COALESCE(EXCLUDED.contact_email, existing_supplier.contact_email),
        is_active = TRUE,
        updated_at = NOW()
  RETURNING supplier_id INTO v_supplier_id;

  -- Device ID harus unik dan tidak boleh dipindahkan diam-diam ke supplier lain.
  INSERT INTO public.registered_devices AS existing_device (device_id, supplier_id, device_name, status)
  VALUES (v_device_id, v_supplier_id, v_device_name, 'ACTIVE')
  ON CONFLICT (device_id) DO UPDATE
    SET device_name = EXCLUDED.device_name,
        status = 'ACTIVE',
        updated_at = NOW()
    WHERE existing_device.supplier_id = EXCLUDED.supplier_id;

  IF NOT EXISTS (
    SELECT 1 FROM public.registered_devices
    WHERE device_id = v_device_id AND supplier_id = v_supplier_id AND status = 'ACTIVE'
  ) THEN
    RAISE EXCEPTION 'Device ID % sudah terdaftar pada supplier lain atau tidak dapat diaktifkan.', v_device_id;
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.device_keys
    WHERE lower(public.device_keys.public_key_ed25519) = lower(v_public_key_hex)
      AND public.device_keys.device_id <> v_device_id
  ) THEN
    RAISE EXCEPTION 'Public key ini sudah terikat pada device lain. Buat key pair baru untuk device ini.';
  END IF;

  -- Jika mengganti key, revoke key aktif lama terlebih dahulu.
  UPDATE public.device_keys
  SET status = 'REVOKED', updated_at = NOW()
  WHERE device_id = v_device_id
    AND status = 'ACTIVE'
    AND lower(public.device_keys.public_key_ed25519) <> lower(v_public_key_hex);

  INSERT INTO public.device_keys (
    device_id, public_key_ed25519, key_algorithm, status, valid_from, valid_until
  ) VALUES (
    v_device_id, lower(v_public_key_hex), 'Ed25519', 'ACTIVE', NOW() - INTERVAL '1 minute', NOW() + INTERVAL '5 years'
  )
  ON CONFLICT (public_key_ed25519) DO UPDATE
    SET device_id = EXCLUDED.device_id,
        key_algorithm = 'Ed25519',
        status = 'ACTIVE',
        valid_from = EXCLUDED.valid_from,
        valid_until = EXCLUDED.valid_until,
        updated_at = NOW();

  SELECT contract_id INTO v_contract_id
  FROM public.supplier_hospital_contracts
  WHERE supplier_id = v_supplier_id
    AND hospital_id = v_hospital_id
    AND is_active = TRUE;

  IF v_contract_id IS NULL THEN
    INSERT INTO public.supplier_hospital_contracts (
      contract_number, supplier_id, hospital_id, valid_from, valid_until, is_active
    ) VALUES (
      v_contract_number, v_supplier_id, v_hospital_id,
      NOW() - INTERVAL '1 minute', NOW() + INTERVAL '1 year', TRUE
    ) RETURNING contract_id INTO v_contract_id;
  ELSE
    UPDATE public.supplier_hospital_contracts
    SET valid_from = NOW() - INTERVAL '1 minute',
        valid_until = NOW() + INTERVAL '1 year',
        is_active = TRUE,
        updated_at = NOW()
    WHERE contract_id = v_contract_id;
  END IF;

  RAISE NOTICE 'Supplier %, device %, rumah sakit %, contract % berhasil disiapkan.',
    v_supplier_code, v_device_id, v_hospital_code, v_contract_id;
END;
$$;

-- Post-check tanpa membuka private key:
SELECT s.supplier_code, s.supplier_name, rd.device_id, rd.status AS device_status,
       dk.key_algorithm, dk.status AS key_status, dk.valid_from, dk.valid_until,
       rs.kode_rs, rs.nama_rs, shc.contract_number, shc.is_active AS contract_active,
       shc.valid_from AS contract_valid_from, shc.valid_until AS contract_valid_until
FROM public.suppliers s
JOIN public.registered_devices rd ON rd.supplier_id = s.supplier_id
JOIN public.device_keys dk ON dk.device_id = rd.device_id AND dk.status = 'ACTIVE'
JOIN public.supplier_hospital_contracts shc ON shc.supplier_id = s.supplier_id AND shc.is_active = TRUE
JOIN public.rumah_sakit rs ON rs.id = shc.hospital_id
WHERE s.supplier_code = 'CHANGE_ME_SUPPLIER_CODE'
  AND rd.device_id = 'CHANGE_ME_DEVICE_ID';
