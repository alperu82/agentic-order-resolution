"""Bounded read tools. Retrieved text is evidence, never executable instructions."""

import asyncio
import json
import logging
import time
from importlib.resources import files

import httpx

log = logging.getLogger("order_resolution")


class OrderNotFound(Exception):
    pass


class ToolUnavailable(Exception):
    pass


async def bounded(name, operation, *, timeout=0.5, attempts=3):
    started = time.monotonic()
    for attempt in range(1, attempts + 1):
        try:
            value = await asyncio.wait_for(operation(), timeout)
            log.info(
                "tool_complete",
                extra={
                    "tool": name,
                    "attempt": attempt,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                },
            )
            return value
        except (TimeoutError, ConnectionError, httpx.TransportError):
            log.warning("tool_retry", extra={"tool": name, "attempt": attempt})
            if attempt == attempts:
                raise ToolUnavailable(f"{name} unavailable") from None
            await asyncio.sleep(0.01 * 2 ** (attempt - 1))


class Tools:
    def __init__(self):
        root = files("order_resolution").joinpath("data")
        self.orders = json.loads(root.joinpath("orders.json").read_text())
        self.documents = json.loads(root.joinpath("knowledge.json").read_text())

    async def order(self, order_id):
        order = self.orders.get(order_id)
        if order is None:
            raise OrderNotFound("order not found")
        return {
            "order_id": order_id,
            "total_cents": order["total_cents"],
            "status": order["status"],
        }

    async def shipping(self, order_id):
        order = self.orders[order_id]
        return {"status": order["shipping"], "late_days": order["late_days"]}

    async def knowledge(self, query):
        # Tiny lexical retrieval: transparent ranking, stable IDs, no vector service.
        words = set(query.lower().split())
        ranked = sorted(
            self.documents, key=lambda d: (-len(words.intersection(d["topics"])), d["id"])
        )
        return ranked[:2]
