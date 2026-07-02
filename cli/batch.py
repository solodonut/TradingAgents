"""Batch analysis TUI: run the whole watchlist in order via the WebUI API."""

import time
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.live import Live

from cli.api_client import ApiClient, ApiError
from cli.batch_dashboard import BatchState
from cli.utils import (
    ask_output_language,
    detect_asset_type,
    get_analysis_date,
    select_analysts,
    select_deep_thinking_agent,
    select_llm_provider,
    select_research_depth,
    select_shallow_thinking_agent,
)

console = Console()


@dataclass
class BatchSettings:
    analysts: list[str]
    research_depth: int
    output_language: str
    trade_date: str
    llm_provider: str
    deep_think_llm: str
    quick_think_llm: str


def analysts_for_asset_type(analysts: list[str], asset_type: str) -> list[str]:
    """Crypto has no fundamentals analyst; drop it, but never return empty."""
    if asset_type != "crypto":
        return analysts
    filtered = [a for a in analysts if a != "fundamentals"]
    return filtered or analysts


def collect_settings() -> BatchSettings:
    """Interactively gather one shared settings set for the whole batch."""
    provider, _url = select_llm_provider()
    deep = select_deep_thinking_agent(provider)
    quick = select_shallow_thinking_agent(provider)
    analysts = [a.value for a in select_analysts()]
    depth = select_research_depth()
    language = ask_output_language()
    trade_date = get_analysis_date()
    return BatchSettings(
        analysts=analysts,
        research_depth=depth,
        output_language=language,
        trade_date=trade_date,
        llm_provider=provider,
        deep_think_llm=deep,
        quick_think_llm=quick,
    )


def enqueue_watchlist(
    client: ApiClient, watchlist: list[dict], settings: BatchSettings
) -> tuple[dict[str, str], list[str]]:
    """Enqueue each ticker in order; return (run_id -> upper ticker, failed upper tickers)."""
    run_map: dict[str, str] = {}
    failed: list[str] = []
    for item in watchlist:
        ticker = item["ticker"]
        normalized = ticker.strip().upper()
        asset_type = detect_asset_type(ticker).value
        analysts = analysts_for_asset_type(settings.analysts, asset_type)
        try:
            resp = client.enqueue(
                ticker=ticker,
                name=item.get("name") or "",
                trade_date=settings.trade_date,
                asset_type=asset_type,
                analysts=analysts,
                research_depth=settings.research_depth,
                output_language=settings.output_language,
                llm_provider=settings.llm_provider,
                deep_think_llm=settings.deep_think_llm,
                quick_think_llm=settings.quick_think_llm,
            )
        except ApiError as exc:
            console.print(f"[red]入队失败 {normalized}: {exc}[/red]")
            failed.append(normalized)
            continue
        for run_id in resp.get("run_ids", []):
            run_map[run_id] = normalized
    return run_map, failed


def poll_until_done(
    client: ApiClient,
    state: BatchState,
    poll_interval: float = 1.5,
    sleep=time.sleep,
    live: Live | None = None,
) -> None:
    """Poll queue/history/status until every row is terminal."""
    while not state.all_done():
        try:
            state.apply_queue(client.get_queue())
            state.apply_history(client.get_history())
            if state.current_running_id:
                state.apply_status(client.get_status(state.current_running_id))
            else:
                state.apply_status(None)
        except ApiError:
            pass  # transient; keep last snapshot and retry next tick
        if live is not None:
            live.update(state.render())
        sleep(poll_interval)


def _print_summary(state: BatchState) -> None:
    console.print("\n[bold]批次汇总[/bold]")
    for row in state.rows:
        console.print(f"  {row.ticker}  {row.name}  ->  {row.status}  {row.decision or ''}")


def run_batch(api_url: str | None = None) -> None:
    client = ApiClient(api_url)
    try:
        watchlist = client.get_watchlist()
    except ApiError:
        console.print(
            "[red]无法连接 API 服务。[/red]请先启动：\n"
            "  ./dev.sh\n或\n"
            "  .venv/bin/python -m uvicorn api.main:app --port 8000"
        )
        raise typer.Exit(1) from None

    if not watchlist:
        console.print("[yellow]watchlist 为空。[/yellow]请先在 webUI 添加自选股。")
        raise typer.Exit(0)

    settings = collect_settings()
    run_map, failed = enqueue_watchlist(client, watchlist, settings)
    state = BatchState(watchlist)
    state.set_run_map(run_map)
    for ticker in failed:
        state.mark_error(ticker)

    try:
        with Live(state.render(), console=console, refresh_per_second=4) as live:
            poll_until_done(client, state, live=live)
            live.update(state.render())
    except KeyboardInterrupt:
        console.print("\n[yellow]已退出看板，队列仍在后台运行。[/yellow]")
        return
    _print_summary(state)
