# 📊 Entity Relationship Diagram (ERD) & Use Case Diagram
## *Sistem Informasi Client Tracking & Laundry Linen RS (ClientS)*

Dokumen ini memuat dokumentasi arsitektur data (**Entity Relationship Diagram / ERD**) dan analisis fungsional sistem (**Use Case Diagram & Spesifikasi Use Case**) untuk aplikasi **Client Checking & Laundry Linen RS (`ClientS`)**.

---

## 🗄️ 1. Entity Relationship Diagram (ERD)

### 1.1 Diagram ERD Konseptual & Relasional
Model data berikut merefleksikan basis data SQLite lokal (`Client_RumahSakit_Template.db`) yang mendukung operasi *Offline-First* serta isolasi multi-tenant rumah sakit.

```mermaid
erDiagram
    RUMAH_SAKIT ||--o{ RUANGAN : "memiliki daftar"
    RUMAH_SAKIT ||--o{ LINEN : "memiliki aset"
    RUMAH_SAKIT ||--o{ TRANSAKSI_LINEN : "membukukan"
    RUMAH_SAKIT ||--o{ RIWAYAT_LINEN : "mencatat audit"

    RUANGAN ||--o{ TRANSAKSI_LINEN : "tujuan distribusi"

    TRANSAKSI_LINEN ||--|{ DETAIL_TRANSAKSI_LINEN : "memuat rincian"
    LINEN ||--o{ DETAIL_TRANSAKSI_LINEN : "terlibat dalam"

    LINEN ||--o{ RIWAYAT_LINEN : "memiliki jejak"
    TRANSAKSI_LINEN ||--o{ RIWAYAT_LINEN : "memicu event"

    TRANSAKSI_LINEN ||--o| PAKET_RECEIVING_OPERATION : "diverifikasi oleh"

    RUMAH_SAKIT {
        int id PK
        string kode UK "Kode Unik RS (Tenant ID)"
        string nama "Nama Resmi Rumah Sakit"
        string alamat "Alamat Fisik RS"
        datetime created_at
    }

    RUANGAN {
        int id PK
        string kode_ruangan UK "Kode Ruangan (misal: R-MAWAR-01)"
        string nama_ruangan "Nama Ruangan (misal: Ruang Mawar 001)"
        string keterangan "Keterangan opsional"
        int hospital_id FK "Multi-tenant hospital ID"
        boolean is_active "Status Aktif/Nonaktif (Toggle)"
        datetime created_at
    }

    LINEN {
        int id PK
        string epc UK "Nomor Chip RFID EPC Gen2 64-hex"
        string kategori "Kategori Linen (Sprei, Baju, dll)"
        string nama_linen "Nama Item Linen"
        string lokasi "Lokasi Fisik Terkini (Storage, R. Laundry, Ruangan)"
        int total_cuci "Akumulator Siklus Cuci (+1 setiap laundry masuk)"
        string status "Status (tersedia, dipakai, dicuci, afkir)"
        int hospital_id FK "Multi-tenant hospital ID"
        datetime created_at
    }

    TRANSAKSI_LINEN {
        int id PK
        string kode_transaksi UK "Kode Unik Transaksi (TRX-...)"
        string jenis_transaksi "Jenis (penerimaan, masuk, keluar, afkir)"
        string petugas "Nama Petugas Eksekutor"
        string ruangan "Ruangan Asal/Tujuan"
        int total_linen "Total Helai Linen dalam Transaksi"
        string status "Status Transaksi (selesai, pending)"
        string catatan "Catatan Operasional"
        string reader_source "ID / Port Scanner Sumber"
        string port_source "COM Port UART (COM3, COM4)"
        int hospital_id FK "Multi-tenant hospital ID"
        datetime created_at
    }

    DETAIL_TRANSAKSI_LINEN {
        int id PK
        int transaksi_id FK "Foreign Key ke transaksi_linen.id"
        int linen_id FK "Foreign Key ke linen.id"
        string epc "Nomor Tag EPC Linen"
        string status_sebelum "Status Sebelum Transaksi"
        string status_setelah "Status Setelah Transaksi"
        datetime waktu_scan "Waktu Tag Terdeteksi"
        string keterangan "Keterangan Kondisi Item"
    }

    RIWAYAT_LINEN {
        int id PK
        int linen_id FK "Foreign Key ke linen.id"
        int transaksi_id FK "Foreign Key ke transaksi_linen.id"
        string event_type "Jenis Event (register, send, wash, decommission)"
        string lokasi_sebelumnya "Lokasi Lama Linen"
        string lokasi_sesudah "Lokasi Baru Linen"
        int hospital_id FK "Multi-tenant hospital ID"
        datetime created_at
    }

    PAKET_RECEIVING_OPERATION {
        string operation_id PK "UUID Idempotensi Operasi"
        int paket_id "ID Paket Kiriman dari Cloud Supplier"
        int hospital_id "ID Tenant Rumah Sakit Penerima"
        string installation_uid "Identitas Instalasi Klien RS"
        string verification_code "Kode Verifikasi Surat Jalan (VC-...)"
        string manifest_hash "SHA-256 Hash Manifest Kiriman"
        int scan_count "Jumlah Fisik Linen Terverifikasi"
        string lifecycle_phase "Fase (claiming, confirmed, dll)"
        string sync_state "Status Sinkronisasi Cloud"
        int transaksi_id FK "Terkait ke transaksi_linen.id"
        string failure_reason "Alasan Gagal jika Terjadi Anomali"
        datetime created_at
        datetime updated_at
    }

    PENGIRIMAN_TEMP {
        int id PK
        string payload "Buffer JSON Transaksi Offline"
        string status "Status Antrean (pending, synced, failed)"
        datetime created_at
    }

    READER_DEVICE {
        int id PK
        string device_name "Nama Perangkat Pembaca"
        string port "Port Serial Terhubung (COM3/COM4)"
        string role "Peran Scanner (masuk, keluar, hybrid)"
        boolean is_active "Status Konektivitas Perangkat"
        datetime last_seen "Waktu Deteksi Heartbeat Terakhir"
    }
```

