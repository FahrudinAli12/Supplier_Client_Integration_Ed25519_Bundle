# 🌐 Panduan Setup Proyek Supabase Mandiri (Self-Hosted / Own Account)
## *Silaris Linen Management: Supplier & Client Integration System*

Dokumen ini merupakan panduan lengkap langkah demi langkah (*step-by-step*) jika Anda atau organisasi Anda ingin menggunakan **akun Supabase sendiri** (proyek Supabase baru) untuk menghubungkan aplikasi **Supplier** (`silarisV2-main`) dan **Client Rumah Sakit** (`ClientS`).

---

## 📌 Ringkasan Arsitektur
Sistem ini menggunakan arsitektur **Single Shared Supabase Project**:
* **Supabase Cloud:** Berfungsi sebagai pusat data (*Single Source of Truth*) pergerakan paket antar-institusi, otentikasi admin, dan validasi tanda tangan kriptografi Ed25519.
* **Supplier (`silarisV2-main`):** Mengirim paket linen baru ke cloud dengan menandatangani payload menggunakan kunci privat Ed25519.
* **Client RS (`ClientS`):** Mengambil manifest kiriman dari cloud menggunakan kode verifikasi, memverifikasi fisik tag RFID di RS, dan menjalankan operasional laundry harian secara **Offline-First** di SQLite lokal.

---

## 🚀 Tahap 1: Membuat Proyek Baru di Supabase

