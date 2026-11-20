# 📖 Panduan Lengkap Step-by-Step Penggunaan Aplikasi Client
## *Hospital Linen Tracking & Laundry Management System (RFID UHF)*

Dokumen ini merupakan panduan operasional standar (*Standard Operating Procedure / SOP*) resmi untuk petugas laundry, perawat ruangan, dan administrator rumah sakit dalam mengoperasikan aplikasi **Client Checking & Laundry Linen RS**.

---

## 📋 Daftar Isi
1. [Inisialisasi Sistem & Login Rumah Sakit](#1-inisialisasi-sistem--login-rumah-sakit)
2. [Setup Master Data Ruangan (Aktivasi & Deaktivasi)](#2-setup-master-data-ruangan-aktivasi--deaktivasi)
3. [Penerimaan & Pendaftaran Linen Baru dari Supplier](#3-penerimaan--pendaftaran-linen-baru-dari-supplier)
4. [Sirkulasi Distribusi: Pengiriman Linen Bersih ke Ruangan (Linen Keluar)](#4-sirkulasi-distribusi-pengiriman-linen-bersih-ke-ruangan-linen-keluar)
5. [Sirkulasi Pencucian: Penerimaan Linen Kotor di Laundry (Linen Masuk)](#5-sirkulasi-pencucian-penerimaan-linen-kotor-di-laundry-linen-masuk)
6. [Monitoring & Filter Inventaris Linen](#6-monitoring--filter-inventaris-linen)
7. [Pemusnahan & Afkir Linen Rusak (Wajib Scan Fisik RFID)](#7-pemusnahan--afkir-linen-rusak-wajib-scan-fisik-rfid)
8. [Dashboard & Audit Riwayat Aktivitas](#8-dashboard--audit-riwayat-aktivitas)
9. [Troubleshooting & Penanganan Gangguan](#9-troubleshooting--penanganan-gangguan)

---

## 1. Inisialisasi Sistem & Login Rumah Sakit

### Langkah 1.1: Menjalankan Server Aplikasi
1. Hubungkan kabel USB perangkat pembaca RFID (*Electron EL-UHF-RMT01*) ke port USB komputer (misal: port `COM3` untuk Linen Masuk / Single Mode, dan `COM4` untuk Linen Keluar).
2. Buka terminal (Command Prompt / PowerShell) di folder `ClientS`:
   ```powershell
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
3. Buka browser (Google Chrome / Microsoft Edge / Brave) dan akses:
   ```
   http://127.0.0.1:8000
   ```

### Langkah 1.2: Login Akun Rumah Sakit
1. Pada halaman Login, masukkan:
   * **Kode Rumah Sakit / Tenant ID** (Contoh: `RS-MEDIKA-01` atau `RS-MW-001`).
   * **Username** dan **Password** petugas.
2. Klik tombol **Masuk ke Sistem**.
3. Sistem secara otomatis melakukan validasi kriptografi Ed25519 dan mengunci session aplikasi khusus untuk data rumah sakit Anda (*Tenant Isolation Shield*).

### Langkah 1.3: Cek Status Scanner RFID
* Perhatikan indikator di pojok kanan atas (*Top Header*) dan sidebar kiri bawah:
  * **Badge Hijau (CONNECTED):** Hardware scanner RFID terhubung dan siap membaca tag.
  * **Badge Merah (DISCONNECTED):** Scanner belum terdeteksi. Klik tombol **Test Connection** untuk melakukan inisialisasi ulang port serial UART.

---

## 2. Setup Master Data Ruangan (Aktivasi & Deaktivasi)

Menu ini digunakan untuk mengelola daftar ruangan rawat inap, ICU, IGD, OK/Kamar Operasi, dan poliklinik rumah sakit.

### Langkah 2.1: Menambah Ruangan Baru
1. Buka menu **Master Data** > **Data Ruangan** di sidebar kiri.
2. Klik tombol **+ Tambah Ruangan**.
3. Isi data formulir modal:
   * **Kode Ruangan:** Contoh: `R-MAWAR-01`, `R-ICU-02`.
   * **Nama Ruangan:** Contoh: `Ruang Mawar 001`, `ICU Lantai 2`.
   * **Keterangan:** Informasi tambahan (opsional).
4. Klik **Simpan Ruangan**.

### Langkah 2.2: Mengedit atau Menonaktifkan Ruangan
Rumah sakit dapat menonaktifkan ruangan yang sedang direnovasi atau ditutup sementara tanpa harus menghapus datanya:
1. Pada tabel ruangan, temukan ruangan yang diinginkan.
2. **Menonaktifkan Ruangan:**
   * Klik tombol **Nonaktifkan** pada kolom Aksi (ikon toggle/status).
   * Konfirmasi perubahan status. Ruangan akan berstatus **Nonaktif**.
3. **Efek Otomatis Ruangan Nonaktif:**
   * Ruangan yang berstatus **Nonaktif** secara otomatis **tidak akan muncul** pada dropdown pemilihan ruangan manapun di seluruh aplikasi (misalnya pada dropdown *Distribusi Linen Keluar* dan dropdown *Filter Lokasi Linen*).
   * Data riwayat transaksi lama yang pernah menggunakan ruangan tersebut tetap aman dan utuh (*Safe Reference Protection*).
4. **Mengaktifkan Kembali:**
   * Klik tombol **Aktifkan** pada baris ruangan yang nonaktif kapan saja ketika ruangan siap digunakan kembali.

---

## 3. Penerimaan & Pendaftaran Linen Baru dari Supplier

Tahapan ini wajib dilakukan ketika rumah sakit menerima suplai kiriman linen baru dari vendor atau mitra laundry eksternal.

> [!IMPORTANT]
> **Proteksi Keamanan Multi-Tenant:**
> Sistem hanya memproses kode verifikasi paket yang ditujukan khusus untuk rumah sakit Anda. Jika menggunakan kode paket milik rumah sakit lain, sistem akan menolak dengan pesan *"Kode verifikasi paket ini milik Rumah Sakit lain"*.

### Langkah 3.1: Mengambil Data Manifest Supplier
1. Buka menu **Settings** > **Sync Data** (`/settings?tab=sync`).
2. Perhatikan kartu **Verifikasi Linen** di sisi kiri bawah:
   * Masukkan **Kode Verifikasi / Penerimaan** yang tertera pada surat jalan supplier (Contoh: `VC-D3E5E6BD` atau `SILARIS-SUPPLIER-...`).
   * Masukkan **Nama Petugas** penerima.
   * Pilih **Ruang Tujuan** penyimpanan awal (default: *Storage / Gudang Linen*).
3. Klik tombol **Get Data** (atau tombol *Terima* pada popup notifikasi paket yang masuk).
4. Sistem akan mengunduh manifest paket dari cloud dan menampilkan rincian nama item linen yang diharapkan.

### Langkah 3.2: Scan Fisik Linen Baru
1. Letakkan tumpukan bungkusan linen baru di dekat antena RFID.
2. Pada kartu **Scan Linen**, klik tombol **Start Scan**.
3. Antena akan mendeteksi chip RFID setiap helai linen secara real-time:
   * **Tabel Linen Terdaftar:** Menampilkan linen hasil scan yang nomor EPC-nya cocok 100% dengan surat jalan cloud supplier.
   * **Tabel Linen Tidak Terdaftar:** Menampilkan tag asing yang terbaca namun tidak terdaftar di surat jalan supplier.
4. Periksa kesesuaian jumlah fisik (*Total Scan*) dengan jumlah surat jalan.

### Langkah 3.3: Menyimpan Linen ke Database Rumah Sakit
1. Klik tombol **Simpan Data**.
2. Sistem secara atomik:
   * Mendaftarkan seluruh linen yang valid ke master database lokal rumah sakit dengan status awal `tersedia` dan siklus cuci awal `0`.
   * Mencatat transaksi resmi jenis `penerimaan`.
   * Mengirim konfirmasi balik ke cloud supplier bahwa paket telah diterima (*received*).
   * Riwayat paket dapat dilihat kapan saja di tab **Log Penerimaan Linen**.

---

## 4. Sirkulasi Distribusi: Pengiriman Linen Bersih ke Ruangan (Linen Keluar)

Tahap ini dijalankan saat petugas mendistribusikan linen bersih siap pakai dari unit laundry ke ruangan perawatan pasien.

1. Buka menu **Laundry** > **Linen Keluar** (`/laundry?tab=keluar`).
2. Klik tombol **Start Scan** (ikon Play hijau/cyan menyala).
3. Lewatkan troli atau tumpukan linen bersih di depan antena RFID:
   * Tabel live scanner akan menampilkan seluruh nomor EPC, nama jenis linen, dan akumulasi siklus cuci saat ini.
4. Pada kartu **Form Pengiriman Linen**:
   * **Ruangan Tujuan:** Pilih ruangan pasien penerima dari dropdown (hanya ruangan aktif yang muncul).
   * **Nama Petugas:** Masukkan nama petugas pengirim / perawat penerima.
5. Klik tombol **Proses Pengiriman**:
   * Status seluruh linen yang tertera diubah menjadi **`dipakai`**.
   * Lokasi fisik linen diperbarui sesuai ruangan tujuan (misal: *R. Mawar 001*).
   * Transaksi tercatat di buku kas register transaksi keluar dan history.
6. Klik **Reset Tabel** untuk melayani antrean troli distribusi ruangan berikutnya.

---

## 5. Sirkulasi Pencucian: Penerimaan Linen Kotor di Laundry (Linen Masuk)

Tahap ini dijalankan saat petugas laundry menerima setoran linen kotor yang ditarik dari ruangan pasien untuk dicuci.

1. Buka menu **Laundry** > **Linen Masuk** (`/laundry?tab=masuk`).
2. Klik tombol **Start Scan**:
   * Sistem otomatis mengaktifkan reader masuk dan menonaktifkan reader keluar untuk mencegah kontaminasi data (*Standby Protection*).
3. Lewatkan kantong/troli linen kotor ke area antena RFID:
   * Setiap helai linen yang terdeteksi muncul seketika di tabel penampung sementara.
   * *Catatan Penting:* Proses scanning di layar ini murni verifikasi visual dan **belum menambah siklus cuci**.
4. Pada kartu **Form Pengambilan Linen**:
   * Lokasi default: `R. Laundry`.
   * Masukkan **Nama Petugas Laundry** penerima.
5. Klik tombol **Proses Penerimaan**:
   * Status seluruh linen diubah menjadi **`dicuci`**.
   * Lokasi fisik linen diubah menjadi `R. Laundry`.
   * **Akumulator Siklus Cuci (*Total Cuci*) bertambah (+1) secara otomatis dan sah.**
   * Transaksi tercatat resmi di sistem dan riwayat aktivitas aplikasi.

---

## 6. Monitoring & Filter Inventaris Linen

Menu **Master Data** > **Data Linen** menyediakan visibilitas menyeluruh terhadap seluruh aset linen rumah sakit dengan sistem filter multi-kriteria real-time.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  FILTER & MONITORING JUMLAH LINEN                                                           │
│  [ Total Terfilter: 24 pcs ]  [ Di Cuci: 8 ]  [ Di Pakai: 15 ]  [ Afkir: 1 ]  [Reset Filter]│
├───────────────────┬───────────────────────────┬─────────────────────┬───────────────────────┤
│ KATEGORI LINEN    │ NAMA LINEN / EPC          │ LOKASI / RUANGAN    │ SIKLUS / JUMLAH CUCI  │
│ [ Semua Kategori ]│ [ Cari nama / EPC...    ] │ [ Semua Lokasi    ] │ [ Semua Siklus Cuci ] │
└───────────────────┴───────────────────────────┴─────────────────────┴───────────────────────┘
```

### Langkah 6.1: Menyaring Data Linen Berdasarkan Kebutuhan
Gunakan kombinasi 4 kontrol filter yang tersedia di bagian atas tabel:
1. **Kategori Linen:** Saring khusus kategori tertentu (misal: *Sprei*, *Sarung Bantal*, *Selimut*, *Baju Pasien*, *Doek Operasi*).
2. **Pencarian Nama / EPC:** Ketik kata kunci nama linen atau nomor tag EPC untuk pencarian instan tanpa perlu reload halaman.
3. **Lokasi / Ruangan:** Pantau berapa banyak linen yang sedang tertahan di ruangan tertentu (misal: ruangan *R-Pasien-001*, *Storage*, atau *R. Laundry*).
4. **Siklus / Jumlah Cuci:** Pantau tingkat keausan kain linen:
   * `Baru (< 15x cuci)`: Linen yang masih baru beroperasi.
   * `Normal (15 - 49x cuci)`: Linen kondisi prima.
   * `Tinggi / Waspada (50 - 99x cuci)`: Linen yang mulai aus dan perlu pengawasan serat.
   * `Kritis / Siap Afkir (≥ 100x cuci)`: Linen yang telah melampaui batas standar pakai rumah sakit dan siap diafkirkan.

### Langkah 6.2: Membaca Live Counter Badges
Setiap kali filter diubah, 4 kotak indikator di samping kanan otomatis menghitung jumlah lembar secara live:
* **Total Terfilter:** Total helai linen yang memenuhi seluruh kriteria filter aktif.
* **Di Cuci:** Jumlah linen terfilter yang sedang berada di unit laundry.
* **Di Pakai:** Jumlah linen terfilter yang sedang terpasang di bed ruangan pasien.
* **Afkir:** Jumlah linen terfilter yang sudah dinonaktifkan/dimusnahkan.
* Klik tombol **Reset Filter** untuk mengembalikan tampilan ke seluruh data aset.

### Langkah 6.3: Menjelajahi Tab Data Linen
* **Tab Semua Linen:** Seluruh aset linen rumah sakit.
* **Tab Linen di Cuci:** Hanya linen yang berstatus sedang dicuci di laundry.
* **Tab Linen di Pakai:** Hanya linen yang sedang berada di ruangan rawat inap/pasien.
* **Tab Linen Afkir:** Buku arsip audit seluruh linen yang telah dimusnahkan beserta tanggal, alasan, dan nama petugas eksekutor.

---

## 7. Pemusnahan & Afkir Linen Rusak (Wajib Scan Fisik RFID)

Fitur ini menjamin akuntabilitas pemusnahan aset rumah sakit. Petugas **wajib melakukan scan fisik** pada kain linen yang benar-benar ada di hadapannya sebelum sistem mengizinkan proses penghapusan/afkir.

```
Alur Afkir:
Pilih Tab Scan Pemusnahan / Afkir ──► Isi Alasan & Nama Petugas ──► Klik Mulai Scan Fisik ──► Scan Tag Fisik ──► Klik Proses Pemusnahan
```

### Langkah 7.1: Membuka Menu Scan Pemusnahan
1. Buka menu **Master Data** > **Data Linen**.
2. Klik tab kelima: **Scan Pemusnahan / Afkir** (terletak di deretan tab sebelah kiri, bersebelahan dengan tab *Linen Afkir*).

### Langkah 7.2: Mengisi Parameter Formulir Pemusnahan
1. **Alasan Pemusnahan / Afkir:** Pilih alasan yang sesuai:
   * *Rusak / Robek / Berlubang*
   * *Noda Kimia / Infeksius Permanen*
   * *Lapuk / Habis Masa Pakai (Jumlah Cuci Kritis)*
   * *Terkontaminasi B3*
   * *Lainnya*
2. **Nama Petugas Eksekutor:** Masukkan nama penanggung jawab pemusnahan linen.
3. **Metode Tindakan:**
   * **Tandai Status AFKIR (Sangat Disarankan):** Linen dinonaktifkan permanen dan dikunci 100% dari transaksi laundry masuk/keluar, namun riwayat audit pencucian tetap tersimpan untuk laporan akreditasi RS.
   * **Hapus Permanen dari Database (Hard Delete):** Menghapus seluruh entri tag dari sistem.
4. **Catatan Tambahan:** Keterangan opsional (misal: *"Afkir triwulan IV ruang ICU"*).

### Langkah 7.3: Melakukan Scan Fisik Linen yang Rusak
1. Klik tombol cyan **▶ Mulai Scan Fisik**. Indikator status scanner akan berubah menjadi berkedip hijau *"Mendeteksi Tag Fisik..."*.
2. Dekatkan fisik kain linen yang rusak ke antena RFID satu per satu atau per bundel:
   * Setiap tag yang terbaca akan diverifikasi terhadap kepemilikan database RS:
     * **Badge Hijau (VALID DI RS):** Tag terdaftar sah milik rumah sakit dan dapat diproses.
     * **Badge Merah (TIDAK DIKENAL):** Tag bukan milik rumah sakit (misal tag vendor lain) dan otomatis diabaikan.
3. Kotak statistik counter di kanan atas menampilkan:
   * **TOTAL SCAN:** Total tag yang terbaca sensor.
   * **VALID DI RS:** Jumlah linen sah yang siap diafkirkan.
   * **TIDAK DIKENAL:** Tag asing yang ditolak.
4. Jika ada tag yang tidak sengaja ter-scan, klik tombol **Hapus** pada baris yang bersangkutan untuk mengeluarkannya dari daftar antrean pemusnahan.

### Langkah 7.4: Eksekusi Pemusnahan
1. Klik tombol merah **Proses Pemusnahan (X Linen)**.
2. Muncul kotak dialog konfirmasi peringatan. Klik **OK / Ya, Eksekusi**.
3. Sistem secara instan:
   * Mengubah status linen menjadi `afkir` (atau menghapus dari DB jika memilih metode hard delete).
   * Mencatat data ke tabel riwayat audit pemusnahan.
   * Mengunci tag tersebut sehingga jika suatu saat tag tersebut ter-scan di menu laundry, sistem akan menolak transaksi.
4. Anda dapat meninjau hasil pemusnahan pada tab **Linen Afkir**.

---

## 8. Dashboard & Audit Riwayat Aktivitas

Halaman **Dashboard** (`/dashboard`) adalah pusat komando operasional harian:

1. **Kartu Ringkasan Metrik (Header):**
   * **Total Linen:** Jumlah seluruh inventaris linen aktif milik rumah sakit.
   * **Linen Masuk:** Jumlah linen yang sedang berada di unit laundry (status cuci).
   * **Linen Keluar:** Jumlah linen yang sedang terdistribusi aktif di ruangan pasien.
2. **Interactive Donut Chart:**
   * Memberikan representasi visual rasio perbandingan linen yang sedang dicuci vs linen yang sedang dipakai.
3. **Riwayat Aktivitas Aplikasi Terkini:**
   * Menampilkan 5 transaksi operasional paling mutakhir di sistem (meliputi transaksi penerimaan supplier, distribusi keluar ruangan, setoran masuk laundry, dan eksekusi afkir).
   * Klik tombol **Lihat Riwayat Lengkap →** untuk melompat ke halaman audit trail terperinci.
4. **Tabel Live Scan RFID:**
   * Memantau stream pembacaan tag RFID secara real-time saat reader sedang aktif.

---

## 9. Troubleshooting & Penanganan Gangguan

| Gejala Masalah | Kemungkinan Penyebab | Langkah Solusi |
| :--- | :--- | :--- |
| **Status Scanner DISCONNECTED (Merah)** | Kabel USB reader longgar atau port COM terputus | 1. Periksa sambungan kabel USB ke komputer.<br>2. Klik tombol **Test Connection** di widget status.<br>3. Pastikan port COM tidak sedang dibuka oleh aplikasi lain (seperti PuTTY / Serial Monitor). |
| **Tag RFID Tidak Terbaca Saat Scan** | Jarak tag terlalu jauh atau orientasi antena terhalang logam | 1. Dekatkan tag linen ke bidang depan antena (jarak efektif 0.5 - 2 meter).<br>2. Hindari wadah berbahan logam tebal yang memantulkan gelombang UHF.<br>3. Pastikan tombol **Start Scan** sudah diklik (ikon beranimasi aktif). |
| **Kode Verifikasi Ditolak (Milik RS Lain)** | Operator memasukkan kode paket yang dialokasikan untuk rumah sakit mitra yang berbeda | 1. Periksa surat jalan fisik dari supplier.<br>2. Pastikan rumah sakit tujuan pada surat jalan sesuai dengan akun RS yang sedang login.<br>3. Minta supplier menerbitkan kode verifikasi yang benar untuk tenant RS Anda. |
| **Internet Rumah Sakit Terputus (Offline)** | Gangguan koneksi ISP / WiFi RS | **Operasional tetap dapat berjalan normal 100%!** Aplikasi menggunakan arsitektur *Offline-First*. Transaksi masuk, keluar, dan afkir tetap tercatat di database lokal SQLite dan otomatis diantrekan ke buffer sinkronisasi saat internet kembali online. |
| **Ruangan Tidak Muncul di Dropdown** | Ruangan diset berstatus Nonaktif | Buka menu **Master Data > Data Ruangan**, cari ruangan tersebut, dan klik tombol **Aktifkan**. |

---

> [!TIP]
> **Praktik Terbaik Pemeliharaan Sistem:**
> Lakukan backup file database lokal `Client_RumahSakit_Template.db` secara berkala (misal seminggu sekali) ke drive penyimpanan cadangan untuk menjamin keamanan arsip data rumah sakit.

