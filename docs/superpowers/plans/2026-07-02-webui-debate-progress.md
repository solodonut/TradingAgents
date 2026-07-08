# WebUI 辩论进度可视化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 WebUI 在多空辩论与三方风险辩论期间实时显示「第几轮 · 谁在发言 · 正文」，并让历史 run 能回放同样的辩论过程。

**Architecture:** 后端 `api/runner.py` 在既有 LangGraph 流循环里新增纯函数 `debate_events`，通过对比辩论 state 的 `count` 单调增长发出新的 `debate_round` SSE 事件；前端订阅该事件，直播时把每位发言者渲染成消息气泡并在 Agent Matrix 里显示轮次明细；历史回放则从已落库的 `result.*_debate_state.history` 解析出发言序列渲染。

**Tech Stack:** Python 3.10+ / FastAPI / LangGraph（后端）；Next.js 16 + React 19 + TypeScript（前端）；pytest（后端单测）、`node --test`（前端 lib 单测）。

## Global Constraints

- 跑任何 Python/pytest 命令一律用 `.venv/bin/python`（系统 python 可能是 3.9，会崩）。
- 所有用户可见文案用中文。
- 动 `webui/` 前先看 `webui/node_modules/next/dist/docs/`（Next.js 16 与训练数据有破坏性差异）。
- **不改**数据库 schema、`api/store.py` 的 `complete_run`/`update_partial_result`，也**不改**任何 LangGraph 节点或 agent 代码（researcher / risk debator 不动）。
- 收尾前手动跑 `.venv/bin/python -m ruff check .` 与 `.venv/bin/python -m pytest -m "not integration"`，前端跑 `cd webui && npm test`、`npx tsc --noEmit`、`npm run lint`。
- 提交遵循 Conventional Commits，并同步维护 `CHANGELOG.md`（Keep a Changelog）。只有用户明确要求才提交/推送——本计划各任务的 commit 步骤在执行者获授权后进行。

## 关键事实（已核实，实现时依赖）

- LangGraph 以 `stream_mode="values"` 流式：**每个 chunk 是完整累积 state**，`count` 单调递增，且相邻两次观测最多相差 1（未触及辩论 state 的 chunk 不改变 `count`）。因此「`count > 上次记录`」即代表恰好新增一位发言者，无需回填。
- 多空 `investment_debate_state`：`current_response` 形如 `"Bull Analyst: ..."` / `"Bear Analyst: ..."`，顺序 Bull(奇数 count)→Bear(偶数 count) 交替，`count` 每人 +1，总人次 = `2 × max_debate_rounds`。
- 风险 `risk_debate_state`：顺序固定 Aggressive→Conservative→Neutral，正文分别在 `current_aggressive_response` / `current_conservative_response` / `current_neutral_response`（均带 `"Xxx Analyst: "` 前缀），`count` 每人 +1，总人次 = `3 × max_risk_discuss_rounds`。
- 轮次：多空 `round = (count + 1) // 2`；风险 `round = (count + 2) // 3`。
- `history` 累积格式为 `history + "\n" + argument`，每段 argument 以 `"<Speaker> Analyst:"` 开头 → 历史回放按该前缀切分。
- 总轮次来自 `graph.config["max_debate_rounds"]` / `["max_risk_discuss_rounds"]`；测试用的 `_FakeGraph` 没有 `config` 属性，故 runner 用 `getattr(graph, "config", None) or {}` 兜底为 1。
- 完成 run 的 `result` 里包含完整 `final_state`（含 `investment_debate_state`/`risk_debate_state` 嵌套 dict），已由 `store.complete_run` 用 `_dumps` 序列化、`get_run` 用 `json.loads` 还原。

## File Structure

