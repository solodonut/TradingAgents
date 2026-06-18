"""Chat routes: session CRUD, portfolio extraction, SSE token streaming."""

import queue
import threading
import uuid

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from sse_starlette.sse import EventSourceResponse

from api.schemas import (
    ChatRequest,
    ChatSessionCreate,
    PortfolioExtractResponse,
    PortfolioHolding,
)
from tradingagents.advisor.context import build_report_context
from tradingagents.advisor.engine import run_chat
from tradingagents.advisor.prompt import build_system_prompt
from tradingagents.advisor.tools import ADVISOR_TOOLS

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _holdings_text(holdings: list[PortfolioHolding]) -> str:
    if not holdings:
        return ""
    lines = []
    for h in holdings:
        label = h.name or h.ticker
        bits = [label]
        if h.shares is not None:
            bits.append(f"{h.shares} 股")
        if h.weight is not None:
            bits.append(f"占比 {h.weight}%")
        if h.avg_cost is not None:
            bits.append(f"成本 {h.avg_cost}")
        if h.current_price is not None:
            bits.append(f"现价 {h.current_price}")
        if h.market_value is not None:
            bits.append(f"市值 {h.market_value}")
        if h.unrealized_pnl is not None:
            bits.append(f"持有盈亏 {h.unrealized_pnl}")
        if h.return_rate is not None:
            bits.append(f"持有收益率 {h.return_rate}%")
        if h.daily_pnl is not None:
            bits.append(f"当日/昨日收益 {h.daily_pnl}")
        if h.daily_return_rate is not None:
            bits.append(f"当日收益率 {h.daily_return_rate}%")
        if h.action is not None:
            bits.append(f"操作 {h.action}")
        lines.append(": ".join([bits[0], ", ".join(bits[1:])]) if len(bits) > 1 else bits[0])
    return "\n".join(lines)


@router.post("/sessions")
def create_session(req: ChatSessionCreate, request: Request) -> dict:
    from api.main import get_store

    store = get_store()
    title = None
    if req.run_id:
        run = store.get_run(req.run_id)
        if run is not None:
            title = f"{run.ticker} ({run.trade_date})"
    session_id = uuid.uuid4().hex
    store.create_chat_session(session_id, run_id=req.run_id, title=title)
    return {"session_id": session_id}


@router.get("/sessions")
def list_sessions() -> list[dict]:
    from api.main import get_store

    return [s.model_dump() for s in get_store().list_chat_sessions()]


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    from api.main import get_store

    store = get_store()
    session = store.get_chat_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    messages = store.list_chat_messages(session_id)
    return {
        "session": session.model_dump(),
        "messages": [m.model_dump() for m in messages],
    }


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    from api.main import get_store

    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    store.delete_chat_session(session_id)
    return {"session_id": session_id, "status": "deleted"}


@router.post("/sessions/{session_id}/portfolio", response_model=PortfolioExtractResponse)
async def extract_portfolio(
    session_id: str,
    request: Request,
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
) -> PortfolioExtractResponse:
    from api.main import get_store
    from tradingagents.advisor.vision import extract_holdings, merge_portfolio_rows

    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")

    uploads = list(files or [])
    if not uploads and file is not None:
        uploads.append(file)
    if not uploads:
        raise HTTPException(status_code=400, detail="no portfolio images uploaded")

    _, vision_llm = request.app.state.chat_llm_factory()
    existing, _ = store.get_portfolio(session_id)
    holdings = existing
    for upload in uploads:
        image_bytes = await upload.read()
        extracted = extract_holdings(
            vision_llm, image_bytes, mime=upload.content_type or "image/png"
        )
        holdings = merge_portfolio_rows(holdings, extracted)
    store.save_portfolio(session_id, holdings, source="vision")
    return PortfolioExtractResponse(holdings=holdings, source="vision")


@router.put("/sessions/{session_id}/portfolio", response_model=PortfolioExtractResponse)
def save_portfolio(
    session_id: str, payload: PortfolioExtractResponse
) -> PortfolioExtractResponse:
    from api.main import get_store

    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    store.save_portfolio(session_id, payload.holdings, source="manual")
    return PortfolioExtractResponse(holdings=payload.holdings, source="manual")


@router.get("/sessions/{session_id}/portfolio", response_model=PortfolioExtractResponse)
def get_portfolio(session_id: str) -> PortfolioExtractResponse:
    from api.main import get_store

    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    holdings, source = store.get_portfolio(session_id)
    return PortfolioExtractResponse(holdings=holdings, source=source or "manual")


@router.post("/sessions/{session_id}/stream")
async def stream_chat(
    session_id: str, req: ChatRequest, request: Request
) -> EventSourceResponse:
    from api.main import get_store

    store = get_store()
    session = store.get_chat_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    user_message = req.message

    report_ctx = ""
    decision = None
    ticker = "标的"
    if session.run_id:
        run = store.get_run(session.run_id)
        if run is not None:
            decision = run.decision
            ticker = run.ticker
            report_ctx = build_report_context(run.result, decision, ticker)
    else:
        report_ctx = build_report_context(None, None, ticker)

    holdings, _ = store.get_portfolio(session_id)
    holdings_ctx = _holdings_text(holdings)
    system_prompt = build_system_prompt(report_ctx, holdings_ctx)

    history = []
    for m in store.list_chat_messages(session_id):
        if m.role == "user":
            history.append(HumanMessage(content=m.content))
        else:
            history.append(AIMessage(content=m.content))

    chat_llm, _ = request.app.state.chat_llm_factory()
    prompt = ChatPromptTemplate.from_messages(
        [("system", "{system}"), MessagesPlaceholder(variable_name="messages")]
    ).partial(system=system_prompt)
    bound = chat_llm.bind_tools(ADVISOR_TOOLS)

    class _PromptChain:
        def invoke(self, messages):
            formatted = prompt.invoke({"messages": messages})
            return bound.invoke(formatted)

    chain = _PromptChain()

    tools_by_name = {t.name: t for t in ADVISOR_TOOLS}

    store.insert_chat_message(
        uuid.uuid4().hex, session_id, "user", user_message, tool_calls=[]
    )

    q: queue.Queue = queue.Queue()

    def _worker():
        final_text = ""
        final_tool_calls: list[dict] = []
        try:
            for event in run_chat(
                chain=chain,
                history_messages=history,
                user_message=user_message,
                tools_by_name=tools_by_name,
            ):
                if event["event"] == "done":
                    final_text = event["data"]["content"]
                    final_tool_calls = event["data"]["tool_calls"]
                q.put(event)
        finally:
            if final_text:
                store.insert_chat_message(
                    uuid.uuid4().hex,
                    session_id,
                    "assistant",
                    final_text,
                    tool_calls=final_tool_calls,
                )
            q.put(None)

    threading.Thread(target=_worker, daemon=True).start()

    async def event_generator():
        import asyncio
        import json

        while True:
            try:
                item = await asyncio.to_thread(q.get, True, 1.0)
            except queue.Empty:
                if await request.is_disconnected():
                    break
                continue
            if item is None:
                break
            yield {"event": item["event"], "data": json.dumps(item["data"])}

    return EventSourceResponse(event_generator())
