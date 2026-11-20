# Silaris Supplier + Client: Single Supabase Project Patch

## Scope

This patch moves Supplier master-data CRUD and package ingestion onto the same Supabase project while preserving:

- Supabase RLS for Supplier master-data access;
- Supabase Auth for human Supplier users;
- Ed25519 device authentication for package ingestion;
- `supplier-ingest` Edge Function and the existing seven-argument `ingest_supplier_package(...)` RPC;
- local SQLite package queue and retry history;
- `rumah_sakit.id` as BIGINT in cloud, while retaining `rs_id` as a decimal string in the existing Supplier API/SQLite cache.

No service-role key is used in the Supplier Python backend. The Edge Function continues to use the managed `SUPABASE_SERVICE_ROLE_KEY` secret inside Supabase.

## Important authorization model

- Supplier users must exist in Supabase Auth.
- Each Supplier user must have one active row in `public.supplier_memberships`.
- `owner` and `admin` can create, edit, activate and deactivate hospital master rows.
- Active Supplier members can read the hospital master list.
- Supplier cannot hard-delete a hospital. The existing API `DELETE /api/rumah-sakit/{id}` now sets `is_active=false` to preserve foreign keys, memberships, contracts and package history.
- Hospital users keep their existing `hospital_memberships` RLS policy. The new Supplier SELECT policy is additive.
- The Ed25519 gateway remains a separate device-authenticated path. Do not replace it with a user access token.

## Files in this patch

Extract this patch over the parent folder that contains `silarisV2-main/` and `ClientS/`. The patch paths already match the project layout:

- `silarisV2-main/backend/` replaces/adds the listed Supplier backend files;
- `silarisV2-main/frontend-vanilla/` replaces/adds the listed Supplier frontend files;
- `ClientS/database_migrations/cloud/` adds the two SQL scripts.

Do not replace the whole project directory with this patch. It contains only changed/new files. The patch intentionally does not include `.env`, local SQLite databases, private keys, service-role keys, or deployed function secrets.

## Safe deployment order

1. Back up the shared Supabase project and the Supplier SQLite database.
2. Confirm the target project is `bgtxpdydljfeltdimmxr` and the deployed `supplier-ingest` GET health check still returns `success=true`.
3. Create the Supplier administrator in Supabase Dashboard → Authentication → Users. Do not enable public sign-up for this management role.
4. Run `ClientS/database_migrations/cloud/09_supplier_memberships_and_hospital_master_rls.sql` in the SQL Editor of the shared project.
5. Edit `ClientS/database_migrations/cloud/09b_bootstrap_supplier_admin_membership.sql`: replace `CHANGE_ME_SUPPLIER_ADMIN_EMAIL` with the exact Auth user's email in both occurrences. Confirm the Supplier code is `SUPP-001`, then run it.
6. Verify that the membership query returns exactly one active row with role `admin`.
7. Update the Supplier backend `.env` as described below. Do not paste any secret values into chat.
8. Copy the patch files into the Supplier project. Keep a backup of each replaced file.
9. Run the Python compile and gateway tests listed below.
10. Start the Supplier backend and open Manajemen Rumah Sakit. Login with the Auth user created in step 3.
11. Test create, edit, deactivate and reactivate against a non-production/test hospital row first.
12. Send one test package and verify that the Client receives the same Ed25519-authenticated ingestion result as before.

## Supplier `.env` changes

Use the shared Client project as the only project URL:

```dotenv
SUPABASE_URL=https://bgtxpdydljfeltdimmxr.supabase.co
SUPABASE_PUBLISHABLE_KEY=<copy the existing CLIENT_SUPABASE_PUBLISHABLE_KEY value>

# Deprecated compatibility variables: leave blank or make them match the same project.
SUPABASE_ANON_KEY=
CLIENT_SUPABASE_URL=
CLIENT_SUPABASE_PUBLISHABLE_KEY=

# Keep the currently registered device and its private key unchanged.
CLIENT_SUPPLIER_DEVICE_ID=SILARIS-SUPPLIER-DEVICE-01
CLIENT_SUPPLIER_PRIVATE_KEY_HEX=<keep the existing 64-hex-character private key>

# For local HTTP development. Set true only when the Supplier app is served over HTTPS.
SUPPLIER_SESSION_COOKIE_SECURE=false
```

If `CLIENT_SUPABASE_URL` is retained, it must point to the exact same host as `SUPABASE_URL`. The new code fails closed if the two URLs point to different projects. Do not put `SUPABASE_SERVICE_ROLE_KEY` in this `.env`.

## Local checks

Run from `silarisV2-main/backend` using the project's existing virtual environment:

```powershell
python -m py_compile .\app\config.py .\app\services\supabase_config.py .\app\services\supplier_auth.py .\app\services\supabase_client.py .\app\services\client_package_gateway.py .\app\services\sync_service.py .\app\routers\auth.py .\app\routers\rumah_sakit.py .\app\schemas\rumah_sakit.py
python -m pytest .\tests -v
```

The current browser page now requires a Supplier login for the hospital master page. The cookie is HttpOnly; access/refresh tokens are not exposed to JavaScript. Sessions live in backend memory, so a backend restart requires the Supplier user to log in again.

## Rollback

- Restore the backed-up Python and frontend files if the Supplier app fails local checks.
- Do not drop `supplier_memberships` or remove the new policies as a first response to a problem. Diagnose the failing policy first.
- The SQL migration is additive. The old Supplier project and its data are not automatically deleted or modified.
- Do not roll the Edge Function back to the earlier HMAC draft. Keep the deployed Ed25519 `supplier-ingest` function and existing RPC.

## Known migration considerations

- Existing Supplier SQLite `RumahSakitLocal.rs_id` values may be UUIDs from the retired Supplier project. The local schema keeps them as text so historical local references are not destroyed. New shared-project IDs are stored as decimal strings derived from the cloud BIGINT `id`.
- Existing pending package rows that refer to retired UUID hospital IDs will not be silently retargeted. They must be reviewed before retry because the destination hospital cannot be inferred safely.
- The Supplier background worker no longer downloads hospital master data anonymously at startup. The cache refresh runs after a Supplier user has authenticated and the user's JWT is forwarded to PostgREST. Membership is rechecked on each protected request so revoked Supplier memberships and role changes take effect promptly.
- Offline hospital-list reads use the last local cache while the local Supplier session remains valid. Cloud writes are disabled while Supabase is offline.