| 文件 | 职责 | 改动类型 |
|------|------|---------|
| `api/runner.py` | 新增辩论发言人常量、`_strip_speaker_prefix`、`debate_events`、`_rounds_config`；在 `AnalysisRunner.run()` 接入 | Modify |
| `tests/webui/test_runner.py` | `debate_events` 单测 + runner 集成断言 | Modify |
| `webui/lib/types.ts` | `SSEEvent` 增加 `debate_round`；`RunResult.result` 放宽为 `Record<string, unknown> \| null` | Modify |
| `webui/lib/sse.ts` | 监听数组增加 `"debate_round"` | Modify |
| `webui/lib/debate.ts` | 新增：从 `history` 字符串解析发言序列的纯函数 `parseDebateHistory` | Create |
| `webui/lib/debate.test.ts` | `parseDebateHistory` 单测 | Create |
| `webui/app/page.tsx` | `followRun` 处理 `debate_round`；新增 `debateDetails` state；重置逻辑；把 `details` 传给 `AgentProgress` | Modify |
| `webui/components/AgentProgress.tsx` | 新增可选 `details` 入参，辩论行 working 时显示轮次明细 | Modify |
| `webui/components/RunDetail.tsx` | 用 `parseDebateHistory` 渲染历史辩论发言（多空插在研究经理前、风险插在最终决策前） | Modify |

---

### Task 1: 后端 `debate_events` 纯函数

**Files:**
- Modify: `api/runner.py`（在 `REPORT_SECTION_KEYS` 定义之后、`class AnalysisRunner` 之前新增）
- Test: `tests/webui/test_runner.py`

**Interfaces:**
- Consumes: 无（纯函数，输入普通 dict）。
- Produces:
  - `debate_events(chunk: dict, tracker: dict, rounds_cfg: dict) -> list[dict]` —
    检测 `chunk` 里 `investment_debate_state`/`risk_debate_state` 的 `count` 是否超过 `tracker` 记录；每超过一次追加一个 `{"event": "debate_round", "data": {...}}`，并把新 count 写回 `tracker["invest_count"]`/`tracker["risk_count"]`。`rounds_cfg` 形如 `{"invest_total": int, "risk_total": int}`。
  - `_rounds_config(graph) -> dict` — 从 `graph.config` 读两个 `max_*_rounds`，缺省 1，返回上面的 `rounds_cfg`。
  - `debate_round` 事件 `data` 字段：`team`(`"invest"`|`"risk"`)、`round`(int)、`total`(int)、`speaker`(str)、`speaker_label`(中文 str)、`content`(去前缀 str)。

- [ ] **Step 1: 写失败测试**

在 `tests/webui/test_runner.py` 顶部 import 追加 `debate_events`，并在文件末尾 `_drain` 之前插入以下测试：

```python
def test_invest_first_turn_is_bull_round_1():
    tracker: dict = {}
    events = debate_events(
        {"investment_debate_state": {"count": 1, "current_response": "Bull Analyst: buy it"}},
        tracker,
        {"invest_total": 2, "risk_total": 1},
    )
    assert len(events) == 1
    assert events[0]["event"] == "debate_round"
    assert events[0]["data"] == {
        "team": "invest",
        "round": 1,
        "total": 2,
        "speaker": "bull",
        "speaker_label": "多方",
        "content": "buy it",
    }
    assert tracker["invest_count"] == 1


def test_invest_second_turn_is_bear_same_round():
    tracker = {"invest_count": 1}
    events = debate_events(
        {"investment_debate_state": {"count": 2, "current_response": "Bear Analyst: no way"}},
        tracker,
        {"invest_total": 2, "risk_total": 1},
    )
    d = events[0]["data"]
    assert d["speaker"] == "bear" and d["speaker_label"] == "空方"
    assert d["round"] == 1 and d["content"] == "no way"


def test_invest_third_turn_is_round_2_bull():
    tracker = {"invest_count": 2}
    events = debate_events(
        {"investment_debate_state": {"count": 3, "current_response": "Bull Analyst: still buy"}},
        tracker,
        {"invest_total": 2, "risk_total": 1},
    )
    assert events[0]["data"]["round"] == 2
    assert events[0]["data"]["speaker"] == "bull"


def test_no_event_when_count_unchanged():
    tracker = {"invest_count": 2}
    events = debate_events(
        {"investment_debate_state": {"count": 2, "current_response": "Bear Analyst: no"}},
        tracker,
        {"invest_total": 2, "risk_total": 1},
    )
    assert events == []


def test_risk_speaker_cycle_and_round_math():
    tracker: dict = {}
    cfg = {"invest_total": 1, "risk_total": 2}
    e1 = debate_events(
        {"risk_debate_state": {
            "count": 1, "latest_speaker": "Aggressive",
            "current_aggressive_response": "Aggressive Analyst: go big"}},
        tracker, cfg)
    assert e1[0]["data"] == {
        "team": "risk", "round": 1, "total": 2,
        "speaker": "aggressive", "speaker_label": "激进", "content": "go big"}
    e2 = debate_events(
        {"risk_debate_state": {
            "count": 2, "latest_speaker": "Conservative",
            "current_conservative_response": "Conservative Analyst: careful"}},
        tracker, cfg)
    assert e2[0]["data"]["speaker"] == "conservative" and e2[0]["data"]["round"] == 1
    e3 = debate_events(
        {"risk_debate_state": {
            "count": 3, "latest_speaker": "Neutral",
            "current_neutral_response": "Neutral Analyst: middle"}},
        tracker, cfg)
    assert e3[0]["data"]["speaker"] == "neutral" and e3[0]["data"]["round"] == 1
    e4 = debate_events(
        {"risk_debate_state": {
            "count": 4, "latest_speaker": "Aggressive",
            "current_aggressive_response": "Aggressive Analyst: again"}},
        tracker, cfg)
    assert e4[0]["data"]["round"] == 2 and e4[0]["data"]["speaker"] == "aggressive"


def test_debate_events_ignores_chunk_without_debate_state():
    assert debate_events({"market_report": "x"}, {}, {"invest_total": 1, "risk_total": 1}) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_runner.py -k "debate or invest or risk" -v`
