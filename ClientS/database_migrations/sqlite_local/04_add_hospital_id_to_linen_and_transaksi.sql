-- =============================================================================
-- MIGRASI 04: PENAMBAHAN KOLOM HOSPITAL_ID PADA LINEN, TRANSAKSI_LINEN, & RIWAYAT_LINEN
-- Tujuan: Isolasi penuh seluruh data aktivitas dan master linen per rumah sakit (Multi-Tenant)
-- Database: SQLite Lokal (ClientS)
-- =============================================================================

-- 1. Tambahkan kolom hospital_id pada linen
ALTER TABLE linen ADD COLUMN hospital_id INTEGER NULL;
CREATE INDEX IF NOT EXISTS ix_linen_hospital_id ON linen (hospital_id);

-- 2. Tambahkan kolom hospital_id pada transaksi_linen
ALTER TABLE transaksi_linen ADD COLUMN hospital_id INTEGER NULL;
CREATE INDEX IF NOT EXISTS ix_transaksi_linen_hospital_id ON transaksi_linen (hospital_id);

-- 3. Tambahkan kolom hospital_id pada riwayat_linen
ALTER TABLE riwayat_linen ADD COLUMN hospital_id INTEGER NULL;
CREATE INDEX IF NOT EXISTS ix_riwayat_linen_hospital_id ON riwayat_linen (hospital_id);

-- 4. Backfill data historis ke RSUD Aminah (hospital_id = 1)
UPDATE linen SET hospital_id = 1 WHERE hospital_id IS NULL;
UPDATE transaksi_linen SET hospital_id = 1 WHERE hospital_id IS NULL;
UPDATE riwayat_linen SET hospital_id = 1 WHERE hospital_id IS NULL;
UPDATE ruangan SET hospital_id = 1 WHERE hospital_id IS NULL;

