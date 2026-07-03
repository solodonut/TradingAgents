#!/usr/bin/env python3
"""Generate a standalone HTML timeline view for TradingAgents run logs."""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def ms_label(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f} ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rem = divmod(seconds, 60)
    return f"{int(minutes)}m {rem:.1f}s"


def compact(value: Any, limit: int = 260) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def event_label(event: dict[str, Any]) -> str:
    event_type = event.get("event_type", "")
    if event_type in {"node_enter", "node_exit"}:
        return str(event.get("node", event_type))
    if event_type == "llm_call":
        return str(event.get("model", "llm_call"))
    if event_type == "vendor_call":
        method = event.get("method", "vendor_call")
        vendor = event.get("vendor", "")
        return f"{method} / {vendor}" if vendor else str(method)
    if event_type in {"tool_call", "memory_op", "checkpoint_op"}:
        return str(event.get("name") or event.get("method") or event_type)
    return str(event_type)


def event_detail(event: dict[str, Any]) -> str:
    event_type = event.get("event_type", "")
    if event_type == "vendor_call":
        return compact(event.get("args"))
    if event_type == "llm_call":
        response = compact(event.get("response"), 180)
        tokens = event.get("tokens")
        token_text = compact(tokens, 80) if tokens else ""
        return " | ".join(part for part in [response, token_text] if part)
    if event_type in {"node_enter", "node_exit"}:
        return ""
    return compact({k: v for k, v in event.items() if k not in {"prompt", "response", "config"}})


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if "ts" not in event:
                continue
            event["_line"] = line_no
            events.append(event)
    return events