Expected: FAIL —`ImportError: cannot import name 'debate_events'`。

- [ ] **Step 3: 实现 `debate_events` 及辅助**

在 `api/runner.py` 中 `REPORT_SECTION_KEYS = frozenset(REPORT_SECTIONS)` 这一行之后插入：

```python
# Debate progress ---------------------------------------------------------
# speaker key -> (prose prefix, Chinese label)
INVEST_SPEAKERS: dict[str, tuple[str, str]] = {
    "bull": ("Bull Analyst:", "多方"),
    "bear": ("Bear Analyst:", "空方"),
}
RISK_SPEAKERS: dict[str, tuple[str, str]] = {
    "aggressive": ("Aggressive Analyst:", "激进"),
    "conservative": ("Conservative Analyst:", "保守"),
    "neutral": ("Neutral Analyst:", "中立"),
}
RISK_SPEAKER_ORDER: tuple[str, ...] = ("aggressive", "conservative", "neutral")
_SPEAKER_PREFIXES: tuple[str, ...] = tuple(
    prefix for prefix, _ in (*INVEST_SPEAKERS.values(), *RISK_SPEAKERS.values())
)


def _strip_speaker_prefix(text: str) -> str:
    """Drop a leading 'Xxx Analyst:' label from a debate argument."""
    stripped = text.lstrip()
    for prefix in _SPEAKER_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return stripped


def _round_event(*, team, round_no, total, speaker, label, content) -> dict:
    return {
        "event": "debate_round",
        "data": {
            "team": team,
            "round": round_no,
            "total": total,
            "speaker": speaker,
            "speaker_label": label,
            "content": _strip_speaker_prefix(content or ""),
        },
    }


def debate_events(chunk: dict, tracker: dict, rounds_cfg: dict) -> list[dict]:
    """Emit `debate_round` events when a debate state's `count` advances.

    `chunk` is a full accumulated state (stream_mode='values'), so `count` is
    monotonic and grows by exactly one per debate turn. `tracker` remembers the
    last count already emitted per team; `rounds_cfg` carries the totals.
    """
    events: list[dict] = []

    invest = chunk.get("investment_debate_state")
    if isinstance(invest, dict):
        count = invest.get("count") or 0
        if count > tracker.get("invest_count", 0):
            tracker["invest_count"] = count
            speaker = "bull" if count % 2 == 1 else "bear"
            _, label = INVEST_SPEAKERS[speaker]
            events.append(
                _round_event(
                    team="invest",
                    round_no=(count + 1) // 2,
                    total=rounds_cfg.get("invest_total", 1),
                    speaker=speaker,
                    label=label,
                    content=invest.get("current_response", ""),
                )
            )

    risk = chunk.get("risk_debate_state")
    if isinstance(risk, dict):
        count = risk.get("count") or 0
        if count > tracker.get("risk_count", 0):
            tracker["risk_count"] = count
            speaker = RISK_SPEAKER_ORDER[(count - 1) % 3]
            _, label = RISK_SPEAKERS[speaker]
            events.append(
                _round_event(
                    team="risk",
                    round_no=(count + 2) // 3,
                    total=rounds_cfg.get("risk_total", 1),
                    speaker=speaker,
                    label=label,
                    content=risk.get(f"current_{speaker}_response", ""),
                )
            )

    return events


def _rounds_config(graph) -> dict:
    """Read debate round totals from graph.config, defaulting to 1."""
    config = getattr(graph, "config", None) or {}
    return {
        "invest_total": int(config.get("max_debate_rounds", 1) or 1),
        "risk_total": int(config.get("max_risk_discuss_rounds", 1) or 1),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_runner.py -k "debate or invest or risk" -v`
