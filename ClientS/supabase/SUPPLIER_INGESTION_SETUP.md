# Supplier -> Client Supabase: setup and deployment

## Architecture

- The Supplier app keeps its existing Supabase project for its own master data and the local RS cache.
- Package data is sent to the Client Supabase project through `supabase/functions/supplier-ingest`.
- The Edge Function verifies the registered device's Ed25519 signature, timestamp, key validity, and one-time nonce.
- The Edge Function calls the existing `public.ingest_supplier_package(...)` RPC with the exact seven parameters already present in the live Client schema.
- The RPC checks device status, supplier status, hospital code, active Supplier-RS contract, payload digest format, and idempotency. It creates the package and returns the Client-issued `verification_code`.
- Client users retrieve package lists through `list_hospital_packages`, which derives the hospital from `auth.uid()` and never returns `verification_code`.

## 1. Generate the Supplier device key

From the Supplier project root:

```powershell
cd backend
pip install -r requirements.txt
python scripts/generate_supplier_ed25519_key.py
```

The command prints:

- `CLIENT_SUPPLIER_PRIVATE_KEY_HEX`: private key, keep only on the Supplier backend.
- `PUBLIC_KEY_ED25519_HEX`: public key, register in Client Supabase.

Do not send the private key to the Client project, do not place it in frontend JavaScript, and do not commit `.env`.

## 2. Register Supplier, device, key, and RS contract

1. Open the SQL Editor of the **Client Supabase project**.
2. Open `supabase/SUPPLIER_DEVICE_SETUP_TEMPLATE.sql`.
3. Replace all `CHANGE_ME` values:
   - supplier code and name;
   - device ID (must exactly match `CLIENT_SUPPLIER_DEVICE_ID`);
   - public key hex printed by the generator;
   - hospital `kode_rs` (must match the Supplier RS cache);
   - unique contract number.
4. Run the SQL.
5. Confirm the post-check returns an active Supplier, active device, active Ed25519 key, and active contract for the intended RS.
6. Repeat the contract registration for every additional RS that this Supplier may serve. Each Supplier-RS pair needs an active contract.

The SQL template never accepts or stores the private key.

## 3. Apply the Client SQL migration

Back up the Client Supabase database first. Then run:

`database_migrations/cloud/08_supplier_ingestion_edge_r2_10_5.sql`

This migration does not recreate Supplier/device/package tables and does not alter existing package rows. It:

- restricts `ingest_supplier_package` execution to `service_role`;
- grants the Edge Function the minimum key/nonce table privileges it needs;
- reconciles `get_package_info` to the live `pengiriman_linen` columns while retaining its tenant check and verification-code masking;
- adds the tenant-scoped `list_hospital_packages` RPC.

Do not run the earlier HMAC migration `08_supplier_ingestion_bridge_r2_10_5.sql` from the previous integration draft. That file does not match the live schema.

## 4. Deploy the Edge Function

Install/link Supabase CLI to the **Client** project, then set the function's service-role secret and deploy:

```powershell
supabase link --project-ref YOUR_CLIENT_PROJECT_REF
supabase secrets set SUPABASE_SERVICE_ROLE_KEY=YOUR_CLIENT_SERVICE_ROLE_KEY
supabase functions deploy supplier-ingest --no-verify-jwt
```

`SUPABASE_URL` is injected by Supabase Edge Functions. The service-role key is stored only in Edge Function secrets. Never place it in either desktop app or frontend.

`verify_jwt = false` is intentional for this endpoint because the Supplier authenticates with the registered Ed25519 device key, not a hospital user JWT. The function independently verifies the device signature before it can write anything.

## 5. Verify the live Client schema and privileges

After applying migration 08 and registering the Supplier/device/contract, run `supabase/SUPPLIER_INGESTION_POSTFLIGHT_READ_ONLY.sql`. Confirm:

- `service_role_can_ingest = true`;
- `authenticated_can_ingest = false` and `anon_can_ingest = false`;
- `authenticated_can_list_packages = true`;
- the Edge Function can read device keys, insert nonces, and use the nonce ID sequence;
- the intended device has an active Ed25519 key and active contract for the target RS.

## 6. Configure Supplier backend

Copy the new variables from `backend/.env.example` into the Supplier backend `.env`:

```dotenv
CLIENT_SUPABASE_URL=https://YOUR_CLIENT_PROJECT_REF.supabase.co
CLIENT_SUPABASE_PUBLISHABLE_KEY=YOUR_CLIENT_PUBLISHABLE_KEY
CLIENT_SUPPLIER_DEVICE_ID=THE_REGISTERED_DEVICE_ID
CLIENT_SUPPLIER_PRIVATE_KEY_HEX=THE_64_HEX_PRIVATE_KEY
```

Keep the existing `SUPABASE_URL` and `SUPABASE_ANON_KEY` pointed at the **Supplier's own Supabase project**. Do not replace them with Client project values.

## 7. Configure Client app

Keep Client app `.env` pointed at the **Client Supabase project** using its normal `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and/or `SUPABASE_PUBLISHABLE_KEY` settings. Keep `ENABLE_PACKAGE_RECEIVING_API=0` during first deployment and smoke tests.

## 8. Test in this order

1. `GET https://YOUR_CLIENT_PROJECT_REF.supabase.co/functions/v1/supplier-ingest` returns `status: ok`.
2. Restart Supplier backend. Logs should show Supplier master cloud and Client ingestion gateway health separately.
3. Send one test package to an RS with an active Supplier-RS contract.
4. Confirm Client `pengiriman_linen` has one `pending` row and `detail_pengiriman_linen` has every EPC.
5. Confirm Supplier receives and stores the cloud `verification_code` and `package_id` locally.
6. Login as the matching RS account. Its package list should show the new package.
7. Login as another RS account. The first RS package must not appear.
8. Try the first package ID and verification code from the other RS account. `get_package_info` / `claim_package` must reject it.
9. Retry the same local package. It must return the same cloud package ID and verification code without inserting a duplicate.
10. Test a changed payload with the same idempotency key. It must be rejected as an idempotency mismatch.
11. Only after all tests pass, set `ENABLE_PACKAGE_RECEIVING_API=1` for the Client app.

## Important behavior

- Supplier's old `VRF-XXXXXX` code is retained as a local package reference (`package_code`). It is not the code entered in Client.
- Client Supabase creates the actual receiving `verification_code` (`VC-...`). Supplier stores and displays that returned cloud code only after successful ingestion.
- If Client cloud is offline, Supplier keeps the package in its local pending queue and does not show the local reference as a valid Client verification code.
- A package already accepted by Client Supabase cannot be cancelled from Supplier because that would orphan the cloud package.
- Every retry uses a new nonce and the same idempotency key. A used nonce is never reused.
