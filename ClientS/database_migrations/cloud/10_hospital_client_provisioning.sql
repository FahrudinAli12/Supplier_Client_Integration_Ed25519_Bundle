-- =============================================================================
-- Silaris single-project migration: Provision Hospital Client Account & Contract
-- Safe/additive migration. Does not drop or truncate existing data.
-- Run in the SQL Editor of the ONE shared Supabase project (bgtxpdydljfeltdimmxr).
-- =============================================================================

BEGIN;

-- 1) RPC to link an auth user to a hospital membership and active supplier contract
CREATE OR REPLACE FUNCTION public.provision_hospital_client_account(
    p_hospital_id bigint,
    p_user_email text,
    p_role text DEFAULT 'operator'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_user_id uuid;
    v_supplier_id uuid;
    v_contract_id uuid;
    v_hospital_code text;
    v_mem_id uuid;
BEGIN
    -- Verify caller is active Supplier owner or admin
    IF NOT public.can_manage_supplier_hospital_master() THEN
        RAISE EXCEPTION 'Akses ditolak: Hanya Supplier admin/owner yang dapat mengaitkan akun client ke rumah sakit.'
            USING ERRCODE = '42501';
    END IF;

    -- Verify hospital exists and is active
    SELECT kode_rs INTO v_hospital_code
    FROM public.rumah_sakit
    WHERE id = p_hospital_id AND is_active = true;

    IF v_hospital_code IS NULL THEN
        RAISE EXCEPTION 'Rumah sakit ID % tidak ditemukan atau sedang dinonaktifkan.', p_hospital_id
            USING ERRCODE = 'P0002';
    END IF;

    -- Lookup auth user by email
    SELECT id INTO v_user_id
    FROM auth.users
    WHERE lower(email) = lower(trim(p_user_email))
    LIMIT 1;

    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Akun auth dengan email % tidak ditemukan.', p_user_email
            USING ERRCODE = 'P0002';
    END IF;

    -- Inactivate any conflicting active memberships for this user to enforce single tenant membership
    UPDATE public.hospital_memberships
    SET is_active = false, updated_at = now()
    WHERE user_id = v_user_id AND is_active = true AND hospital_id <> p_hospital_id;

    -- Insert or update membership for this hospital
    INSERT INTO public.hospital_memberships (user_id, hospital_id, role, is_active)
    VALUES (v_user_id, p_hospital_id, COALESCE(p_role, 'operator'), true)
    ON CONFLICT (user_id) WHERE (is_active = true)
    DO UPDATE SET hospital_id = EXCLUDED.hospital_id, role = EXCLUDED.role, is_active = true, updated_at = now()
    RETURNING id INTO v_mem_id;

    -- Ensure active contract exists between calling supplier and hospital
    SELECT sm.supplier_id INTO v_supplier_id
    FROM public.supplier_memberships sm
    WHERE sm.user_id = auth.uid() AND sm.is_active = true
    LIMIT 1;

    IF v_supplier_id IS NOT NULL THEN
        SELECT contract_id INTO v_contract_id
        FROM public.supplier_hospital_contracts
        WHERE supplier_id = v_supplier_id AND hospital_id = p_hospital_id;

        IF v_contract_id IS NULL THEN
            INSERT INTO public.supplier_hospital_contracts (
                contract_number, supplier_id, hospital_id, valid_from, valid_until, is_active
            ) VALUES (
                'CTR-' || v_hospital_code || '-' || to_char(now(), 'YYYYMMDD'),
                v_supplier_id, p_hospital_id,
                now() - INTERVAL '1 hour', now() + INTERVAL '5 years', true
            ) RETURNING contract_id INTO v_contract_id;
        ELSE
            UPDATE public.supplier_hospital_contracts
            SET is_active = true, valid_until = now() + INTERVAL '5 years', updated_at = now()
            WHERE contract_id = v_contract_id;
        END IF;
    END IF;

    RETURN jsonb_build_object(
        'success', true,
        'user_id', v_user_id,
        'hospital_id', p_hospital_id,
        'membership_id', v_mem_id,
        'contract_id', v_contract_id
    );
END;
$$;

REVOKE ALL ON FUNCTION public.provision_hospital_client_account(bigint, text, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.provision_hospital_client_account(bigint, text, text) TO authenticated;

NOTIFY pgrst, 'reload schema';

COMMIT;

