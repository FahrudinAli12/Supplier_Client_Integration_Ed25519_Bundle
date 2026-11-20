"""
FastAPI Application Entry Point.

- Creates all SQLite tables on startup
- Starts background sync and health-check tasks
- Wires up serial service callbacks for WebSocket broadcast
- Mounts all routers and the WebSocket endpoint
- Configures CORS for local network access
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database.session import engine, ensure_supplier_cloud_columns
from app.database.models import Base
from app.services.serial_service import serial_service
from app.services.websocket_manager import ws_manager
from app.services.sync_service import sync_service
from app.services.supabase_client import supabase_client
from app.config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

settings = get_settings()


# ────────────────────── Serial Callbacks ──────────────────────

async def _on_epc_detected(epc: str, rssi: str):
    """Called by serial_service when a new EPC is detected — broadcast to all WS clients."""
    await ws_manager.broadcast_epc_detected(epc, rssi)


async def _on_serial_error(message: str):
    """Called by serial_service on port-level errors — broadcast to all WS clients."""
    await ws_manager.broadcast_error(message)
    await ws_manager.broadcast_connection_state(
        serial_connected=serial_service.serial_connected,
        cloud_online=sync_service.combined_cloud_online,
    )


# ────────────────────── Lifespan ──────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    # === STARTUP ===
    logger.info("Starting RFID Linen Pro backend...")

    # Create all SQLite tables
    Base.metadata.create_all(bind=engine)
    ensure_supplier_cloud_columns()
    logger.info("SQLite database tables and additive Supplier-to-Client columns created/verified")

    # Wire up serial service callbacks
    serial_service.set_callbacks(
        on_epc_detected=_on_epc_detected,
        on_error=_on_serial_error,
    )

    # Check for connected RFID reader hardware on startup (auto-connect if single port found)
    logger.info("Checking for connected RFID reader hardware...")
    try:
        from app.routers.ports import list_serial_ports
        matching_ports = list_serial_ports()
        if len(matching_ports) == 1:
            single_port = matching_ports[0]["port"]
            logger.info(f"Auto-connecting to single matching serial port: {single_port}")
            await serial_service.open_port(single_port)
        elif len(matching_ports) > 1:
            logger.info(f"Found {len(matching_ports)} matching serial ports. Waiting for user selection.")
        else:
            logger.info("No matching RFID reader serial ports found on startup.")
    except Exception as port_err:
        logger.warning(f"Failed to check or auto-connect serial ports on startup: {port_err}")

    # Start background sync service (cloud health check + pending upload loop)
    await sync_service.start()
    logger.info("Background sync service started")

    logger.info("Backend startup complete ✓")

    yield  # Application is running

    # === SHUTDOWN ===
    logger.info("Shutting down RFID Linen Pro backend...")

    # Stop scanning if active
    await serial_service.stop_inventory()
    await serial_service.close_port()

    # Stop background tasks
    await sync_service.stop()

    # Close httpx client
    await supabase_client.close()

    logger.info("Backend shutdown complete")


# ────────────────────── App Creation ──────────────────────

from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import traceback

app = FastAPI(
    title="RFID Linen Pro API",
    description="Backend API untuk Sistem Informasi RFID Produsen Linen",
    version="1.0.0",
    lifespan=lifespan,
)

from app.services.trusted_local import validate_trusted_local_access
from fastapi import HTTPException

# Pure ASGI Trusted Local Security Middleware — avoids BaseHTTPMiddleware threadpool bottlenecks
class TrustedLocalASGIMiddleware:
    def __init__(self, app_inst):
        self.app = app_inst

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/"):
            request = Request(scope, receive=receive)
            try:
                validate_trusted_local_access(request)
            except HTTPException as exc:
                response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

app.add_middleware(TrustedLocalASGIMiddleware)

# CORS — the frontend is served same-origin; session cookies are not shared cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*", "X-Supplier-Request", "X-Supplier-Machine-Auth"],
)

# ────────────────────── Global Exception Handlers ──────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global handler for unexpected server errors (500) — prevents stack trace leakage."""
    logger.error(
        f"Unhandled Exception on {request.method} {request.url.path}: {exc}\n{traceback.format_exc()}"
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Terjadi kesalahan pada server."},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Custom handler for Pydantic validation errors (422) — formats into consistent detail string."""
    error_messages = []
    for err in exc.errors():
        loc_parts = [str(loc) for loc in err.get("loc", []) if loc != "body"]
        field_path = " -> ".join(loc_parts)
        msg = err.get("msg", "input tidak valid")
        if field_path:
            error_messages.append(f"Field '{field_path}': {msg}")
        else:
            error_messages.append(msg)

    formatted_detail = "; ".join(error_messages) if error_messages else "Format input data tidak valid."
    logger.warning(f"Validation Error on {request.method} {request.url.path}: {formatted_detail}")
    return JSONResponse(
        status_code=422,
        content={"detail": f"Data tidak valid: {formatted_detail}"},
    )


# ────────────────────── Mount Routers ──────────────────────

from app.routers import auth, dashboard, kategori, nama_linen, linen, rumah_sakit, pengiriman, ports

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(kategori.router)
app.include_router(nama_linen.router)
app.include_router(linen.router)
app.include_router(rumah_sakit.router)
app.include_router(pengiriman.router)
app.include_router(ports.router)


# ────────────────────── Mount WebSocket ──────────────────────

from app.websocket import websocket_endpoint

app.websocket("/ws")(websocket_endpoint)


import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# ────────────────────── Serve Frontend ──────────────────────

frontend_vanilla_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend-vanilla"))

if os.path.exists(frontend_vanilla_path):
    # Serve static JS modules under /js/
    app.mount("/js", StaticFiles(directory=os.path.join(frontend_vanilla_path, "js")), name="frontend-js")

    # SPA Catch-All: any route (including root /, /pendaftaran, /v2, etc.) serves index.html
    @app.get("/{path:path}", tags=["Frontend"], include_in_schema=False)
    @app.get("/", tags=["Frontend"], include_in_schema=False)
    async def serve_spa(path: str = ""):
        """Serve SPA index.html for all non-API GET routes (History API fallback)."""
        file_path = os.path.join(frontend_vanilla_path, path)
        if path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_vanilla_path, "index.html"))