1. Buka browser dan login ke akun Supabase Anda di **[supabase.com](https://supabase.com)**.
2. Klik tombol **New Project**:
   * **Organization:** Pilih organisasi Anda.
   * **Name:** Masukkan nama proyek (misal: `silaris-linen-cloud`).
   * **Database Password:** Buat password yang kuat dan simpan baik-baik.
   * **Region:** Pilih wilayah server terdekat (disarankan: `Southeast Asia (Singapore)`).
   * **Pricing Plan:** Paket *Free Tier* sudah sangat cukup untuk tahap awal.
3. Tunggu 1–2 menit hingga database selesai disiapkan oleh Supabase.
4. Masuk ke menu **Project Settings** (ikon gerigi di kiri bawah) > **API**:
   * Salin **Project URL** (contoh: `https://xyzprojectref.supabase.co`).
   * Salin **Project API Keys**:
     * `anon` / `public` key (Publishable API Key).
     * `service_role` key (Secret Key — *hanya digunakan untuk setup Edge Function, jangan simpan di Git!*).

---

## 🗄️ Tahap 2: Menjalankan Script Migrasi Database (SQL Editor)

Di dashboard Supabase proyek Anda, buka menu **SQL Editor** (ikon terminal/query di sidebar kiri). Jalankan file-file SQL berikut secara berurutan. Seluruh file berada di folder `ClientS/database_migrations/cloud/`:

### 1. Migrasi Inti Paket & RPC (`07_package_communication_rpc_consolidated_r2_10_4.sql`)
* **Lokasi file:** `ClientS/database_migrations/cloud/07_package_communication_rpc_consolidated_r2_10_4.sql`
* **Fungsi:** Membuat tabel `pengiriman_linen`, `detail_pengiriman_linen`, `sync_events`, enum status, fungsi hashing kanonikal SHA-256, dan fungsi verifikasi paket.
* **Aksi:** Salin seluruh isi file, tempel ke SQL Editor Supabase, lalu klik **Run**.

### 2. Migrasi Ingest Supplier Ed25519 (`08_supplier_ingestion_edge_r2_10_5.sql`)
* **Lokasi file:** `ClientS/database_migrations/cloud/08_supplier_ingestion_edge_r2_10_5.sql`
* **Fungsi:** Menyiapkan RPC `ingest_supplier_package` dan skema validasi tanda tangan digital Ed25519 untuk gerbang penerimaan paket supplier.
* **Aksi:** Salin isi file, tempel ke SQL Editor Supabase, lalu klik **Run**.

### 3. Migrasi Multi-Tenant & Keamanan RLS (`09_supplier_memberships_and_hospital_master_rls.sql`)
* **Lokasi file:** `ClientS/database_migrations/cloud/09_supplier_memberships_and_hospital_master_rls.sql`
* **Fungsi:** Membuat tabel master `rumah_sakit`, `supplier_memberships`, dan mengaktifkan proteksi Row Level Security (RLS) agar rumah sakit tidak bisa mengintip data rumah sakit lain.
* **Aksi:** Salin isi file, tempel ke SQL Editor Supabase, lalu klik **Run**.

### 4. Migrasi Provisioning Klien Rumah Sakit (`10_hospital_client_provisioning.sql`)
* **Lokasi file:** `ClientS/database_migrations/cloud/10_hospital_client_provisioning.sql`
* **Fungsi:** Fungsi otomatisasi registrasi tenant rumah sakit baru dan isolasi data lokal.
* **Aksi:** Salin isi file, tempel ke SQL Editor Supabase, lalu klik **Run**.

### 5. Migrasi Verifikasi Paket Aman (`11_get_package_by_verification_code.sql`)
* **Lokasi file:** `ClientS/database_migrations/cloud/11_get_package_by_verification_code.sql`
* **Fungsi:** Fungsi RPC `get_package_by_verification_code` dengan proteksi tenant ID ketat (menolak akses jika rumah sakit mencoba memasukkan kode paket RS lain).
* **Aksi:** Salin isi file, tempel ke SQL Editor Supabase, lalu klik **Run**.

---

## 🔐 Tahap 3: Pembuatan Kunci Ed25519 & Registrasi Perangkat Supplier

Aplikasi Supplier menggunakan tanda tangan kriptografi **Ed25519** untuk menjamin paket yang dikirim tidak dapat dimanipulasi di perjalanan.

### Langkah 3.1: Generate Pasangan Kunci Ed25519
Buka terminal di root proyek dan jalankan skrip bawaan:
```powershell
python silarisV2-main/backend/scripts/generate_supplier_ed25519_key.py
```
Output akan menghasilkan dua baris kunci:
```
CLIENT_SUPPLIER_PRIVATE_KEY_HEX=abcdef123456... (64 karakter hex)
PUBLIC_KEY_ED25519_HEX=7890fedcba... (64 karakter hex)
```
* **Private Key:** Simpan untuk file `.env` di komputer Supplier saja.
* **Public Key:** Didaftarkan ke database Supabase Cloud.

### Langkah 3.2: Daftarkan Perangkat Supplier ke Supabase
1. Buka file template: `ClientS/supabase/SUPPLIER_DEVICE_SETUP_TEMPLATE.sql`.
2. Buka di editor teks, lalu ganti nilai variabel:
   * `v_supplier_code`: Contoh `'SUPP-001'`.
   * `v_supplier_name`: Contoh `'PT Silaris Laundry Mandiri'`.
   * `v_device_id`: Contoh `'SILARIS-SUPPLIER-DEVICE-01'`.
   * `v_public_key_hex`: Tempel nilai **`PUBLIC_KEY_ED25519_HEX`** hasil Langkah 3.1 di atas.
   * `v_hospital_code`: Kode rumah sakit pertama (Contoh: `'RS-MEDIKA-01'`).
   * `v_contract_number`: Nomor kontrak unik (Contoh: `'KTR-2026-001'`).
3. Jalankan script tersebut di **SQL Editor** Supabase.

---

## ⚡ Tahap 4: Deploy Supabase Edge Function (`supplier-ingest`)

Edge Function bertindak sebagai gerbang backend cloud tanpa server yang memvalidasi otentisitas pengiriman paket.

1. **Install Supabase CLI** (jika belum ada):
   ```bash
   npm install -g supabase
   ```
2. **Login ke Akun Supabase via CLI:**
   ```bash
   supabase login
   ```
3. **Hubungkan Folder Lokal ke Proyek Cloud:**
   ```bash
   cd ClientS
   supabase link --project-ref <PROJECT_REF_ANDA>
   ```
   *(Ganti `<PROJECT_REF_ANDA>` dengan ID proyek Anda dari URL Supabase, misal `xyzprojectref`).*
4. **Deploy Fungsi `supplier-ingest`:**
   ```bash
   supabase functions deploy supplier-ingest
   ```
5. **Uji Kesehatan Fungsi (Health Check):**
   Buka browser dan akses:
   `https://<PROJECT_REF_ANDA>.supabase.co/functions/v1/supplier-ingest`  
   Jika berhasil, akan mengembalikan respons JSON: `{"success": true, "status": "healthy"}`.

---

## 📝 Tahap 5: Konfigurasi File `.env` di Komputer Lokal

Sekarang hubungkan aplikasi komputer lokal ke proyek Supabase baru Anda:

### 1. Di Sisi Supplier (`silarisV2-main/backend/.env`)
Buat atau edit file `silarisV2-main/backend/.env`:
```env
# URL & API Key Supabase Anda
SUPABASE_URL=https://<PROJECT_REF_ANDA>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<ANON_KEY_ANDA>

# Identitas Ed25519 yang dibuat pada Tahap 3
CLIENT_SUPPLIER_DEVICE_ID=SILARIS-SUPPLIER-DEVICE-01
CLIENT_SUPPLIER_PRIVATE_KEY_HEX=<64_HEX_PRIVATE_KEY_DARI_TAHAP_3>

# Keamanan session lokal
SUPPLIER_SESSION_COOKIE_SECURE=false
SUPPLIER_SESSION_MAX_AGE_SECONDS=2592000

# Basis data lokal cache supplier
DATABASE_URL=sqlite:///./local.db

# Serial RFID Port Supplier
ALLOWED_DRIVERS=cp210
```

### 2. Di Sisi Client Rumah Sakit (`ClientS/.env`)
Buat atau edit file `ClientS/.env`:
```env
# URL & API Key Supabase Anda
SUPABASE_URL=https://<PROJECT_REF_ANDA>.supabase.co
SUPABASE_ANON_KEY=<ANON_KEY_ANDA>
SUPABASE_PUBLISHABLE_KEY=<ANON_KEY_ANDA>

# Aktifkan integrasi penerimaan paket
ENABLE_PACKAGE_RECEIVING_API=1

# Basis data lokal SQLite rumah sakit (Offline-First)
DATABASE_URL=sqlite:///Client_RumahSakit_Template.db

# Port Hardware RFID Klien RS
RFID_MASUK_PORT=COM3
RFID_KELUAR_PORT=COM4
RFID_DEMO_MODE=0
```

---

## 👤 Tahap 6: Registrasi User Admin & Data Rumah Sakit

### Langkah 6.1: Membuat User Admin Supplier
1. Di Dashboard Supabase Anda, buka menu **Authentication** > **Users**.
2. Klik **Add User** > **Create User**:
   * **Email:** Misal `admin.supplier@silaris.com`.
   * **Password:** Masukkan password login admin.
   * Centang opsi *Auto Confirm User*.
3. Buka file `ClientS/database_migrations/cloud/09b_bootstrap_supplier_admin_membership.sql`.
4. Ganti teks `CHANGE_ME_SUPPLIER_ADMIN_EMAIL` dengan email yang Anda daftarkan di atas (`admin.supplier@silaris.com`).
5. Jalankan script tersebut di **SQL Editor** Supabase. User tersebut kini resmi memiliki role `admin` supplier.

### Langkah 6.2: Menambahkan Master Rumah Sakit
1. Jalankan aplikasi Supplier:
   ```powershell
   cd silarisV2-main\backend
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
   ```
2. Buka browser di `http://127.0.0.1:8001` dan login dengan akun admin di atas.
3. Masuk ke menu **Manajemen Rumah Sakit**, lalu klik **Tambah Rumah Sakit** (misal: *RS Medika Utama*, kode: `RS-MEDIKA-01`).

---

## 🧪 Tahap 7: Verifikasi dan Uji Integrasi (End-to-End)

Untuk memastikan bahwa seluruh tabel cloud, Edge Function, dan verifikasi Ed25519 bekerja 100%:

Buka terminal di root proyek dan jalankan script pengujian otomatis:
```powershell
python run_all_tests.py
```
Seluruh 14 test suite integrasi harus berstatus **PASSED**:
* ✅ `test_gateway_signs_canonical_payload_and_returns_cloud_receipt`
* ✅ `test_gateway_rejects_duplicate_epc_before_network_call`
* ✅ `test_resolve_single_shared_project_url`
* ✅ `test_supplier_auth` & CSRF Protection
* ✅ `test_linen_decommission` & `test_ruangan_status`

---

## ❓ FAQ & Troubleshooting Supabase Mandiri

| Kendala | Penyebab Umum | Solusi |
| :--- | :--- | :--- |
| **Error `401 Unauthorized` saat kirim paket** | Public key Ed25519 belum didaftarkan di cloud atau salah salin private key di `.env` | Pastikan `CLIENT_SUPPLIER_PRIVATE_KEY_HEX` di `.env` berpasangan persis dengan `PUBLIC_KEY_ED25519_HEX` yang ada di tabel `supplier_devices`. |
| **Error `403 Forbidden` / RLS Policy** | Akun user belum terdaftar di tabel `supplier_memberships` | Jalankan script `09b_bootstrap_supplier_admin_membership.sql` dengan email akun Supabase Auth Anda. |
| **Edge Function `500 Internal Error`** | Variabel rahasia `SUPABASE_SERVICE_ROLE_KEY` belum terpasang otomatis di Edge Function | Buka Project Settings > Edge Functions > tambahkan secret `SUPABASE_SERVICE_ROLE_KEY` sesuai project key Anda. |
| **RS Lain Bisa Ambil Paket?** | Tenant ID belum terisolasi | Pastikan script migrasi nomor `11_get_package_by_verification_code.sql` sudah dijalankan di Supabase. |
| **Internet RS Terputus** | Koneksi ISP offline | **Tidak ada masalah.** Aplikasi `ClientS` tetap berjalan 100% menggunakan SQLite lokal. Data akan otomatis disinkronkan saat koneksi internet kembali pulih. |

