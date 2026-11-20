-- Run only AFTER creating the Supplier admin account in Supabase Auth.
-- Replace the email below with the exact Auth user email.
-- This grants master-hospital management to that user for supplier SUPP-001.

DO $block$
DECLARE
    v_email text := 'moch.fahrudinalinugroho@gmail.com';
    v_user_id uuid;
    v_supplier_id uuid;
BEGIN
    IF v_email = 'CHANGE_ME_SUPPLIER_ADMIN_EMAIL' THEN
        RAISE EXCEPTION 'Replace CHANGE_ME_SUPPLIER_ADMIN_EMAIL before running this script.';
    END IF;

    SELECT id INTO v_user_id
    FROM auth.users
    WHERE lower(email) = lower(v_email)
    LIMIT 1;

    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Auth user % not found. Create the user in Supabase Auth first.', v_email;
    END IF;

    SELECT supplier_id INTO v_supplier_id
    FROM public.suppliers
    WHERE supplier_code = 'SUPP-001'
      AND is_active = true
    LIMIT 1;

    IF v_supplier_id IS NULL THEN
        RAISE EXCEPTION 'Active supplier SUPP-001 not found. Check public.suppliers.';
    END IF;

    INSERT INTO public.supplier_memberships (user_id, supplier_id, role, is_active)
    VALUES (v_user_id, v_supplier_id, 'admin', true)
    ON CONFLICT (user_id, supplier_id)
    DO UPDATE SET role = 'admin', is_active = true, updated_at = now();
END;
$block$;

-- Verify. This query is for the project administrator only.
SELECT sm.user_id, u.email, s.supplier_code, s.supplier_name, sm.role, sm.is_active
FROM public.supplier_memberships sm
JOIN auth.users u ON u.id = sm.user_id
JOIN public.suppliers s ON s.supplier_id = sm.supplier_id
WHERE lower(u.email) = lower('moch.fahrudinalinugroho@gmail.com');
