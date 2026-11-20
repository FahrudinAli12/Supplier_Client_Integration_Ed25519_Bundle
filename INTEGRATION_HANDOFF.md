# Silaris Supplier + Client Supabase Integration Handoff

## Chosen architecture

**Architecture A: Client Supabase is the package center.**

- Supplier's existing Supabase project remains responsible for Supplier-side master data, including the RS cache.
- Supplier package manifests are sent to the Client Supabase project through the `supplier-ingest` Edge Function.
- Client Supabase stores the package in its existing `pengiriman_linen` and `detail_pengiriman_linen` tables.
- Client users read packages through a tenant-scoped RPC and claim/confirm them through the existing Client RPCs.

## What the live Supabase preflight confirmed

The user's live Client project already contains:

- `suppliers`
- `registered_devices`
- `device_keys` with `key_algorithm = Ed25519`
- `device_nonces`
- `supplier_hospital_contracts`
- `pengiriman_linen`
- `detail_pengiriman_linen`
- `supplier_ingestion_audit`
- `hospital_memberships`
- `rumah_sakit`

The live project also exposes the seven-argument `ingest_supplier_package(...)` RPC. Its checks cover active device/Supplier, active hospital, active Supplier-RS contract, payload digest format, idempotency, manifest construction, and package insertion. It returns the Client-issued `verification_code`.

The live preflight did **not** show `list_hospital_packages`, and the original Client adapter selected a nonexistent `claim_session_id` column. The corrected Client package-list adapter now calls a new tenant-scoped RPC and does not select service-only columns.

## Changes in this bundle

### Supplier

- Added `client_package_gateway.py` with Ed25519 signing.
- Added the Client Supabase URL, publishable key, device ID, and private-key configuration.
- Added `cryptography` dependency.
- Added `generate_supplier_ed25519_key.py`.
- Supplier sends a canonical payload digest covering package code, RS code, idempotency key, note, and all normalized linen items.
- Each request signs `device_id:timestamp:nonce:payload_digest` with Ed25519.
- The Supplier retains its local SQLite package history and stores the cloud `package_id`, `kode_pengiriman`, `verification_code`, and manifest hash after successful ingestion.
- The Supplier's old `VRF-...` code is retained as a local reference. The Client cloud creates the actual `VC-...` verification code, which the Supplier displays only after cloud ingestion succeeds.
- Cancellation is blocked after Client Supabase has accepted the package.

### Client

- Added Edge Function `supabase/functions/supplier-ingest/index.ts`.
- The Edge Function verifies an active, time-valid Ed25519 device key, timestamp skew, signature, payload digest, and one-time nonce before calling the existing ingestion RPC.
- Added `database_migrations/cloud/08_supplier_ingestion_edge_r2_10_5.sql`. It does not recreate existing tables. It restricts the ingestion RPC to `service_role`, reconciles `get_package_info` with the live table columns while retaining tenant isolation, and adds `list_hospital_packages`, deriving the hospital from `auth.uid()`.
- The package list omits `verification_code` and user UUID fields.
- Added a device/Supplier/contract registration SQL template and a read-only postflight SQL.
- `ENABLE_PACKAGE_RECEIVING_API` remains off by default.

## Local verification performed

| Check | Result |
|---|---:|
| Supplier Python compile | PASS |
| Supplier gateway tests | 2 passed |
| Client Python compile | PASS |
| Client test suite | 99 passed |
| Edge Function TypeScript type-check (with Deno/Supabase declarations) | PASS |
| SQLite additive migration test | PASS |

The Client test suite reports pre-existing Pydantic/FastAPI/SQLAlchemy deprecation warnings. No test failures were reported.

## Not yet verified

The code has **not** been deployed to the user's live Supabase projects from this environment. The following still require the user's project credentials and explicit deployment:

1. Register the Supplier, device, Ed25519 public key, and active Supplier-RS contract in Client Supabase.
2. Apply migration `08_supplier_ingestion_edge_r2_10_5.sql` to Client Supabase.
3. Set `SUPABASE_SERVICE_ROLE_KEY` as an Edge Function secret and deploy `supplier-ingest` with JWT verification disabled for this custom Ed25519 endpoint.
4. Configure the Supplier backend `.env` with the Client project URL, publishable key, registered device ID, and private key.
5. Run the live smoke tests for RS A, RS B, replay rejection, and idempotent retry.
6. Enable `ENABLE_PACKAGE_RECEIVING_API=1` only after the tests pass.

## Do not use the previous HMAC draft

Do **not** run the earlier `08_supplier_ingestion_bridge_r2_10_5.sql` or deploy its HMAC-based `supplier-ingest` implementation. That draft does not match the live Client schema and bypasses the established Ed25519 device-key model. Use only the corrected files in this bundle.

## Required deployment order

1. Generate Ed25519 key pair on the Supplier backend workstation.
2. Register the public key and Supplier-RS contract in Client Supabase using `ClientS/supabase/SUPPLIER_DEVICE_SETUP_TEMPLATE.sql`.
3. Apply `ClientS/database_migrations/cloud/08_supplier_ingestion_edge_r2_10_5.sql`.
4. Run `ClientS/supabase/SUPPLIER_INGESTION_POSTFLIGHT_READ_ONLY.sql`.
5. Deploy `supplier-ingest` Edge Function.
6. Configure Supplier `.env` using `silarisV2-main/backend/.env.example` as reference.
7. Send one test package for RS A. Confirm the returned cloud code is displayed by Supplier.
8. Login as RS A and verify it can list and claim the package.
9. Login as RS B and verify the package is absent and direct claim is rejected even with the correct code.
10. Retry the same Supplier package and confirm no duplicate package is created.
11. Enable Client receiving feature gate after successful end-to-end verification.

## Secret handling

- The Supplier private Ed25519 key belongs only in the Supplier backend `.env`.
- The Client Supabase service-role key belongs only in Edge Function secrets.
- Never put either secret in frontend JavaScript, Client `.env`, a Git repository, or a ZIP shared with other people.
