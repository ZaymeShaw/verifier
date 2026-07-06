from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .routes import router

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(title="Verifier API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)

    if FRONTEND_ROOT.exists():
        app.mount("/frontend", StaticFiles(directory=str(FRONTEND_ROOT), html=True), name="frontend")

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse("/frontend/index.html")

    @app.get("/frontend")
    def frontend_index() -> RedirectResponse:
        return RedirectResponse("/frontend/index.html")

    @app.get("/index.html")
    def index_html() -> RedirectResponse:
        return RedirectResponse("/frontend/index.html")

    @app.get("/live.html")
    def live_html() -> RedirectResponse:
        return RedirectResponse("/frontend/live.html")

    @app.get("/summary.html")
    def summary_html() -> RedirectResponse:
        return RedirectResponse("/frontend/summary.html")

    return app


app = create_app()