def build_payload(path: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        raise SystemExit(f"{path}: no events found")

    parsed = [(event, parse_ts(event["ts"])) for event in events]
    run_start = min(ts for _, ts in parsed)
    run_end = max(ts for _, ts in parsed)
    run_elapsed_ms = (run_end - run_start).total_seconds() * 1000

    rows: list[dict[str, Any]] = []
    totals = Counter()
    counts = Counter()
    by_node = defaultdict(float)

    for event, end_ts in parsed:
        event_type = event.get("event_type", "unknown")
        elapsed_ms = event.get("elapsed_ms")
        if isinstance(elapsed_ms, (int, float)):
            start_ts = end_ts - timedelta(milliseconds=float(elapsed_ms))
            duration_ms = max(float(elapsed_ms), 0.0)
        else:
            start_ts = end_ts
            duration_ms = 0.0

        start_ms = (start_ts - run_start).total_seconds() * 1000
        end_ms = (end_ts - run_start).total_seconds() * 1000
        label = event_label(event)
        node = event.get("node") or label
        ok = event.get("ok")

        if duration_ms:
            totals[event_type] += duration_ms
            counts[event_type] += 1
            if event_type == "node_exit":
                by_node[str(node)] += duration_ms

        rows.append(
            {
                "seq": event.get("seq"),
                "line": event.get("_line"),
                "type": event_type,
                "label": label,
                "node": node,
                "model": event.get("model", ""),
                "vendor": event.get("vendor", ""),
                "method": event.get("method", ""),
                "ok": ok,
                "fallback": event.get("fallback", False),
                "startMs": round(start_ms, 3),
                "endMs": round(end_ms, 3),
                "durationMs": round(duration_ms, 3),
                "durationLabel": ms_label(duration_ms),
                "ts": event["ts"],
                "detail": event_detail(event),
            }
        )

    slow = sorted((row for row in rows if row["durationMs"] > 0), key=lambda r: r["durationMs"], reverse=True)
    first = events[0]
    return {
        "source": str(path),
        "title": path.name,
        "ticker": first.get("ticker", ""),
        "runId": first.get("run_id", ""),
        "start": run_start.isoformat(),
        "end": run_end.isoformat(),
        "elapsedMs": round(run_elapsed_ms, 3),
        "elapsedLabel": ms_label(run_elapsed_ms),
        "eventCount": len(events),
        "types": dict(Counter(event.get("event_type", "unknown") for event in events)),
        "totals": {key: round(value, 3) for key, value in totals.items()},
        "counts": dict(counts),
        "nodeTotals": dict(sorted(by_node.items(), key=lambda item: item[1], reverse=True)),
        "rows": rows,
        "slow": slow[:20],
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --ink: #1e211c;
      --muted: #686c63;
      --line: #d9d9d0;
      --panel: #ffffff;
      --node: #3f6b57;
      --llm: #7759a6;
      --vendor: #b46d2b;
      --other: #687483;
      --bad: #b9443f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 28px 32px 18px;
      border-bottom: 1px solid var(--line);
      background: #fbfbf8;
    }}
    h1 {{ margin: 0 0 8px; font-size: 24px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 17px; }}
    .meta {{ color: var(--muted); word-break: break-all; }}
    main {{ padding: 22px 32px 40px; max-width: 1480px; margin: 0 auto; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(5, minmax(150px, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }}
    .stat, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .stat {{ padding: 14px 16px; }}
    .stat b {{ display: block; font-size: 22px; margin-top: 4px; }}
    .stat span {{ color: var(--muted); }}
    section {{ padding: 16px; margin-top: 16px; }}
    .controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-bottom: 14px;
    }}
    input, select {{
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      background: white;
      color: var(--ink);
    }}
    label {{ display: inline-flex; gap: 6px; align-items: center; color: var(--muted); }}
    .timeline {{
      position: relative;
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background:
        linear-gradient(to right, rgba(0,0,0,.04) 1px, transparent 1px) 0 0 / 10% 100%,
        #fff;
    }}
    .ticks {{
      position: sticky;
      top: 0;
      z-index: 2;
      height: 32px;
      min-width: 1100px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.94);
    }}
    .tick {{
      position: absolute;
      top: 7px;
      transform: translateX(-50%);
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }}
    .lane {{
      position: relative;
      min-width: 1100px;
      height: 30px;
      border-bottom: 1px solid #eeeeea;
    }}
    .lane:hover {{ background: #fafaf7; }}
    .bar {{
      position: absolute;
      top: 6px;
      height: 18px;
      min-width: 2px;
      border-radius: 4px;
      color: white;
      padding: 1px 6px;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      font-size: 12px;
      cursor: default;
    }}
    .bar.node_exit {{ background: var(--node); }}
    .bar.llm_call {{ background: var(--llm); }}
    .bar.vendor_call {{ background: var(--vendor); }}
    .bar.other {{ background: var(--other); }}
    .bar.bad {{ background: var(--bad); }}
    .legend {{ display: flex; gap: 14px; flex-wrap: wrap; color: var(--muted); }}
    .legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      padding: 8px 9px;
      border-bottom: 1px solid #ecece6;
      text-align: left;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; background: #fbfbf8; position: sticky; top: 0; }}
    tbody tr:hover {{ background: #fafaf7; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .pill {{
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 1px 7px;
      color: var(--muted);
      background: #fff;
      white-space: nowrap;
    }}
    .table-wrap {{ max-height: 520px; overflow: auto; border: 1px solid var(--line); border-radius: 8px; }}
    @media (max-width: 900px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>TradingAgents 运行耗时视图</h1>
    <div class="meta" id="meta"></div>
  </header>
  <main>
    <div class="stats" id="stats"></div>
    <section>
      <h2>时间序列</h2>
      <div class="controls">
        <label>类型
          <select id="typeFilter">
            <option value="">全部耗时事件</option>
            <option value="node_exit">节点</option>
            <option value="llm_call">LLM 请求</option>
            <option value="vendor_call">数据源请求</option>
          </select>
        </label>
        <label>最小耗时(ms)<input id="minMs" type="number" min="0" step="100" value="0"></label>
        <label>搜索<input id="search" placeholder="node / model / vendor / method"></label>
      </div>
      <div class="legend">
        <span><i style="background: var(--node)"></i>节点</span>
        <span><i style="background: var(--llm)"></i>LLM</span>
        <span><i style="background: var(--vendor)"></i>数据源</span>
        <span><i style="background: var(--bad)"></i>失败</span>
      </div>
      <div class="timeline" id="timeline"></div>
    </section>
    <section>
      <h2>慢操作排行</h2>
      <div class="table-wrap"><table id="slowTable"></table></div>
    </section>
    <section>
      <h2>节点总耗时</h2>
      <div class="table-wrap"><table id="nodeTable"></table></div>
    </section>
    <section>
      <h2>事件明细</h2>
      <div class="table-wrap"><table id="eventTable"></table></div>
    </section>
  </main>
  <script id="payload" type="application/json">{payload}</script>
  <script>
    const data = JSON.parse(document.getElementById('payload').textContent);
    const rows = data.rows.filter(r => r.durationMs > 0);
    const timeline = document.getElementById('timeline');
    const typeFilter = document.getElementById('typeFilter');
    const minMs = document.getElementById('minMs');
    const search = document.getElementById('search');

    function fmt(ms) {{
      if (ms < 1000) return Math.round(ms) + ' ms';
      const s = ms / 1000;
      if (s < 60) return s.toFixed(1) + ' s';
      return Math.floor(s / 60) + 'm ' + (s % 60).toFixed(1) + 's';
    }}
    function esc(value) {{
      return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
    }}
    function matches(row) {{
      const type = typeFilter.value;
      const min = Number(minMs.value || 0);
      const q = search.value.trim().toLowerCase();
      if (type && row.type !== type) return false;
      if (row.durationMs < min) return false;
      if (!q) return true;
      return [row.label, row.node, row.model, row.vendor, row.method, row.detail].join(' ').toLowerCase().includes(q);
    }}
    function renderStats() {{
      const llm = data.totals.llm_call || 0;
      const vendor = data.totals.vendor_call || 0;
      const node = data.totals.node_exit || 0;
      const stats = [
        ['总运行时间', data.elapsedLabel],
        ['事件数', data.eventCount],
        ['LLM 总耗时', fmt(llm)],
        ['数据源总耗时', fmt(vendor)],
        ['节点总耗时', fmt(node)]
      ];
      document.getElementById('stats').innerHTML = stats.map(([k,v]) => `<div class="stat"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('');
      document.getElementById('meta').innerHTML = `${esc(data.title)} · ticker ${esc(data.ticker || '-')} · ${esc(data.start)} → ${esc(data.end)}<br>${esc(data.source)}`;
    }}
    function renderTimeline() {{
      const filtered = rows.filter(matches);
      const maxEnd = Math.max(...rows.map(r => r.endMs), data.elapsedMs);
      const ticks = Array.from({{length: 11}}, (_, i) => {{
        const left = i * 10;
        return `<span class="tick" style="left:${left}%">${fmt(maxEnd * i / 10)}</span>`;
      }}).join('');
      const lanes = filtered.map(row => {{
        const left = Math.max(0, row.startMs / maxEnd * 100);
        const width = Math.max(0.15, row.durationMs / maxEnd * 100);
        const cls = row.ok === false ? 'bad' : (['node_exit','llm_call','vendor_call'].includes(row.type) ? row.type : 'other');
        const tip = `#${row.seq} ${row.type} ${row.label} ${row.durationLabel}\\n${row.ts}\\n${row.detail || ''}`;
        return `<div class="lane"><div class="bar ${cls}" style="left:${left}%;width:${width}%" title="${esc(tip)}">#${esc(row.seq)} ${esc(row.label)} · ${esc(row.durationLabel)}</div></div>`;
      }}).join('');
      timeline.innerHTML = `<div class="ticks">${ticks}</div>${lanes || '<div class="lane"><span class="tick" style="left:50%">无匹配事件</span></div>'}`;
    }}
    function renderTable(id, tableRows, columns) {{
      const head = '<thead><tr>' + columns.map(c => `<th class="${c.num ? 'num' : ''}">${esc(c.label)}</th>`).join('') + '</tr></thead>';
      const body = '<tbody>' + tableRows.map(row => '<tr>' + columns.map(c => {{
        const value = c.render ? c.render(row) : row[c.key];
        return `<td class="${c.num ? 'num' : ''}">${value}</td>`;
      }}).join('') + '</tr>').join('') + '</tbody>';
      document.getElementById(id).innerHTML = head + body;
    }}
    function renderTables() {{
      const visible = rows.filter(matches);
      const columns = [
        {{label: '#', key: 'seq', num: true, render: r => esc(r.seq)}},
        {{label: '类型', render: r => `<span class="pill">${esc(r.type)}</span>`}},
        {{label: '名称', render: r => esc(r.label)}},
        {{label: '开始', num: true, render: r => fmt(r.startMs)}},
        {{label: '耗时', num: true, render: r => `<b>${esc(r.durationLabel)}</b>`}},
        {{label: '详情', render: r => esc(r.detail)}}
      ];
      renderTable('slowTable', [...visible].sort((a,b) => b.durationMs - a.durationMs).slice(0, 30), columns);
      renderTable('eventTable', visible, columns);
      const nodeRows = Object.entries(data.nodeTotals).map(([node, ms]) => ({{node, ms}}));
      renderTable('nodeTable', nodeRows, [
        {{label: '节点', render: r => esc(r.node)}},
        {{label: '总耗时', num: true, render: r => `<b>${fmt(r.ms)}</b>`}}
      ]);
    }}
    function render() {{
      renderTimeline();
      renderTables();
    }}
    [typeFilter, minMs, search].forEach(el => el.addEventListener('input', render));
    renderStats();
    render();
  </script>
</body>
</html>
"""


def write_html(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    template = HTML_TEMPLATE.replace("{{", "{").replace("}}", "}")
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    body = template.replace(
        "{title}", html.escape(f"Run Log Timeline - {payload['title']}")
    ).replace("{payload}", payload_json)
    output.write_text(body, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="Path to a TradingAgents JSONL run log")
    parser.add_argument("-o", "--output", type=Path, help="Output HTML path")
    args = parser.parse_args()

    log_path = args.log.expanduser().resolve()
    output = args.output.expanduser().resolve() if args.output else log_path.with_suffix(".html")
    events = load_events(log_path)
    payload = build_payload(log_path, events)
    write_html(payload, output)
    print(output)


if __name__ == "__main__":
    main()
