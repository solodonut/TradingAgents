"""Chat routes: session CRUD, portfolio extraction, SSE token streaming."""

import queue
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from sse_starlette.sse import EventSourceResponse

from api.schemas import (
    ChatRequest,
    ChatSessionBulkDelete,
    ChatSessionCreate,
    ChatSessionReportsUpdate,
    ChatSessionUpdate,
    PortfolioExtractResponse,
    PortfolioHolding,
)
from tradingagents.advisor.context import build_report_context
from tradingagents.advisor.engine import run_chat
from tradingagents.advisor.export import ExportContext, create_export_tools
from tradingagents.advisor.prompt import build_system_prompt
from tradingagents.advisor.tools import ADVISOR_TOOLS

router = APIRouter(prefix="/api/chat", tags=["chat"])
REPORT_DIR = Path(__file__).resolve().parents[2] / "report"


def _completed_runs(store, run_ids: list[str]):
    if len(run_ids) != len(set(run_ids)):
        raise HTTPException(status_code=422, detail="run_ids must be unique")
    runs = []
    for run_id in run_ids:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(
                status_code=422, detail=f"analysis run not found: {run_id}"
            )
        if run.status != "completed":
            raise HTTPException(
                status_code=422,
                detail=f"analysis run is not completed: {run_id}",
            )
        runs.append(run)
    return runs


def _report_context(store, run_ids: list[str]) -> str:
    if not run_ids:
        return build_report_context(None, None, "标的")
    sections = []
    for index, run_id in enumerate(run_ids, start=1):
        run = store.get_run(run_id)
        if run is None or run.status != "completed":
            continue
        header = (
            f"# 报告 {index} · {run.ticker} · {run.trade_date} · "
            f"{run.decision or '—'}"
        )
        sections.append(
            f"{header}\n\n"
            f"{build_report_context(run.result, run.decision, run.ticker)}"
        )
    return "\n\n---\n\n".join(sections) or build_report_context(None, None, "标的")


def _chat_history(store, session_id: str) -> list:
    history = []
    for message in store.list_chat_messages(session_id):
        if message.role == "user":
            history.append(HumanMessage(content=message.content))
        else:
            history.append(AIMessage(content=message.content))
    return history


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
    requested_run_ids = req.run_ids if req.run_ids is not None else []
    if req.run_id is not None:
        requested_run_ids = [req.run_id]
    runs = _completed_runs(store, requested_run_ids)
    title = None
    if runs:
        title = f"{runs[0].ticker} ({runs[0].trade_date})"
    session_id = uuid.uuid4().hex
    store.create_chat_session(
        session_id,
        run_id=req.run_id,
        title=title,
        run_ids=req.run_ids,
    )
    return {"session_id": session_id}


@router.get("/sessions")
def list_sessions() -> list[dict]:
    from api.main import get_store

    return [s.model_dump() for s in get_store().list_chat_sessions()]


@router.delete("/sessions")
def delete_sessions(req: ChatSessionBulkDelete) -> dict:
    from api.main import get_store

    store = get_store()
    deleted: list[str] = []
    for session_id in req.session_ids:
        if store.get_chat_session(session_id) is None:
            continue
        store.delete_chat_session(session_id)
        deleted.append(session_id)
    return {"deleted": deleted}


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


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, req: ChatSessionUpdate) -> dict:
    from api.main import get_store

    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    store.rename_chat_session(session_id, req.title)
    session = store.get_chat_session(session_id)
    return session.model_dump()


@router.put("/sessions/{session_id}/reports")
def update_session_reports(
    session_id: str, req: ChatSessionReportsUpdate
) -> dict:
    from api.main import get_store

    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    _completed_runs(store, req.run_ids)
    store.replace_chat_session_run_ids(session_id, req.run_ids)
    return store.get_chat_session(session_id).model_dump()


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

    report_ctx = _report_context(store, session.run_ids)

    holdings, _ = store.get_portfolio(session_id)
    holdings_ctx = _holdings_text(holdings)
    system_prompt = build_system_prompt(report_ctx, holdings_ctx)

    history = _chat_history(store, session_id)

    chat_llm, _ = request.app.state.chat_llm_factory()

    def load_export_context() -> ExportContext:
        current_session = store.get_chat_session(session_id)
        if current_session is None:
            raise ValueError("chat session not found")
        return ExportContext(
            title=current_session.title or "chat-report",
            messages=_chat_history(store, session_id),
        )

    export_tools = create_export_tools(
        llm=chat_llm,
        load_context=load_export_context,
        report_dir=REPORT_DIR,
    )
    tools = [*ADVISOR_TOOLS, *export_tools]
    prompt = ChatPromptTemplate.from_messages(
        [("system", "{system}"), MessagesPlaceholder(variable_name="messages")]
    ).partial(system=system_prompt)
    bound = chat_llm.bind_tools(tools)

    class _PromptChain:
        def invoke(self, messages):
            formatted = prompt.invoke({"messages": messages})
            return bound.invoke(formatted)

    chain = _PromptChain()

    tools_by_name = {tool.name: tool for tool in tools}

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