Expected: PASS（6 个新测试全绿）。

- [ ] **Step 5: 提交**

```bash
git add api/runner.py tests/webui/test_runner.py
git commit -m "feat(webui): add debate_events to translate debate state into SSE round events"
```

---

### Task 2: 把 `debate_events` 接入 `AnalysisRunner.run()`

**Files:**
- Modify: `api/runner.py`（`AnalysisRunner.run` 方法）
- Test: `tests/webui/test_runner.py`

**Interfaces:**
- Consumes: `debate_events`、`_rounds_config`（Task 1）。
- Produces: 运行时事件队列中，在报告事件之外新增 `debate_round` 事件；`run()` 行为其余不变（报告落库、done/error/cancelled 不受影响）。

- [ ] **Step 1: 写失败测试**

在 `tests/webui/test_runner.py` 末尾 `_drain` 之前追加：

```python
def test_runner_emits_debate_round_events(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})

    fake = _FakeGraph(
        chunks=[
            {"investment_debate_state": {"count": 1, "current_response": "Bull Analyst: up"}},
            {"investment_debate_state": {"count": 2, "current_response": "Bear Analyst: down"}},
            {"final_trade_decision": "**Rating**: Buy"},
        ],
        final_state={"final_trade_decision": "**Rating**: Buy"},
        decision="Buy",
    )
    fake.config = {"max_debate_rounds": 1, "max_risk_discuss_rounds": 1}
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q)
    runner.run(
        run_id="r1",
        graph=fake,
        init_state={},
        decision="Buy",
        final_state={"final_trade_decision": "**Rating**: Buy"},
    )

    events = _drain(q)
    rounds = [e for e in events if e["event"] == "debate_round"]
    assert len(rounds) == 2
    assert rounds[0]["data"]["speaker"] == "bull" and rounds[0]["data"]["total"] == 1
    assert rounds[1]["data"]["speaker"] == "bear"
    # 报告事件不受影响
    assert any(e["event"] == "done" for e in events)


def test_runner_without_config_still_streams_debate_rounds(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    # _FakeGraph 没有 config 属性 -> total 回退为 1，不报错。
    fake = _FakeGraph(
        chunks=[{"investment_debate_state": {"count": 1, "current_response": "Bull Analyst: up"}}],
        final_state=None,
        decision=None,
    )
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q)
    runner.run(run_id="r1", graph=fake, init_state={}, decision=None, final_state=None)

    rounds = [e for e in _drain(q) if e["event"] == "debate_round"]
    assert len(rounds) == 1 and rounds[0]["data"]["total"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_runner.py -k "debate_round or without_config" -v`
Expected: FAIL —`assert len(rounds) == 2` 失败（当前 runner 不发 `debate_round`，`rounds` 为空）。

- [ ] **Step 3: 在 `run()` 里接入**

在 `AnalysisRunner.run` 顶部，把开头几行改为初始化 tracker 与 rounds 配置。找到：

```python
    def run(self, run_id, graph, init_state, decision, final_state) -> None:
        seen: set[str] = set()
        accumulated: dict = {}
```

改为：

```python
    def run(self, run_id, graph, init_state, decision, final_state) -> None:
        seen: set[str] = set()
        debate_tracker: dict = {}
        rounds_cfg = _rounds_config(graph)
        accumulated: dict = {}
```

然后找到流循环里发送报告事件的这一段：

```python
                for event in chunk_to_events(chunk, seen):
                    self._q.put(event)
                if self._is_cancelled():
                    self._emit_cancelled(run_id)
                    return
```

改为（在报告事件之后、取消检查之前追加辩论事件）：

