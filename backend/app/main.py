import time
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.core.errors import install_error_handlers
from app.core.security import tokens_match
from app.db import get_engine
from app.logging_setup import configure_logging
from app.routers import (
    admin,
    appointments,
    auth,
    customers,
    dashboard,
    documents,
    estimates,
    history,
    inspections,
    invoices,
    payments,
    photos,
    public,
    reminders,
    reports,
    settings,
    work_orders,
)

log = structlog.get_logger()

API_PREFIX = "/api"


def create_app() -> FastAPI:
    cfg = get_settings()
    configure_logging(cfg.log_level, json=cfg.environment != "development")

    app = FastAPI(
        title="Shop API",
        version="0.1.0",
        description="Customers, vehicles, work orders, estimates, invoices, and payments "
        "for a one-person repair shop.",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-amz-cf-id") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        secret = cfg.origin_secret.get_secret_value()
        if secret and not tokens_match(request.headers.get("x-origin-secret"), secret):
            # Only CloudFront knows this header; direct hits on the Function URL are refused.
            return JSONResponse(
                status_code=403, content={"error": {"code": "forbidden", "message": "Forbidden."}}
            )
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round((time.perf_counter() - start) * 1000, 1),
        )
        structlog.contextvars.clear_contextvars()
        return response

    @app.get(f"{API_PREFIX}/health", tags=["health"])
    def health():
        db_ok = True
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            log.exception("health_db_failed")
            db_ok = False
        status = 200 if db_ok else 503
        return JSONResponse(
            status_code=status, content={"status": "ok" if db_ok else "degraded", "database": db_ok}
        )

    for r in (
        auth.router,
        customers.router,
        appointments.router,
        work_orders.router,
        estimates.router,
        invoices.router,
        settings.router,
        settings.public,
        dashboard.router,
        documents.router,
        public.router,
        payments.router,
        photos.router,
        inspections.router,
        history.router,
        admin.router,
        reminders.router,
        reports.router,
    ):
        app.include_router(r, prefix=API_PREFIX)

    return app


app = create_app()
