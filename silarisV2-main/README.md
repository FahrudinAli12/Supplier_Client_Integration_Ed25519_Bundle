# RFID Linen Pro — Single-Process Deployment System

Sistem Informasi dan Manajemen RFID Linen untuk Produsen Linen Gudang. Dirancang khusus untuk efisiensi tinggi, pengoperasian *offline-first*, dan beban minimal pada perangkat gudang melalui **Single-Process Deployment**.

---

## 🏗️ Arsitektur Sistem

Seluruh sistem disajikan oleh **satu proses tunggal** FastAPI (`uvicorn app.main:app`), menghilangkan kebutuhan web server terpisah (misalnya Nginx/Node.js) untuk frontend.

```
                  ┌──────────────────────────────────────────────┐
                  │          FastAPI Single Process              │
                  │             (Port 8000)                      │
                  ├──────────────────────┬───────────────────────┤
                  │     REST API & WS    │    Vanilla SPA        │
                  │  /api/*  |  /ws      │  Static Files & SPA   │
                  └──────────┬───────────┴───────────┬───────────┘
                             │                       │
                             ▼                       ▼
                    ┌─────────────────┐     ┌─────────────────┐
                    │ SQLite (local)  │     │   Browser Client│
                    │   local.db      │     │  (Alpine + JS)  │
                    └────────┬────────┘     └─────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Supabase Cloud  │
                    │   (PostgreSQL)  │
                    └─────────────────┘
```

### Stack Teknologi
- **Backend & Web Server**: FastAPI, Uvicorn, SQLAlchemy, PySerial Async
- **Database**: SQLite (lokal, *offline-first* cache) + Supabase Cloud (Master Cloud DB via HTTP/REST)
- **Frontend**: Vanilla JavaScript (ES Modules, History API Routing), Alpine.js, Tailwind CSS CDN
- **Komunikasi Hardware**: WebSocket persisten (`ws://localhost:8000/ws`) untuk *real-time RFID scanning*

---

## 🚀 Cara Menjalankan Aplikasi

### Opsi 1: Menjalankan via Script Batch (Rekomendasi Windows)
Cukup double-click file `run.bat` di root project, atau jalankan melalui terminal:

```cmd
run.bat
```

### Opsi 2: Menjalankan Manual via Uvicorn

1. Masuk ke folder `backend`:
   ```bash
   cd backend
   ```
2. Aktifkan virtual environment & install dependensi:
   ```bash
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Jalankan server Uvicorn:
   ```bash
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
4. Buka aplikasi di browser:
   **`http://localhost:8000/`**

---

## 📱 Daftar Halaman Aplikasi (10 Halaman SPA)

| Halaman | Route URL | Deskripsi |
|---|---|---|
| **Dashboard** | `/` | Summary statistik stok, pengiriman, dan status perangkat |
| **Pendaftaran Linen** | `/pendaftaran` | Pendaftaran EPC tag RFID baru |
| **Cek Info Linen** | `/cek-info` | Scan & cek histori individual tag linen |
| **Kirim Barang** | `/kirim-barang` | Scanning massal linen & pembuatan invoice pengiriman RS |
| **Antrean Bermasalah** | `/antrean-bermasalah` | Penanganan pengiriman tertunda/gagal sync ke cloud |
| **Manajemen Linen** | `/manajemen-linen` | Kelola master data tag linen & status ketersediaan |
| **Kategori Linen** | `/kategori-linen` | Master data kategori linen |
| **Nama Linen** | `/manajemen-nama` | Master data nama linen |
| **Rumah Sakit** | `/rumah-sakit` | Data master Rumah Sakit (synced dari Supabase Cloud) |
| **Histori Pengiriman** | `/histori-pengiriman` | Catatan histori pengiriman yang telah berhasil diupload ke Cloud |

---

## 🔒 Konfigurasi Environment & Sync

Environment variables disimpan di `backend/.env`:

```ini
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here
ALLOWED_DRIVERS=cp210
SYNC_LOOP_INTERVAL_SECONDS=30
DATABASE_URL=sqlite:///./local.db
```

- **Sinkronisasi Otomatis**: Pada saat startup, backend akan otomatis melakukan *sync-down* data Rumah Sakit dari Supabase ke cache SQLite lokal.
- **Queue Pengiriman**: Pengiriman barang di-cache di SQLite lokal terlebih dahulu sebelum di-upload ke Supabase Cloud oleh background worker.

## Client Supabase package ingestion

See `../INTEGRATION_HANDOFF.md` in the combined bundle and the Client project's `supabase/SUPPLIER_INGESTION_SETUP.md` for Ed25519 setup and deployment.