---

### 1.2 Penjelasan Entitas & Kardinalitas (Data Dictionary)

| Entitas | Deskripsi & Aturan Integritas | Hubungan / Kardinalitas |
| :--- | :--- | :--- |
| **`rumah_sakit`** | Menyimpan identitas tenant rumah sakit. Memastikan pemisahan data antar-faskes (*Tenant Isolation*). | **1 to N** terhadap `linen`, `ruangan`, `transaksi_linen`, dan `riwayat_linen`. |
| **`ruangan`** | Master lokasi ruangan rawat inap, poliklinik, dan penunjang medis. Memiliki atribut `is_active` (toggle). Ruangan nonaktif otomatis disembunyikan dari dropdown distribusi. | **1 to N** terhadap `transaksi_linen` (*Safe Delete*: Ruangan tidak bisa dihapus jika ada linen atau transaksi aktif). |
| **`linen`** | Aset fisik kain linen yang dipasangi tag RFID UHF. Menyimpan status siklus (`tersedia`, `dipakai`, `dicuci`, `afkir`) dan akumulasi cuci (`total_cuci`). | **1 to N** terhadap `detail_transaksi_linen` dan `riwayat_linen`. |
| **`transaksi_linen`** | Header batch aktivitas sirkulasi linen (penerimaan baru, distribusi keluar ruangan, laundry kotor masuk, dan pemusnahan afkir). | **1 to N** terhadap `detail_transaksi_linen` dan `riwayat_linen`. |
| **`detail_transaksi_linen`** | Baris rincian per helai tag RFID yang diproses dalam suatu transaksi batch beserta snapshot status sebelum dan sesudah. | Menghubungkan **M to N** antara `transaksi_linen` dan `linen`. |
| **`riwayat_linen`** | Buku besar (*immutable audit trail*) perpindahan fisik dan perubahan status setiap linen dari awal registrasi hingga afkir. | Pencatatan audit histori pergerakan setiap helai linen. |
| **`paket_receiving_operation`** | Pengendali status idempotensi penerimaan kiriman paket supplier. Mencegah satu kode verifikasi diproses ganda. | **1 to 1** dengan transaksi jenis penerimaan. |
| **`pengiriman_temp`** | Buffer antrean transaksi saat internet terputus (*Offline-First*). Otomatis dikirim ke cloud saat internet kembali pulih. | Entitas antrean internal (*queue*). |
| **`reader_device`** | Menyimpan konfigurasi hardware reader RFID serial UART (COM port, baudrate, mode aktif/standby). | Entitas manajemen perangkat keras. |