```python
                for event in chunk_to_events(chunk, seen):
                    self._q.put(event)
                if isinstance(chunk, dict):
                    for event in debate_events(chunk, debate_tracker, rounds_cfg):
                        self._q.put(event)
                if self._is_cancelled():
                    self._emit_cancelled(run_id)
                    return
```

- [ ] **Step 4: 跑测试确认通过（含既有回归）**

Run: `.venv/bin/python -m pytest tests/webui/test_runner.py -v`
Expected: PASS（新旧测试全绿，既有 done/error/cancelled/partial 测试不受影响）。

- [ ] **Step 5: 提交**

```bash
git add api/runner.py tests/webui/test_runner.py
git commit -m "feat(webui): stream debate_round SSE events from AnalysisRunner"
```

---

### Task 3: 前端 SSE 类型与订阅接入 `debate_round`

**Files:**
- Modify: `webui/lib/types.ts`
- Modify: `webui/lib/sse.ts`

**Interfaces:**
- Consumes: 后端 `debate_round` 事件（Task 2）。
- Produces:
  - `SSEEvent` 联合类型新增一支 `{ event: "debate_round"; data: { team: "invest" | "risk"; round: number; total: number; speaker: string; speaker_label: string; content: string } }`。
  - `RunResult.result` 放宽为 `Record<string, unknown> | null`（辩论 state 是嵌套对象，非字符串）。
  - `subscribe()` 现在也监听 `"debate_round"`。

- [ ] **Step 1: 扩展 `SSEEvent` 与 `RunResult.result` 类型**

在 `webui/lib/types.ts` 中，找到 `SSEEvent` 定义（以 `export type SSEEvent =` 开头），在 `cancelled` 那一支之后、分号之前追加新的一支。将：

```ts
  | { event: "cancelled"; data: { run_id: string; message: string } };
```

改为：

```ts
  | { event: "cancelled"; data: { run_id: string; message: string } }
  | {
      event: "debate_round";
      data: {
        team: "invest" | "risk";
        round: number;
        total: number;
        speaker: string;
        speaker_label: string;
        content: string;
      };
    };
```

同一文件中找到 `RunResult` 接口里的：

```ts
  result: Record<string, string> | null;
```

改为（辩论 state 为嵌套对象，需放宽；已有 `as string` 读法仍成立）：

```ts
  result: Record<string, unknown> | null;
```

- [ ] **Step 2: 订阅列表加入 `debate_round`**

在 `webui/lib/sse.ts` 中找到：

```ts
  (
    ["agent_status", "message", "report_section", "stats", "done", "error", "cancelled"] as const
  ).forEach((t) => es.addEventListener(t, handler(t)));
```

改为：

```ts
  (
    [
      "agent_status",
      "message",
      "report_section",
      "stats",
      "done",
      "error",
      "cancelled",
      "debate_round",
    ] as const
  ).forEach((t) => es.addEventListener(t, handler(t)));
```

- [ ] **Step 3: 类型检查通过**

Run: `cd webui && npx tsc --noEmit`
Expected: 无报错（放宽 `result` 类型后，`page.tsx`/`RunDetail.tsx` 现有 `as string` 读法仍编译通过）。

- [ ] **Step 4: 提交**

```bash
git add webui/lib/types.ts webui/lib/sse.ts
git commit -m "feat(webui): register debate_round SSE event on the frontend"
```

---

### Task 4: 前端直播——消息气泡 + Agent Matrix 轮次明细

**Files:**
- Modify: `webui/components/AgentProgress.tsx`
- Modify: `webui/app/page.tsx`

**Interfaces:**
- Consumes: `SSEEvent`（Task 3）里的 `debate_round`。
- Produces:
  - `AgentProgress` 新增可选 prop `details?: Record<string, string>`；某行 `working` 且 `details[id]` 存在时，第二行显示明细而非 `id`。
  - `page.tsx` 新增 `debateDetails` state（`Record<string, string>`），`followRun` 处理 `debate_round`：追加消息气泡、把对应行标为 working、写入明细；`resetRunView` 清空该 state；`AgentProgress` 传入 `details={debateDetails}`。

- [ ] **Step 1: 扩展 `AgentProgress` 支持 `details`**

先按 Global Constraints 阅读 `webui/node_modules/next/dist/docs/` 里 App Router / Client Components 相关章节（本组件是 `"use client"`）。

在 `webui/components/AgentProgress.tsx` 中，把组件签名与第二行渲染改为支持 `details`。将：

