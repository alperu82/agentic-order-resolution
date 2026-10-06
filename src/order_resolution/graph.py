import logging
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from .models import Proposal, Request, Resolution
from .planner import Planner
from .tools import OrderNotFound, Tools, bounded

log = logging.getLogger("order_resolution")


class State(TypedDict, total=False):
    request: Request
    case_id: str
    order: dict
    shipping: dict
    documents: list[dict]
    proposal: Proposal
    result: Resolution


def build_graph(tools: Tools, planner: Planner):
    async def gather(state):
        request = state["request"]
        order = await bounded("order", lambda: tools.order(request.order_id))
        shipping = await bounded("shipping", lambda: tools.shipping(request.order_id))
        documents = await bounded(
            "knowledge", lambda: tools.knowledge(request.issue + " " + shipping["status"])
        )
        return {"order": order, "shipping": shipping, "documents": documents}

    async def propose(state):
        proposal = await planner.propose(
            state["request"], state["order"], state["shipping"], state["documents"]
        )
        return {"proposal": proposal}

    def policy(state):
        proposal = state["proposal"]
        ids = {d["id"] for d in state["documents"]}
        supported = bool(proposal.evidence_ids) and set(proposal.evidence_ids) <= ids
        shipping = state["shipping"]["status"]
        status = "manual_review"
        amount = 0
        if supported and proposal.action == "tracking_update" and shipping == "in_transit":
            status = "completed"
        elif (
            supported
            and proposal.action == "refund"
            and shipping == "lost"
            and "loss-v1" in proposal.evidence_ids
        ):
            status = "awaiting_approval"
            amount = state["order"]["total_cents"]
        log.info("policy_decision", extra={"case_id": state["case_id"], "status": status})
        return {
            "result": Resolution(
                case_id=state["case_id"],
                order_id=state["request"].order_id,
                status=status,
                proposal=proposal,
                amount_cents=amount,
            )
        }

    graph = StateGraph(State)
    graph.add_node("gather_evidence", gather)
    graph.add_node("propose", propose)
    graph.add_node("enforce_policy", policy)
    graph.add_edge(START, "gather_evidence")
    graph.add_edge("gather_evidence", "propose")
    graph.add_edge("propose", "enforce_policy")
    graph.add_edge("enforce_policy", END)
    return graph.compile()


async def resolve(graph, request):
    case_id = str(uuid4())
    try:
        state = await graph.ainvoke({"request": request, "case_id": case_id})
        return state["result"]
    except OrderNotFound:
        raise
    except Exception:
        # Do not log exception messages: provider errors may contain sensitive input.
        log.warning("resolution_failed", extra={"case_id": case_id})
        return Resolution(
            case_id=case_id,
            order_id=request.order_id,
            status="failed",
            error="Dependency or planner unavailable; no action taken",
        )
