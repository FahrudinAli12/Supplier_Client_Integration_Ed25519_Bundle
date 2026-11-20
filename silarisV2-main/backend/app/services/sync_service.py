"""Background package retry worker and authenticated hospital-cache sync."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import SessionLocal
from app.database.models import PengirimanTemp, RumahSakitLocal
from app.services.supabase_client import supabase_client
from app.services.client_package_gateway import client_package_gateway
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)
settings = get_settings()


class SyncService:
    """Monitor the one Supabase project and retry locally queued packages."""

    def __init__(self):
        self.cloud_online: bool = False
        self.client_ingestion_online: bool = False
        self._sync_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None

    @property
    def combined_cloud_online(self) -> bool:
        return self.cloud_online and self.client_ingestion_online

    async def start(self):
        self.cloud_online = await supabase_client.health_check()
        self.client_ingestion_online = await client_package_gateway.health_check()
        logger.info(
            "Initial single-project status: supabase_auth=%s supplier_ingestion=%s",
            self.cloud_online,
            self.client_ingestion_online,
        )
        # Master-data sync is deliberately deferred until a Supplier user logs in.
        # This ensures PostgREST receives that user's JWT and RLS remains effective.
        self._sync_task = asyncio.create_task(self._sync_loop())
        self._health_task = asyncio.create_task(self._health_check_loop())

    async def stop(self):
        for task in (self._sync_task, self._health_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._sync_task = None
        self._health_task = None

    async def _health_check_loop(self):
        while True:
            try:
                await asyncio.sleep(10)
                was_online = self.combined_cloud_online
                self.cloud_online = await supabase_client.health_check()
                self.client_ingestion_online = await client_package_gateway.health_check()
                if was_online != self.combined_cloud_online:
                    logger.info("Combined cloud status changed: %s", self.combined_cloud_online)
                    from app.services.serial_service import serial_service
                    await ws_manager.broadcast_connection_state(
                        serial_connected=serial_service.serial_connected,
                        cloud_online=self.combined_cloud_online,
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Health check loop error: %s", exc)
                await asyncio.sleep(10)

    async def _sync_loop(self):
        while True:
            try:
                await asyncio.sleep(settings.SYNC_LOOP_INTERVAL_SECONDS)
                if not self.client_ingestion_online:
                    continue
                db = SessionLocal()
                try:
                    pending = (
                        db.query(PengirimanTemp)
                        .filter(PengirimanTemp.status_upload.in_(["pending", "gagal"]))
                        .order_by(PengirimanTemp.timestamp.asc())
                        .all()
                    )
                    for record in pending:
                        try:
                            await self._try_upload(db, record)
                        except Exception as rec_err:
                            logger.exception(
                                "Per-record ingestion error for %s: %s",
                                getattr(record, "kode_verifikasi", "unknown"),
                                rec_err,
                            )
                finally:
                    db.close()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Sync loop outer error: %s", exc)

    async def _try_upload(self, db: Session, record: PengirimanTemp) -> bool:
        try:
            local_rs = db.query(RumahSakitLocal).filter(
                RumahSakitLocal.rs_id == str(record.rs_id)
            ).first()
            if not local_rs or not (local_rs.kode_rs or "").strip():
                raise ValueError(
                    f"Kode RS untuk rs_id {record.rs_id} tidak ditemukan pada cache Supplier. "
                    "Paket ditahan agar tidak salah tujuan."
                )
            if not local_rs.is_active:
                raise ValueError(
                    f"Rumah sakit {local_rs.kode_rs} sedang nonaktif. Paket tidak dikirim."
                )

            items = json.loads(record.daftar_epc) if record.daftar_epc else []
            if not isinstance(items, list) or not items:
                raise ValueError("Manifest paket kosong atau formatnya tidak valid.")

            device_id = settings.CLIENT_SUPPLIER_DEVICE_ID.strip()
            cloud_package_code = f"{device_id[:32]}-{record.temp_id}-{record.kode_verifikasi}"
            result = await client_package_gateway.upload_package(
                hospital_code=local_rs.kode_rs,
                package_code=cloud_package_code,
                items=items,
                idempotency_key=f"{device_id}:{record.temp_id}:{record.kode_verifikasi}",
                catatan=f"Pengiriman Supplier; referensi lokal {record.temp_id}",
            )

            if result:
                record.status_upload = "sukses"
                record.kode_verifikasi_cloud = str(result["verification_code"])
                record.cloud_package_code = str(result.get("package_code") or cloud_package_code)
                record.cloud_package_id = int(result["package_id"])
                record.cloud_manifest_hash = str(result["manifest_hash"])
                record.cloud_synced_at = datetime.now(timezone.utc)
                record.last_error = None
                db.commit()
                logger.info(
                    "Paket lokal %s tersimpan di Supabase: package_id=%s, kode_cloud=%s",
                    record.kode_verifikasi,
                    record.cloud_package_id,
                    record.kode_verifikasi_cloud,
                )
                return True

            record.percobaan_ke += 1
            rejection_reason = getattr(client_package_gateway, "last_rejection_error", None) or "Gateway tidak mengembalikan hasil penerimaan paket."
            record.last_error = rejection_reason
            if record.percobaan_ke >= settings.SYNC_MAX_RETRY_BEFORE_PERMANENT_FAIL:
                record.status_upload = "gagal_permanen"
            else:
                record.status_upload = "gagal"
            db.commit()
            return False
        except Exception as exc:
            db.rollback()
            kode_verifikasi = getattr(record, "kode_verifikasi", "unknown")
            logger.error("Upload exception for %s: %s", kode_verifikasi, exc)
            try:
                record.percobaan_ke += 1
                record.last_error = str(exc)
                if record.percobaan_ke >= settings.SYNC_MAX_RETRY_BEFORE_PERMANENT_FAIL:
                    record.status_upload = "gagal_permanen"
                else:
                    record.status_upload = "gagal"
                db.commit()
            except Exception as commit_err:
                db.rollback()
                logger.error("Failed to persist upload failure status: %s", commit_err)
            return False

    async def sync_down_rumah_sakit(self, access_token: Optional[str] = None) -> bool:
        """Refresh local cache using backend admin or provided Supplier access token."""
        rows = await supabase_client.get_rumah_sakit_full(access_token)
        if rows is None:
            logger.warning("Could not refresh rumah_sakit cache; keeping last known local data")
            return False

        db = SessionLocal()
        try:
            cached_rows = db.query(RumahSakitLocal).all()
            if not rows and cached_rows:
                logger.error(
                    "Supabase returned an empty rumah_sakit list while local cache has %s rows; "
                    "cache was left unchanged to avoid hiding data after an RLS/configuration error.",
                    len(cached_rows),
                )
                return False

            # Mark cached rows inactive first, then upsert the authoritative cloud rows.
            # Do not delete cache rows because local package history still references them.
            for cached in cached_rows:
                cached.is_active = False

            for row in rows:
                cloud_id = row.get("id")
                if cloud_id is None:
                    continue
                rs_id = str(int(cloud_id))
                cached = db.query(RumahSakitLocal).filter(
                    RumahSakitLocal.rs_id == rs_id
                ).first()
                if cached is None:
                    cached = RumahSakitLocal(rs_id=rs_id)
                    db.add(cached)
                cached.kode_rs = row.get("kode_rs")
                cached.nama_rs = row.get("nama_rs")
                cached.alamat = row.get("alamat")
                cached.is_active = bool(row.get("is_active", True))
                cached.updated_at = None
                cached.timestamp = datetime.now(timezone.utc)
            db.commit()
            logger.info("Synced %s rumah_sakit records to local cache", len(rows))
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def try_upload_now(self, db: Session, record: PengirimanTemp) -> bool:
        if not self.client_ingestion_online:
            return False
        return await self._try_upload(db, record)


sync_service = SyncService()