```tsx
export function AgentProgress({ statuses }: { statuses: Record<string, string> }) {
```

改为：

```tsx
export function AgentProgress({
  statuses,
  details,
}: {
  statuses: Record<string, string>;
  details?: Record<string, string>;
}) {
```

再把渲染第二行的这一段：

```tsx
                <div className="truncate text-[0.65rem] uppercase tracking-[0.14em] text-muted-foreground">
                  {a.id}
                </div>
```

改为（working 且有明细时显示明细，否则仍显示 id）：

```tsx
                <div className="truncate text-[0.65rem] uppercase tracking-[0.14em] text-muted-foreground">
                  {working && details?.[a.id] ? details[a.id] : a.id}
                </div>
```

- [ ] **Step 2: `page.tsx` 新增 `debateDetails` state 并在重置时清空**

在 `webui/app/page.tsx` 中，找到 `messages` state 声明：

```tsx
  const [messages, setMessages] = useState<{ agent: string; content: string }[]>([]);
```

其后新增一行：

```tsx
  const [debateDetails, setDebateDetails] = useState<Record<string, string>>({});
```

找到 `resetRunView` 里的：

```tsx
    setMessages([]);
    setDecision(null);
```

改为：

```tsx
    setMessages([]);
    setDebateDetails({});
    setDecision(null);
```

- [ ] **Step 3: `followRun` 处理 `debate_round` 事件**

在 `webui/app/page.tsx` 的 `followRun` 事件回调里，找到 `cancelled` 分支：

```tsx
        else if (e.event === "cancelled") setError("分析已停止");
```

在其后追加 `debate_round` 分支：

```tsx
        else if (e.event === "debate_round") {
          const id = e.data.team === "invest" ? "debate" : "risk_debate";
          const teamLabel = e.data.team === "invest" ? "多空辩论" : "风险辩论";
          const detail = `第 ${e.data.round}/${e.data.total} 轮 · ${e.data.speaker_label}`;
          setMessages((m) => [...m, { agent: `${teamLabel} · ${detail}`, content: e.data.content }]);
          setStatuses((s) => (s[id] === "done" ? s : { ...s, [id]: "working" }));
          setDebateDetails((d) => ({ ...d, [id]: detail }));
        }
```

- [ ] **Step 4: 把 `details` 传给 `AgentProgress`**

在 `webui/app/page.tsx` 找到侧栏渲染：

```tsx
            <AgentProgress statuses={sidebarStatuses} />
```

改为：

```tsx
            <AgentProgress statuses={sidebarStatuses} details={debateDetails} />
```

- [ ] **Step 5: 类型检查与 lint**

Run: `cd webui && npx tsc --noEmit && npm run lint`
Expected: 均无报错。

- [ ] **Step 6: 手动验证直播（需要真实 run，可选但推荐）**

启动后端与前端（`./dev.sh`，或分别 `.venv/bin/python -m uvicorn api.main:app --reload --port 8000` 与 `cd webui && npm run dev`），发起一个 `research_depth >= 3`（多轮）的分析：
- 进入多空辩论时，消息区应逐条出现「多空辩论 · 第 1/2 轮 · 多方」等气泡，正文可读；
- Agent Matrix 的「多空辩论 / 风险辩论」行在 WORKING 时第二行显示「第 X/N 轮 · 空方」。

- [ ] **Step 7: 提交**

```bash
git add webui/app/page.tsx webui/components/AgentProgress.tsx
git commit -m "feat(webui): stream debate turns as bubbles and show round detail in agent matrix"
```

---

### Task 5: 历史回放——解析并渲染已落库的辩论历史

**Files:**
- Create: `webui/lib/debate.ts`
- Create: `webui/lib/debate.test.ts`
- Modify: `webui/components/RunDetail.tsx`

**Interfaces:**
- Consumes: `RunResult.result`（Task 3 放宽后的 `Record<string, unknown>`）里的 `investment_debate_state.history` / `risk_debate_state.history`。
- Produces:
  - `webui/lib/debate.ts` 导出：
    - `type DebateTurn = { round: number; speakerLabel: string; content: string }`
    - `parseDebateHistory(history: unknown, groupSize: number, labels: Record<string, string>): DebateTurn[]`
    - `INVEST_LABELS`、`RISK_LABELS` 常量。
  - `RunDetail` 在「研究经理(investment_plan)」气泡前渲染多空发言、在最终决策前渲染风险发言。

