-- =============================================================================
-- Silaris single-project migration: Supplier Auth membership + Rumah Sakit CRUD
-- Safe/additive migration. Does not recreate or delete existing business tables.
-- Run in the SQL Editor of the ONE shared Supabase project (bgtxpdydljfeltdimmxr).
-- =============================================================================

BEGIN;

-- 1) Supplier user membership. User accounts are created in Supabase Auth first.
CREATE TABLE IF NOT EXISTS public.supplier_memberships (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    supplier_id uuid NOT NULL REFERENCES public.suppliers(supplier_id) ON DELETE RESTRICT,
    role text NOT NULL DEFAULT 'operator',
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT supplier_memberships_role_check
        CHECK (role IN ('owner', 'admin', 'operator', 'viewer')),
    CONSTRAINT supplier_memberships_user_supplier_key UNIQUE (user_id, supplier_id)
);

CREATE INDEX IF NOT EXISTS idx_supplier_memberships_user_active
    ON public.supplier_memberships (user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_supplier_memberships_supplier_active
    ON public.supplier_memberships (supplier_id, is_active);

ALTER TABLE public.supplier_memberships ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.supplier_memberships FROM anon, authenticated;
GRANT SELECT ON TABLE public.supplier_memberships TO authenticated;

DROP POLICY IF EXISTS p_supplier_memberships_self_read ON public.supplier_memberships;
CREATE POLICY p_supplier_memberships_self_read
    ON public.supplier_memberships
    FOR SELECT
    TO authenticated
    USING (user_id = (SELECT auth.uid()));

-- Membership writes are intentionally unavailable to authenticated users.
-- Provisioning is performed by a trusted project administrator / postgres.

-- 2) Narrow SECURITY DEFINER predicates. They return booleans only and expose
--    no membership rows. search_path is pinned to prevent object-shadowing.
CREATE OR REPLACE FUNCTION public.has_active_supplier_membership()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.supplier_memberships sm
        WHERE sm.user_id = auth.uid()
          AND sm.is_active = true
    );
$function$;

CREATE OR REPLACE FUNCTION public.can_manage_supplier_hospital_master()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
    SELECT EXISTS (
        SELECT 1
        FROM public.supplier_memberships sm
        WHERE sm.user_id = auth.uid()
          AND sm.is_active = true
          AND sm.role IN ('owner', 'admin')
    );
$function$;

REVOKE ALL ON FUNCTION public.has_active_supplier_membership() FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.can_manage_supplier_hospital_master() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.has_active_supplier_membership() TO authenticated;
GRANT EXECUTE ON FUNCTION public.can_manage_supplier_hospital_master() TO authenticated;

-- 3) Add Supplier read/insert/update policies to the existing rumah_sakit table.
--    Existing hospital_memberships SELECT policy remains in place. PostgreSQL's
--    permissive policies combine with OR, so hospital users retain their access.
ALTER TABLE public.rumah_sakit ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE ON TABLE public.rumah_sakit TO authenticated;
REVOKE DELETE ON TABLE public.rumah_sakit FROM anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.rumah_sakit_id_seq TO authenticated;

DROP POLICY IF EXISTS p_rumah_sakit_supplier_read ON public.rumah_sakit;
CREATE POLICY p_rumah_sakit_supplier_read
    ON public.rumah_sakit
    FOR SELECT
    TO authenticated
    USING (public.has_active_supplier_membership());

DROP POLICY IF EXISTS p_rumah_sakit_supplier_insert ON public.rumah_sakit;
CREATE POLICY p_rumah_sakit_supplier_insert
    ON public.rumah_sakit
    FOR INSERT
    TO authenticated
    WITH CHECK (public.can_manage_supplier_hospital_master());

DROP POLICY IF EXISTS p_rumah_sakit_supplier_update ON public.rumah_sakit;
CREATE POLICY p_rumah_sakit_supplier_update
    ON public.rumah_sakit
    FOR UPDATE
    TO authenticated
    USING (public.can_manage_supplier_hospital_master())
    WITH CHECK (public.can_manage_supplier_hospital_master());

-- Deliberately NO DELETE policy and NO DELETE table grant. Supplier UI's DELETE
-- endpoint performs UPDATE is_active=false. This preserves memberships,
-- supplier_hospital_contracts and pengiriman_linen foreign-key history.

NOTIFY pgrst, 'reload schema';

COMMIT;

-- =============================================================================
-- POST-MIGRATION CHECKS (read-only)
-- =============================================================================
SELECT tablename, policyname, cmd, roles
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('supplier_memberships', 'rumah_sakit')
ORDER BY tablename, policyname;

SELECT grantee, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'public'
  AND table_name IN ('supplier_memberships', 'rumah_sakit')
  AND grantee IN ('anon', 'authenticated')
ORDER BY table_name, grantee, privilege_type;