---

## 🎯 2. Use Case Diagram

### 2.1 Diagram Use Case Sistem
Diagram use case di bawah memetakan interaksi 4 aktor (Petugas Laundry, Petugas Ruangan, Administrator RS, dan Sistem/Hardware Eksternal) dengan seluruh modul sistem ClientS.

```mermaid
flowchart LR
    %% Aktor
    subgraph AKTOR ["Aktor Pengguna & Eksternal"]
        PL(["Petugas / Operator Laundry"])
        PR(["Petugas Ruangan / Perawat"])
        ADM(["Administrator Master Data RS"])
        RFID[["Hardware RFID Reader (UART)"]]
        CLOUD[["Cloud Supabase (Supplier/Pusat)"]]
    end

    %% Batasan Sistem ClientS
    subgraph CLIENTS ["Sistem Aplikasi Client Checking & Laundry RS (ClientS)"]
        
        subgraph MOD_AUTH ["1. Modul Autentikasi & Inisialisasi"]
            UC_LOGIN["UC-01: Login Akun Rumah Sakit (Multi-tenant)"]
            UC_READER["UC-02: Monitor & Test Koneksi Reader RFID"]
        end

        subgraph MOD_MASTER ["2. Modul Master Data"]
            UC_RUANGAN["UC-03: Kelola Data Ruangan (Tambah/Edit/Hapus)"]
            UC_TOGGLE_RUANGAN["UC-04: Aktivasi / Nonaktifkan Ruangan"]
            UC_MONITOR_LINEN["UC-05: Filter & Monitoring Jumlah Linen"]
            UC_AFKIR["UC-06: Pemusnahan / Afkir Linen Fisik Rusak"]
        end

        subgraph MOD_LAUNDRY ["3. Modul Sirkulasi Laundry & Distribusi"]
            UC_SYNC["UC-07: Penerimaan & Verifikasi Linen Supplier"]
            UC_KELUAR["UC-08: Distribusi Linen Bersih ke Ruangan (Linen Keluar)"]
            UC_MASUK["UC-09: Penerimaan Linen Kotor di Laundry (Linen Masuk)"]
        end

        subgraph MOD_MONITORING ["4. Modul Monitoring & Pelaporan"]
            UC_DASHBOARD["UC-10: Pantau Dashboard & Live Stream Scan"]
            UC_HISTORY["UC-11: Audit Riwayat Transaksi Sirkulasi"]
            UC_LOG_SYNC["UC-12: Audit Log Penerimaan Paket Supplier"]
        end

        subgraph MOD_OFFLINE ["5. Modul Sinkronisasi & Buffer"]
            UC_OFFLINE_SYNC["UC-13: Sinkronisasi Otomatis Antrean Offline"]
        end
    end

    %% Relasi Aktor -> Use Case
    PL --> UC_LOGIN
    PL --> UC_READER
    PL --> UC_SYNC
    PL --> UC_KELUAR
    PL --> UC_MASUK
    PL --> UC_AFKIR
    PL --> UC_DASHBOARD
    PL --> UC_HISTORY

    PR --> UC_LOGIN
    PR --> UC_MONITOR_LINEN
    PR --> UC_KELUAR

    ADM --> UC_LOGIN
    ADM --> UC_RUANGAN
    ADM --> UC_TOGGLE_RUANGAN
    ADM --> UC_MONITOR_LINEN
    ADM --> UC_AFKIR
    ADM --> UC_DASHBOARD
    ADM --> UC_HISTORY
    ADM --> UC_LOG_SYNC

    %% Hubungan ke Sistem / Hardware Eksternal
    UC_READER <--> RFID
    UC_SYNC <--> RFID
    UC_KELUAR <--> RFID
    UC_MASUK <--> RFID
    UC_AFKIR <--> RFID

    UC_SYNC <--> CLOUD
    UC_OFFLINE_SYNC <--> CLOUD

    %% Relasi Include / Extend
    UC_AFKIR -.->|"<<include>>"| UC_MONITOR_LINEN
    UC_SYNC -.->|"<<include>>"| UC_READER
    UC_KELUAR -.->|"<<include>>"| UC_TOGGLE_RUANGAN
```