- [ ] **Step 1: 写 `parseDebateHistory` 失败测试**

新建 `webui/lib/debate.test.ts`：

```ts
import assert from "node:assert/strict";
import test from "node:test";

import { INVEST_LABELS, RISK_LABELS, parseDebateHistory } from "./debate.ts";

test("parses bull/bear history into ordered turns with round math", () => {
  const history =
    "\nBull Analyst: 看多理由一\nBear Analyst: 看空理由一\nBull Analyst: 看多理由二\nBear Analyst: 看空理由二";
  const turns = parseDebateHistory(history, 2, INVEST_LABELS);
  assert.equal(turns.length, 4);
  assert.deepEqual(turns[0], { round: 1, speakerLabel: "多方", content: "看多理由一" });
  assert.deepEqual(turns[1], { round: 1, speakerLabel: "空方", content: "看空理由一" });
  assert.equal(turns[2].round, 2);
  assert.equal(turns[3].speakerLabel, "空方");
});

test("parses 3-way risk history with groupSize 3", () => {
  const history =
    "\nAggressive Analyst: 激进\nConservative Analyst: 保守\nNeutral Analyst: 中立\nAggressive Analyst: 再激进";
  const turns = parseDebateHistory(history, 3, RISK_LABELS);
  assert.equal(turns.length, 4);
  assert.equal(turns[0].speakerLabel, "激进");
  assert.equal(turns[2].round, 1);
  assert.equal(turns[3].round, 2);
});

test("returns empty for non-string or blank history", () => {
  assert.deepEqual(parseDebateHistory(undefined, 2, INVEST_LABELS), []);
  assert.deepEqual(parseDebateHistory("", 2, INVEST_LABELS), []);
  assert.deepEqual(parseDebateHistory("   ", 3, RISK_LABELS), []);
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd webui && node --no-warnings --test --experimental-strip-types lib/debate.test.ts`
Expected: FAIL —模块 `./debate.ts` 不存在。

- [ ] **Step 3: 实现 `webui/lib/debate.ts`**

新建 `webui/lib/debate.ts`：

```ts
// Parse a debate `history` string (accumulated as `history + "\n" + argument`,
// each argument prefixed with "<Speaker> Analyst:") into ordered turns.

export type DebateTurn = { round: number; speakerLabel: string; content: string };

export const INVEST_LABELS: Record<string, string> = {
  Bull: "多方",
  Bear: "空方",
};

export const RISK_LABELS: Record<string, string> = {
  Aggressive: "激进",
  Conservative: "保守",
  Neutral: "中立",
};

export function parseDebateHistory(
  history: unknown,
  groupSize: number,
  labels: Record<string, string>,
): DebateTurn[] {
  if (typeof history !== "string" || !history.trim()) return [];
  const re = /(Bull|Bear|Aggressive|Conservative|Neutral) Analyst:/g;
  const marks: { speaker: string; start: number; contentStart: number }[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(history)) !== null) {
    marks.push({ speaker: m[1], start: m.index, contentStart: m.index + m[0].length });
  }
  return marks.map((mark, i) => {
    const end = i + 1 < marks.length ? marks[i + 1].start : history.length;
    return {
      round: Math.floor(i / groupSize) + 1,
      speakerLabel: labels[mark.speaker] ?? mark.speaker,
      content: history.slice(mark.contentStart, end).trim(),
    };
  });
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd webui && node --no-warnings --test --experimental-strip-types lib/debate.test.ts`
Expected: PASS（3 个测试全绿）。

- [ ] **Step 5: 在 `RunDetail` 中渲染历史辩论**

先按 Global Constraints 阅读 `webui/node_modules/next/dist/docs/` 里 Client Components 章节。

在 `webui/components/RunDetail.tsx` 顶部 import 区追加：

```tsx
import { Fragment } from "react";
import { INVEST_LABELS, RISK_LABELS, parseDebateHistory, type DebateTurn } from "@/lib/debate";
```

在组件内部（`RunDetail` 函数体里，`const finalDetail = ...` 之后）计算发言序列与标题：

