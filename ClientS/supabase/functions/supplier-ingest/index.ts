import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "apikey, content-type, x-supplier-device-id, x-supplier-timestamp, x-supplier-nonce, x-supplier-signature",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

function jsonResponse(body: Record<string, unknown>, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json; charset=utf-8" },
  });
}

const EDGE_TRIM_RE =
  /^[\u0020\u0009-\u000D\u0085\u00A0\u1680\u180E\u2000-\u200D\u2028\u2029\u202F\u205F\u3000\uFEFF]+|[\u0020\u0009-\u000D\u0085\u00A0\u1680\u180E\u2000-\u200D\u2028\u2029\u202F\u205F\u3000\uFEFF]+$/gu;

function normalizeText(value: unknown): string {
  return String(value ?? "")
    .normalize("NFC")
    .replace(EDGE_TRIM_RE, "");
}

function fromHex(value: string, expectedBytes: number): Uint8Array | null {
  if (value.length !== expectedBytes * 2 || !/^[0-9a-f]+$/i.test(value)) return null;
  const out = new Uint8Array(expectedBytes);
  for (let i = 0; i < expectedBytes; i++) {
    out[i] = Number.parseInt(value.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

type PackageItem = { epc: string; kategori: string; nama_linen: string };

function normalizeItems(value: unknown): PackageItem[] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > 5000) return null;
  const seen = new Set<string>();
  const items: PackageItem[] = [];
  for (const raw of value) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
    const item = raw as Record<string, unknown>;
    let epc = normalizeText(item.epc).toUpperCase();
    if (epc.length === 28 && epc.startsWith("3000")) epc = epc.slice(4);
    if (!/^[0-9A-F]{24}$/.test(epc)) return null;
    if (seen.has(epc)) return null;
    seen.add(epc);
    items.push({
      epc,
      kategori: normalizeText(item.kategori),
      nama_linen: normalizeText(item.nama_linen),
    });
  }
  items.sort((a, b) => a.epc < b.epc ? -1 : a.epc > b.epc ? 1 : 0);
  return items;
}

function canonicalPayloadBytes(payload: {
  package_code: string;
  hospital_code: string;
  idempotency_key: string;
  catatan: string;
  items: PackageItem[];
}): Uint8Array {
  // Property order and separators intentionally match Python json.dumps(
  // ensure_ascii=False, sort_keys=True, separators=(",", ":")).
  const canonical = JSON.stringify({
    catatan: payload.catatan,
    hospital_code: payload.hospital_code,
    idempotency_key: payload.idempotency_key,
    items: payload.items,
    package_code: payload.package_code,
  });
  return new TextEncoder().encode(canonical);
}


function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const buffer = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(buffer).set(bytes);
  return buffer;
}


