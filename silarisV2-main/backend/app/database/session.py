"""SQLite database engine and additive local-cache migrations."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.config import get_settings

settings = get_settings()
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_supplier_cloud_columns() -> None:
    """Additive-only changes. Never drop or rebuild existing local tables."""
    with engine.begin() as connection:
        table_exists = connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pengiriman_temp'"
        ).first()
        if table_exists:
            existing = {
                row[1] for row in connection.exec_driver_sql("PRAGMA table_info(pengiriman_temp)").fetchall()
            }
            additions = {
                "kode_verifikasi_cloud": "TEXT NULL",
                "cloud_package_code": "TEXT NULL",
                "cloud_package_id": "INTEGER NULL",
                "cloud_manifest_hash": "VARCHAR(64) NULL",
                "cloud_synced_at": "DATETIME NULL",
                "last_error": "TEXT NULL",
            }
            for column_name, column_type in additions.items():
                if column_name not in existing:
                    connection.exec_driver_sql(
                        f'ALTER TABLE pengiriman_temp ADD COLUMN "{column_name}" {column_type}'
                    )

        rs_exists = connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rumah_sakit'"
        ).first()
        if rs_exists:
            existing_rs = {
                row[1] for row in connection.exec_driver_sql("PRAGMA table_info(rumah_sakit)").fetchall()
            }
            additions_rs = {
                "is_active": "BOOLEAN NOT NULL DEFAULT 1",
                "updated_at": "DATETIME NULL",
                "client_email": "VARCHAR(255) NULL",
                "client_user_id": "VARCHAR(64) NULL",
            }
            for column_name, column_type in additions_rs.items():
                if column_name not in existing_rs:
                    connection.exec_driver_sql(
                        f'ALTER TABLE rumah_sakit ADD COLUMN "{column_name}" {column_type}'
                    )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
