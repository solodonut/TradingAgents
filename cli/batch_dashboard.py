"""State machine + rich rendering for the batch analysis dashboard."""

from dataclasses import dataclass

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

STATUS_ICONS = {
    "pending": "⏳",
    "running": "▶",
    "completed": "✓",
    "error": "✗",
    "cancelled": "⊘",
}

# report section key -> Chinese label (keys mirror api/runner.py REPORT_SECTIONS)
SECTION_LABELS = {
    "market_report": "市场分析",
    "sentiment_report": "情绪分析",
    "news_report": "新闻分析",
    "fundamentals_report": "基本面分析",
    "investment_plan": "研究经理复盘",
    "trader_investment_plan": "交易员计划",
    "final_trade_decision": "组合经理决策",
    "validation_report": "报告校验",
}

_TERMINAL = ("completed", "error", "cancelled")


@dataclass
class TickerRow:
    ticker: str
    name: str
    run_id: str | None = None
    status: str = "pending"
    decision: str | None = None


class BatchState:
    def __init__(self, watchlist: list[dict]):
        self.rows: list[TickerRow] = [
            TickerRow(ticker=item["ticker"].strip().upper(), name=item.get("name") or "")
            for item in watchlist
        ]
        self._by_ticker: dict[str, TickerRow] = {r.ticker: r for r in self.rows}
        self._by_run: dict[str, TickerRow] = {}
        self.current_running_id: str | None = None
        self.current_detail: dict | None = None

    def set_run_map(self, run_map: dict[str, str]) -> None:
        for run_id, ticker in run_map.items():
            row = self._by_ticker.get(ticker)
            if row is not None:
                row.run_id = run_id
                self._by_run[run_id] = row

    def mark_error(self, ticker: str) -> None:
        row = self._by_ticker.get(ticker)
        if row is not None:
            row.status = "error"

    def apply_queue(self, queue: dict) -> None:
        running = queue.get("running")
        pending_ids = {p["run_id"] for p in queue.get("pending", [])}
        self.current_running_id = running["run_id"] if running else None
        for row in self.rows:
            if row.run_id is None:
                continue
            if running and row.run_id == running["run_id"]:
                row.status = "running"
            elif row.run_id in pending_ids:
                row.status = "pending"
            # else: terminal — leave for apply_history to confirm

    def apply_history(self, history: list[dict]) -> None:
        for entry in history:
            row = self._by_run.get(entry["run_id"])
            if row is None:
                continue
            row.status = entry["status"]
            if entry.get("decision"):
                row.decision = entry["decision"]

    def apply_status(self, status: dict | None) -> None:
        self.current_detail = status

    def all_done(self) -> bool:
        return all(row.status in _TERMINAL for row in self.rows)

    def _detail_panel(self) -> Panel:
        detail = self.current_detail
        if not self.current_running_id or not detail:
            return Panel(Text("暂无正在运行的分析", style="dim"), title="当前运行")
        row = self._by_run.get(self.current_running_id)
        header = f"{row.ticker} ({row.name})" if row and row.name else (row.ticker if row else "")
        section = detail.get("last_report_section")
        section_label = SECTION_LABELS.get(section, section) if section else "尚未产出章节"
        lines = [
            Text(header, style="bold"),
            Text(f"当前章节: {section_label}"),
            Text(
                f"LLM: {'活动中' if detail.get('llm_active') else '空闲'}"
                f" · 并发 {detail.get('active_llm_calls', 0)}"
                f" · 模型 {detail.get('last_llm_model') or '-'}"
            ),
        ]
        if detail.get("last_llm_error"):
            lines.append(Text(f"错误: {detail['last_llm_error']}", style="red"))
        return Panel(Group(*lines), title="当前运行")

    def render(self):
        table = Table(title="批量分析进度", expand=True)
        table.add_column("标的")
        table.add_column("状态", justify="center")
        table.add_column("决策", justify="center")
        for row in self.rows:
            label = f"{row.ticker}  {row.name}".strip()
            icon = STATUS_ICONS.get(row.status, "?")
            table.add_row(label, f"{icon} {row.status}", row.decision or "-")
        return Group(table, self._detail_panel())