---

### 2.2 Tabel Spesifikasi Use Case Terperinci

| Kode UC | Nama Use Case | Aktor Terlibat | Deskripsi Singkat & Alur Utama |
| :--- | :--- | :--- | :--- |
| **UC-01** | **Login Akun Rumah Sakit** | Petugas Laundry, Perawat, Admin | Petugas memasukkan Kode RS (Tenant ID), Username, dan Password. Sistem memvalidasi kredensial dan mengunci sesi kerja hanya untuk data rumah sakit tersebut. |
| **UC-02** | **Monitor & Test Koneksi Reader** | Petugas Laundry, Hardware RFID | Sistem memeriksa port serial UART (`COM3`/`COM4`). Menampilkan indikator *CONNECTED* / *DISCONNECTED* dan menyediakan tombol *Test Connection*. |
| **UC-03** | **Kelola Master Ruangan** | Administrator RS | Menambah ruangan baru, mengedit nama/kode, atau menghapus ruangan dengan proteksi *Safe Delete* (ruangan berelasi tidak dapat dihapus sembarangan). |
| **UC-04** | **Aktivasi / Nonaktifkan Ruangan** | Administrator RS | Mengubah status ruangan menjadi Aktif atau Nonaktif. Ruangan nonaktif otomatis disembunyikan dari dropdown distribusi linen keluar tanpa menghapus data historisnya. |
| **UC-05** | **Filter & Monitoring Data Linen** | Perawat, Petugas Laundry, Admin | Menyaring linen berdasarkan Kategori, Pencarian Nama/EPC, Lokasi Ruangan, dan Siklus Cuci (<15x baru, 15-49x normal, 50-99x waspada, ≥100x kritis) dengan 4 live counter badges. |
| **UC-06** | **Pemusnahan / Afkir Linen Fisik** | Petugas Laundry, Admin, Hardware RFID | **Wajib scan fisik RFID** pada linen rusak. Sistem memvalidasi kepemilikan tag di RS, meminta alasan pemusnahan & nama petugas, lalu mengunci tag permanen dari transaksi cuci/pakai. |
| **UC-07** | **Penerimaan Linen Baru Supplier** | Petugas Laundry, Hardware RFID, Cloud Supabase | Memasukkan kode verifikasi surat jalan vendor (`VC-...`), mengambil manifest cloud, scan fisik linen baru, memetakan linen terdaftar vs tidak terdaftar, dan menyimpan secara atomik ke DB lokal. |
| **UC-08** | **Distribusi Linen Bersih (Keluar)** | Petugas Laundry, Perawat, Hardware RFID | Scan tumpukan linen bersih di troli, memilih ruangan tujuan (hanya ruangan aktif), memasukkan nama pengirim, dan memperbarui status linen menjadi `dipakai`. |
| **UC-09** | **Penerimaan Linen Kotor (Masuk)** | Petugas Laundry, Hardware RFID | Scan kantong/troli linen kotor, memproses masuk ke `R. Laundry`, memperbarui status menjadi `dicuci`, dan **menambah akumulasi siklus cuci (+1)** secara otomatis. |
| **UC-10** | **Pantau Dashboard & Live Stream** | Seluruh Petugas, Admin | Memantau ringkasan metrik total linen, linen dicuci, linen dipakai, grafik donut perbandingan rasio, live stream pembacaan antena, dan 5 riwayat aktivitas terkini. |
| **UC-11** | **Audit Riwayat Transaksi** | Petugas Laundry, Admin | Menampilkan log harian linen masuk dan keluar, beserta rincian nomor EPC dan riwayat jumlah cuci setiap helai linen per transaksi. |
| **UC-12** | **Audit Log Penerimaan Supplier** | Administrator RS | Meninjau arsip riwayat paket kiriman supplier yang pernah diterima beserta manifest itemnya. |
| **UC-13** | **Sinkronisasi Antrean Offline** | Background Worker, Cloud Supabase | Saat internet terputus (*offline*), seluruh transaksi disimpan di tabel lokal `pengiriman_temp`. Begitu internet online kembali, sistem otomatis mengirimkan data ke tabel cloud `sync_events`. |

