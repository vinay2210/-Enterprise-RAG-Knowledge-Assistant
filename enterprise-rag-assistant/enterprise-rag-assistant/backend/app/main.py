"""
Application entry point.
Run with:  uvicorn app.main:app --reload
"""
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings
from app.database import init_db, SessionLocal
from app.utils.logger import logger
from app.api import auth_routes, drive_routes, chat_routes, document_routes

settings = get_settings()
scheduler = BackgroundScheduler()


def _allowed_origins(frontend_url: str) -> list[str]:
    origins = {frontend_url.rstrip("/")}
    parsed = urlparse(frontend_url)

    local_hosts = {"localhost", "127.0.0.1", "0.0.0.0"}
    if parsed.scheme and parsed.port and parsed.hostname in local_hosts:
        for host in local_hosts:
            origins.add(f"{parsed.scheme}://{host}:{parsed.port}")

    return sorted(origins)


def scheduled_sync_job():
    from app.drive.sync import run_sync
    db = SessionLocal()
    try:
        count = run_sync(db)
        logger.info(f"Scheduled sync complete - {count} files in Drive folder.")
    except Exception as e:
        logger.exception(f"Scheduled sync failed: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up: initializing database...")
    init_db()
    scheduler.add_job(
        scheduled_sync_job,
        "interval",
        seconds=settings.drive_poll_interval_seconds,
        id="drive_sync",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Drive polling scheduled every {settings.drive_poll_interval_seconds}s")
    yield
    logger.info("Shutting down scheduler...")
    scheduler.shutdown(wait=False)


app = FastAPI(title="Enterprise RAG Knowledge Assistant", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(settings.frontend_url),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"{request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"{request.method} {request.url.path} -> {response.status_code}")
    return response


app.include_router(auth_routes.router)
app.include_router(drive_routes.router)
app.include_router(chat_routes.router)
app.include_router(document_routes.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return RedirectResponse(settings.frontend_url)