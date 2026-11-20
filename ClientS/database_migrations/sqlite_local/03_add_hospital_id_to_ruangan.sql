-- =============================================================================
-- MIGRASI 03: PENAMBAHAN KOLOM HOSPITAL_ID PADA TABEL RUANGAN (MULTI-TENANT ISOLATION)
-- Tujuan: Memisahkan master data ruangan per rumah sakit untuk pengujian / multi-hospital support
-- Database: SQLite Lokal (ClientS)
-- =============================================================================

-- 1. Tambahkan kolom hospital_id (nullable integer)
ALTER TABLE ruangan ADD COLUMN hospital_id INTEGER NULL;

-- 2. Buat indeks untuk percepatan query berdasarkan hospital_id
CREATE INDEX IF NOT EXISTS ix_ruangan_hospital_id ON ruangan (hospital_id);

-- 3. Setel ruangan lama milik RSUD Aminah (hospital_id = 1)
UPDATE ruangan SET hospital_id = 1 WHERE hospital_id IS NULL;