```tsx
  const investState = result["investment_debate_state"] as { history?: string } | undefined;
  const riskState = result["risk_debate_state"] as { history?: string } | undefined;
  const investTurns = parseDebateHistory(investState?.history, 2, INVEST_LABELS);
  const riskTurns = parseDebateHistory(riskState?.history, 3, RISK_LABELS);
  const investTotal = Math.max(1, Math.ceil(investTurns.length / 2));
  const riskTotal = Math.max(1, Math.ceil(riskTurns.length / 3));
  const heading = (team: string, t: DebateTurn, total: number) =>
    `${team} · 第 ${t.round}/${total} 轮 · ${t.speakerLabel}`;
```

然后把报告 section 的渲染（`{sections.map(...)}` 到 `{run.decision && ...}` 之间）替换为在正确位置插入辩论气泡。将：

```tsx
      {sections.map((s) => (
        <MessageBubble key={s.field} agent={s.label} content={result[s.field] as string} />
      ))}

      {run.decision && (
        <DecisionCard decision={run.decision} detail={hasFinal ? (finalDetail as string) : ""} />
      )}
```

改为：

```tsx
      {sections.map((s) => (
        <Fragment key={s.field}>
          {s.field === "investment_plan" &&
            investTurns.map((t, i) => (
              <MessageBubble
                key={`invest-${i}`}
                agent={heading("多空辩论", t, investTotal)}
                content={t.content}
              />
            ))}
          <MessageBubble agent={s.label} content={result[s.field] as string} />
        </Fragment>
      ))}

      {riskTurns.map((t, i) => (
        <MessageBubble
          key={`risk-${i}`}
          agent={heading("风险辩论", t, riskTotal)}
          content={t.content}
        />
      ))}

      {run.decision && (
        <DecisionCard decision={run.decision} detail={hasFinal ? (finalDetail as string) : ""} />
      )}
```

（注：多空发言插在「研究经理(investment_plan)」气泡前；若该 run 无 `investment_plan` 报告，则多空发言不显示——完成的 run 正常都有该字段。风险发言渲染在所有报告 section 之后、最终决策卡片之前。）

- [ ] **Step 6: 类型检查、lint、全部前端单测**

Run: `cd webui && npx tsc --noEmit && npm run lint && npm test`
Expected: 均通过（`npm test` 覆盖 `lib/*.test.ts` 含新增的 `debate.test.ts`）。

- [ ] **Step 7: 手动验证历史回放（可选但推荐）**

前端打开一个已完成的多轮历史 run：详情页应在「研究经理」之前出现多空辩论各轮发言、在最终决策之前出现风险辩论各轮发言，均带「第 X/N 轮 · 发言人」标题。

- [ ] **Step 8: 更新 CHANGELOG 并提交**

在 `CHANGELOG.md` 的 `## [Unreleased]` → `### Added` 下新增一行（若无该分组则创建）：

```markdown
- WebUI 多空/风险辩论进度可视化：直播时按「第几轮 · 发言人」流式展示每轮发言，Agent Matrix 显示当前轮次；历史 run 可回放完整辩论过程。
```

提交：

```bash
git add webui/lib/debate.ts webui/lib/debate.test.ts webui/components/RunDetail.tsx CHANGELOG.md
git commit -m "feat(webui): replay persisted debate history in run detail view"
```

---

## 收尾验证（全部任务完成后）

- [ ] 后端：`.venv/bin/python -m ruff check .` → 无错误。
- [ ] 后端：`.venv/bin/python -m pytest -m "not integration"` → 全绿。
- [ ] 前端：`cd webui && npx tsc --noEmit && npm run lint && npm test` → 全绿。

## Self-Review 记录

- **Spec 覆盖**：轮次+发言人换算(Task1)、后端事件(Task1/2)、SSE 管道(Task3)、直播消息+Matrix明细(Task4)、历史回放(Task5)、不改 schema/agent(Global Constraints)、测试(各任务 + 收尾) —— 均有对应任务。
- **占位符扫描**：无 TBD/TODO；每个代码步骤含完整可粘贴代码与确切命令。
- **类型一致性**：`debate_events`/`_rounds_config` 签名在 Task1 定义、Task2 使用一致；`SSEEvent.debate_round` 的 `data` 字段与后端 `_round_event` 产出字段逐一对应（team/round/total/speaker/speaker_label/content）；`parseDebateHistory`/`DebateTurn`/`INVEST_LABELS`/`RISK_LABELS` 在 Task5 定义并在 `RunDetail` 使用，命名一致。