async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = new Uint8Array(
    await crypto.subtle.digest("SHA-256", toArrayBuffer(bytes)),
  );

  return Array.from(digest)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function verifyEd25519(
  publicKeyHex: string,
  signatureHex: string,
  canonicalMessage: string,
): Promise<boolean> {
  const publicKeyBytes = fromHex(publicKeyHex, 32);
  const signatureBytes = fromHex(signatureHex, 64);

  if (!publicKeyBytes || !signatureBytes) return false;

  const key = await crypto.subtle.importKey(
    "raw",
    toArrayBuffer(publicKeyBytes),
    { name: "Ed25519" },
    false,
    ["verify"],
  );

  return await crypto.subtle.verify(
    { name: "Ed25519" },
    key,
    toArrayBuffer(signatureBytes),
    toArrayBuffer(new TextEncoder().encode(canonicalMessage)),
  );
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });

  const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  if (!supabaseUrl || !serviceRoleKey) {
    return jsonResponse({ success: false, error: "Ingestion gateway belum dikonfigurasi." }, 503);
  }
  if (req.method === "GET") {
    return jsonResponse({ success: true, status: "ok", service: "supplier-ingest", signature: "Ed25519" });
  }
  if (req.method !== "POST") return jsonResponse({ success: false, error: "Method not allowed." }, 405);

  const deviceId = normalizeText(req.headers.get("x-supplier-device-id"));
  const timestamp = normalizeText(req.headers.get("x-supplier-timestamp"));
  const nonce = normalizeText(req.headers.get("x-supplier-nonce")).toLowerCase();
  const signature = normalizeText(req.headers.get("x-supplier-signature")).toLowerCase();
  const timestampNumber = Number(timestamp);
  const nowEpoch = Math.floor(Date.now() / 1000);

  if (!deviceId || deviceId.length > 128) {
    return jsonResponse({ success: false, error: "Device ID tidak valid." }, 401);
  }
  if (!/^\d{10}$/.test(timestamp) || !Number.isSafeInteger(timestampNumber) || Math.abs(nowEpoch - timestampNumber) > 300) {
    return jsonResponse({ success: false, error: "Timestamp request tidak valid atau kedaluwarsa." }, 401);
  }
  if (!/^[A-Za-z0-9_-]{16,128}$/.test(nonce) || !/^[a-f0-9]{128}$/.test(signature)) {
    return jsonResponse({ success: false, error: "Nonce atau signature tidak valid." }, 401);
  }

  const contentLength = Number(req.headers.get("content-length") ?? "0");
  if (contentLength > 2_000_000) return jsonResponse({ success: false, error: "Payload terlalu besar." }, 413);
  const rawBody = await req.text();
  if (new TextEncoder().encode(rawBody).length > 2_000_000) {
    return jsonResponse({ success: false, error: "Payload terlalu besar." }, 413);
  }

  let body: Record<string, unknown>;
  try {
    const parsed = JSON.parse(rawBody);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("body is not object");
    body = parsed as Record<string, unknown>;
  } catch {
    return jsonResponse({ success: false, error: "Body harus berupa objek JSON valid." }, 400);
  }

  const packageCode = normalizeText(body.package_code).toUpperCase();
  const hospitalCode = normalizeText(body.hospital_code);
  const idempotencyKey = normalizeText(body.idempotency_key);
  const catatan = normalizeText(body.catatan);
  const suppliedDigest = normalizeText(body.payload_digest).toLowerCase();
  const items = normalizeItems(body.items);

  if (!packageCode || packageCode.length > 128 || !hospitalCode || hospitalCode.length > 64 || !idempotencyKey || idempotencyKey.length > 200) {
    return jsonResponse({ success: false, error: "package_code, hospital_code, atau idempotency_key tidak valid." }, 400);
  }
  if (!/^[0-9a-f]{64}$/.test(suppliedDigest) || !items) {
    return jsonResponse({ success: false, error: "payload_digest atau daftar item tidak valid." }, 400);
  }

  const canonicalBytes = canonicalPayloadBytes({
    package_code: packageCode,
    hospital_code: hospitalCode,
    idempotency_key: idempotencyKey,
    catatan,
    items,
  });
  const computedDigest = await sha256Hex(canonicalBytes);
  if (computedDigest !== suppliedDigest) {
    return jsonResponse({ success: false, error: "Payload digest tidak cocok dengan isi paket." }, 400);
  }

  const supabase = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  // Only an active, time-valid Ed25519 key registered for this device may sign ingestion.
  const { data: keyRow, error: keyError } = await supabase
    .from("device_keys")
    .select("public_key_ed25519,key_algorithm,status,valid_from,valid_until")
    .eq("device_id", deviceId)
    .eq("key_algorithm", "Ed25519")
    .eq("status", "ACTIVE")
    .maybeSingle();

  if (keyError) {
    console.error("device_keys lookup failed", keyError.message);
    return jsonResponse({ success: false, error: "Validasi kunci perangkat gagal." }, 503);
  }
  if (!keyRow) return jsonResponse({ success: false, error: "Device key tidak terdaftar atau tidak aktif." }, 401);

  const validFrom = Date.parse(String(keyRow.valid_from));
  const validUntil = Date.parse(String(keyRow.valid_until));
  const nowMs = Date.now();
  if (!Number.isFinite(validFrom) || !Number.isFinite(validUntil) || nowMs < validFrom || nowMs > validUntil) {
    return jsonResponse({ success: false, error: "Masa berlaku device key tidak valid." }, 401);
  }

  const canonicalMessage = `${deviceId}:${timestamp}:${nonce}:${suppliedDigest}`;
  let signatureValid = false;
  try {
    signatureValid = await verifyEd25519(
      String(keyRow.public_key_ed25519), signature, canonicalMessage,
    );
  } catch (error) {
    console.error("Ed25519 verification failed", error);
    signatureValid = false;
  }
  if (!signatureValid) return jsonResponse({ success: false, error: "Signature Ed25519 tidak valid." }, 401);

  // Consume the nonce before ingestion. A retry must use a fresh nonce but the same idempotency key.
  const { error: nonceError } = await supabase.from("device_nonces").insert({
    device_id: deviceId,
    nonce,
    expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
  });
  if (nonceError) {
    if (nonceError.code === "23505") {
      return jsonResponse({ success: false, error: "Nonce sudah pernah digunakan (replay ditolak)." }, 409);
    }
    console.error("device_nonces insert failed", nonceError.message);
    return jsonResponse({ success: false, error: "Pencatatan nonce gagal." }, 503);
  }

  const { data, error } = await supabase.rpc("ingest_supplier_package", {
    p_device_id: deviceId,
    p_package_code: packageCode,
    p_hospital_code: hospitalCode,
    p_idempotency_key: idempotencyKey,
    p_payload_digest: suppliedDigest,
    p_catatan: catatan,
    p_items: items,
  });

  if (error) {
    console.error("ingest_supplier_package RPC failed", error.message);
    return jsonResponse({ success: false, error: "Cloud gagal menyimpan paket." }, 500);
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return jsonResponse({ success: false, error: "Respons ingestion RPC tidak valid." }, 502);
  }

  const result = data as Record<string, unknown>;
  const statusCode = Number(result.http_status ?? (result.success === true ? 200 : 400));
  return jsonResponse(result, Math.max(200, Math.min(statusCode, 599)));
});
