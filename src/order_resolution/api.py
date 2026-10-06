import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException

from .graph import build_graph, resolve
from .models import Approval, Request, Resolution
from .planner import Planner
from .store import Conflict, Store
from .tools import OrderNotFound, Tools


class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {"level": record.levelname, "event": record.getMessage()}
        for key in ("case_id", "status", "tool", "attempt", "duration_ms"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data)


def create_app(database_path=None, tools=None, planner=None, reviewer_token=None):
    @asynccontextmanager
    async def lifespan(app):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("order_resolution")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        app.state.store = Store(database_path or os.getenv("DATABASE_PATH", "demo.db"))
        app.state.graph = build_graph(tools or Tools(), planner or Planner())
        app.state.lock = asyncio.Lock()
        app.state.token = reviewer_token or os.getenv("REVIEWER_TOKEN")
        yield
        logger.removeHandler(handler)

    app = FastAPI(title="Order Resolution Agent", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "portfolio-demo"}

    @app.post("/resolutions", response_model=Resolution)
    async def resolutions(
        request: Request,
        idempotency_key: str = Header(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"),
    ):
        # One worker by design. Lock protects lookup + graph + durable commit locally.
        async with app.state.lock:
            try:
                existing = app.state.store.existing(idempotency_key, request)
                if existing:
                    return existing
                result = await resolve(app.state.graph, request)
                return app.state.store.finish_new(idempotency_key, request, result)
            except Conflict as exc:
                raise HTTPException(409, str(exc)) from None
            except OrderNotFound:
                raise HTTPException(404, "Order not found") from None

    @app.get("/resolutions/{case_id}", response_model=Resolution)
    def get_resolution(case_id: str):
        try:
            return app.state.store.get(case_id)
        except KeyError:
            raise HTTPException(404, "Case not found") from None

    @app.post("/resolutions/{case_id}/approval", response_model=Resolution)
    async def approval(
        case_id: str, decision: Approval, authorization: str | None = Header(default=None)
    ):
        if not app.state.token:
            raise HTTPException(503, "Reviewer token is not configured")
        expected = "Bearer " + app.state.token
        if not secrets.compare_digest((authorization or "").encode(), expected.encode()):
            raise HTTPException(401, "Reviewer authorization required")
        async with app.state.lock:
            try:
                return app.state.store.review(case_id, decision.approve)
            except KeyError:
                raise HTTPException(404, "Case not found") from None
            except Conflict as exc:
                raise HTTPException(409, str(exc)) from None

    return app


app = create_app()
