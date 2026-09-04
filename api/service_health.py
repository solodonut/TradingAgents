"""Best-effort remote service health checks for the WebUI."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import requests

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.health_check import check_and_select

ServiceStatus = Literal["checking", "ok", "warning", "error", "disabled"]
ServiceKind = Literal["llm", "data", "system"]

_REQUEST_TIMEOUT = 5
_MAX_ERROR_LEN = 300
_SECRET_KEYS = {"token", "apikey", "api_key"}


def _event(
    *,
    service_id: str,
    name: str,
    kind: ServiceKind,
    status: ServiceStatus,
    message: str,
    latency_ms: int | None = None,
) -> dict:
    return {
        "id": service_id,
        "name": name,
        "kind": kind,
        "status": status,
        "message": message[:_MAX_ERROR_LEN],
        "latency_ms": latency_ms,
    }


def _enabled_data_vendors(config: dict) -> set[str]:
    enabled: set[str] = set()
    data_vendors = config.get("data_vendors", {})
    tool_vendors = config.get("tool_vendors", {})
    for raw in [*data_vendors.values(), *tool_vendors.values()]:
        for vendor in str(raw).split(","):
            normalized = vendor.strip().lower()
            if normalized and normalized not in {"default", "disabled", "none", "off"}:
                enabled.add(normalized)
    return enabled


def _http_probe(
    url: str, *, params: dict | None = None, headers: dict | None = None
) -> tuple[bool, str, int]:
    start = time.monotonic()
    try:
        response = requests.get(url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT)
        elapsed = int((time.monotonic() - start) * 1000)
        if 200 <= response.status_code < 400:
            return True, "Reachable", elapsed
        return False, f"HTTP {response.status_code}", elapsed
    except Exception as exc:  # noqa: BLE001 - any exception is a service failure
        elapsed = int((time.monotonic() - start) * 1000)
        message = _redact_secret_values(f"{type(exc).__name__}: {exc}", params)
        return False, message, elapsed


def _redact_secret_values(message: str, *containers: object) -> str:
    secrets: set[str] = set()

    def collect(value: object, key: str | None = None) -> None:
        if key and key.lower() in _SECRET_KEYS and value is not None:
            text = str(value)
            if text:
                secrets.add(text)
        elif isinstance(value, dict):
            for child_key, child_value in value.items():
                collect(child_value, str(child_key))
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    for container in containers:
        collect(container)

    redacted = message
    for secret in secrets:
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _json_probe(
    url: str,
    *,
    method: str = "GET",
    params: dict | None = None,
    json_payload: dict | None = None,
    headers: dict | None = None,
) -> tuple[bool, object, int]:
    start = time.monotonic()
    try:
        if method.upper() == "POST":
            response = requests.post(
                url,
                params=params,
                json=json_payload,
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
            )
        else:
            response = requests.get(url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT)
        elapsed = int((time.monotonic() - start) * 1000)
        if not 200 <= response.status_code < 400:
            return False, f"HTTP {response.status_code}", elapsed
        return True, response.json(), elapsed
    except Exception as exc:  # noqa: BLE001 - any exception is a service failure
        elapsed = int((time.monotonic() - start) * 1000)
        message = _redact_secret_values(f"{type(exc).__name__}: {exc}", params, json_payload)
        return False, message, elapsed


def _text_probe(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    encoding: str = "utf-8",
) -> tuple[bool, str, int]:
    """GET ``url`` 并返回响应正文,供需要自己解析非 JSON 正文的探针使用。

    只给腾讯/新浪这类**境内网页内部接口**用,两点与 ``_http_probe`` 不同:

    - ``trust_env = False`` 强制绕过代理。企业代理隧道不到境内主机(见
      ``akshare_utils.no_proxy_session`` 的说明),不绕过会让健康检查报红而实际取数
      是好的。这里用 session 级开关而不是那个上下文管理器 —— 后者猴补丁
      ``requests.Session.__init__`` 并清空进程级环境变量,并发时会波及同进程里
      正需要代理的 LLM 调用。
    - 不复用 vendor 的 ``ak_retry``:那条路有 6 次指数退避重试(最坏上百秒)和进程级
      熔断,会把 SSE 健康流拖死,还会污染真实调用的熔断状态。
    """
    start = time.monotonic()
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT)
        elapsed = int((time.monotonic() - start) * 1000)
        if not 200 <= response.status_code < 400:
            return False, f"HTTP {response.status_code}", elapsed
        # 响应头不带 charset 时 requests 会猜成 ISO-8859-1,中文变乱码,故显式指定。
        response.encoding = encoding
        return True, response.text, elapsed
    except Exception as exc:  # noqa: BLE001 - any exception is a service failure
        elapsed = int((time.monotonic() - start) * 1000)
        message = _redact_secret_values(f"{type(exc).__name__}: {exc}", params)
        return False, message, elapsed


def _today_compact() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


def _format_compact_date(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def _normalize_date(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        if value > 10_000_000_000:
            value = value / 1000
        try:
            return datetime.fromtimestamp(value, tz=ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return None


def _extract_latest_date(payload: object) -> str | None:
    dates: list[str] = []

    def visit(value: object, key: str | None = None) -> None:
        if key and (
            key.lower()
            in {"date", "trade_date", "cal_date", "latesttradingday", "07. latest trading day"}
            or (isinstance(value, int) and key.lower() in {"timestamp", "time"})
        ):
            normalized = _normalize_date(value)
            if normalized:
                dates.append(normalized)

        if isinstance(value, dict):
            fields = value.get("fields")
            items = value.get("items")
            if isinstance(fields, list) and isinstance(items, list):
                date_indexes = [
                    index
                    for index, field in enumerate(fields)
                    if str(field).lower() in {"date", "trade_date", "cal_date"}
                ]
                for item in items:
                    if not isinstance(item, (list, tuple)):
                        continue
                    for index in date_indexes:
                        if index < len(item):
                            normalized = _normalize_date(item[index])
                            if normalized:
                                dates.append(normalized)

            for child_key, child_value in value.items():
                normalized_key = _normalize_date(child_key)
                if normalized_key:
                    dates.append(normalized_key)
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str) and "," in value:
            normalized = _normalize_date(value.split(",", 1)[0])
            if normalized:
                dates.append(normalized)

    visit(payload)
    return max(dates) if dates else None


def _freshness_status(latest_date: str) -> tuple[ServiceStatus, str]:
    expected = _today_compact()
    latest_label = _format_compact_date(latest_date)
    expected_label = _format_compact_date(expected)
    if latest_date == expected:
        return "ok", f"Reachable; latest daily data is {latest_label}"
    return (
        "warning",
        f"Reachable, but latest daily data is {latest_label}; expected {expected_label}",
    )


def _json_probe_args(probe_spec: dict, api_key: str | None) -> tuple[dict, dict]:
    params = dict(probe_spec.get("params", {}))
    json_payload = dict(probe_spec.get("json_payload", {}))

    key_target = probe_spec.get("api_key")
    if api_key and key_target == "params:apikey":
        params["apikey"] = api_key
    elif api_key and key_target == "params:api_key":
        params["api_key"] = api_key
    elif api_key and key_target == "json:token":
        json_payload["token"] = api_key

    return params, json_payload


def _same_json_probe(base: dict, freshness: dict) -> bool:
    return (
        str(base.get("url")) == str(freshness.get("url"))
        and str(base.get("method", "GET")).upper() == str(freshness.get("method", "GET")).upper()
        and dict(base.get("params", {})) == dict(freshness.get("params", {}))
        and dict(base.get("json_payload", {})) == dict(freshness.get("json_payload", {}))
        and base.get("headers") == freshness.get("headers")
        and base.get("api_key") == freshness.get("api_key")
    )


def _run_combined_freshness_probe(spec: dict, api_key: str | None) -> tuple[ServiceStatus, str, int]:
    freshness = dict(spec["freshness"])
    params, json_payload = _json_probe_args(freshness, api_key)

    ok, payload, latency_ms = _json_probe(
        str(freshness["url"]),
        method=str(freshness.get("method", "GET")),
        params=params or None,
        json_payload=json_payload or None,
        headers=freshness.get("headers"),
    )
    if not ok:
        return "error", str(payload), latency_ms

    latest_date = _extract_latest_date(payload)
    if not latest_date:
        return "error", "Reachable, but freshness response had no usable date", latency_ms

    status, message = _freshness_status(latest_date)
    return status, message, latency_ms


def _run_json_reachability_probe(spec: dict, api_key: str | None) -> tuple[bool, str, int]:
    reachability = dict(spec["reachability"])
    params, json_payload = _json_probe_args(reachability, api_key)

    ok, payload, latency_ms = _json_probe(
        str(reachability["url"]),
        method=str(reachability.get("method", "GET")),
        params=params or None,
        json_payload=json_payload or None,
        headers=reachability.get("headers"),
    )
    if not ok:
        return False, str(payload), latency_ms
    return True, "Reachable", latency_ms


def _run_freshness_probe(spec: dict, api_key: str | None) -> tuple[ServiceStatus, str, int]:
    freshness = dict(spec["freshness"])
    params, json_payload = _json_probe_args(freshness, api_key)

    ok, payload, latency_ms = _json_probe(
        str(freshness["url"]),
        method=str(freshness.get("method", "GET")),
        params=params or None,
        json_payload=json_payload or None,
        headers=freshness.get("headers"),
    )
    if not ok:
        return "error", str(payload), latency_ms

    latest_date = _extract_latest_date(payload)
    if not latest_date:
        return "error", "Reachable, but freshness response had no usable date", latency_ms

    status, message = _freshness_status(latest_date)
    return status, message, latency_ms


_AMAZINGDATA_REF_CODE = "000001.SZ"  # 平安银行,与 Tushare freshness 探测同参考标的


def _lookback_compact(days: int) -> str:
    dt = datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=days)
    return dt.strftime("%Y%m%d")


def _amazingdata_latest_date(payload: object) -> str | None:
    """从 /kline 响应({data: {code: [{kline_time: YYYYMMDD, ...}]}})取最新交易日。

    kline_time 是整型 YYYYMMDD(如 20260710),须先转字符串再交给 _normalize_date
    ——否则会被当成 Unix 时间戳误解析。
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    records: object = None
    if isinstance(data, dict):
        records = data.get(_AMAZINGDATA_REF_CODE)
        if records is None and len(data) == 1:
            records = next(iter(data.values()))
    elif isinstance(data, list):
        records = data
    if not isinstance(records, list):
        return None

    dates: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        raw = record.get("kline_time")
        normalized = _normalize_date(str(raw)) if raw is not None else None
        if normalized:
            dates.append(normalized)
    return max(dates) if dates else None


def _run_amazingdata_probe() -> tuple[ServiceStatus, str, int]:
    from tradingagents.dataflows import ad_service_client

    start = time.monotonic()
    if not ad_service_client.service_available():
        latency_ms = int((time.monotonic() - start) * 1000)
        return (
            "error",
            "Local service unreachable or not logged in (check AD_API_PORT/AD_API_BASE)",
            latency_ms,
        )

    try:
        payload = ad_service_client.call(
            "/kline",
            method="POST",
            json={
                "code_list": [_AMAZINGDATA_REF_CODE],
                "begin_date": int(_lookback_compact(30)),
                "end_date": int(_today_compact()),
                "period": "day",
                "adjust": "none",  # 不复权:免去后复权因子拉取(首次约 38s)
            },
            timeout=_REQUEST_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 - freshness 探测失败降级为 warning,不误报 error
        latency_ms = int((time.monotonic() - start) * 1000)
        return (
            "warning",
            f"Reachable, but latest data date is unavailable ({type(exc).__name__})",
            latency_ms,
        )

    latency_ms = int((time.monotonic() - start) * 1000)
    latest_date = _amazingdata_latest_date(payload)
    if not latest_date:
        return "warning", "Reachable, but latest data date is unavailable", latency_ms
    status, message = _freshness_status(latest_date)
    return status, message, latency_ms


_TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q=sh510300"  # 沪深300ETF华泰柏瑞:最大、几乎不停牌

# 下标与 tencent_etf 的实测字段表一致(第 30 位快照时间、第 78 位 IOPV、第 81 位单位净值)。
# 腾讯是网页内部接口,字段位置漂移一次就会让 IOPV 静默失真,所以这里盯住字段数与 IOPV。
_TENCENT_IDX_TIMESTAMP = 30
_TENCENT_IDX_IOPV = 78
_TENCENT_MIN_FIELDS = 82


def _run_tencent_probe() -> tuple[ServiceStatus, str, int]:
    """探腾讯 ``qt.gtimg.cn`` 实时快照 —— IOPV / 折溢价在本项目没有第二个来源。

    腾讯另一个域(``web.ifzq.gtimg.cn`` 日线)只在 ``core_stock_apis`` 链尾兜底,前两档
    健康时根本不会被调用,所以这张卡盯住独此一家的那条路径。要逐 cell 探整张
    ``VENDOR_METHODS`` 表用 ``/api/diagnostics/etf/{code}``。
    """
    from tradingagents.dataflows.tencent_utils import parse_quote_fields

    ok, text, latency_ms = _text_probe(_TENCENT_QUOTE_URL, encoding="gbk")
    if not ok:
        return "error", text, latency_ms

    fields = parse_quote_fields(text)
    if not fields:
        return (
            "error",
            "Reachable, but the quote response was empty (rate-limited or blocked)",
            latency_ms,
        )
    if len(fields) < _TENCENT_MIN_FIELDS:
        return (
            "error",
            f"Reachable, but the quote had {len(fields)} fields; "
            f"expected at least {_TENCENT_MIN_FIELDS}",
            latency_ms,
        )

    try:
        iopv = float(fields[_TENCENT_IDX_IOPV])
    except ValueError:
        iopv = 0.0
    if not iopv:
        # 零值拦截:vendor 这时会抛 NoMarketDataError,IOPV 实际已断供,但停牌/非交易
        # 时段也可能是 0,所以报 warning 而不是 error。
        return (
            "warning",
            "Reachable, but IOPV is missing or zero (suspended or upstream error)",
            latency_ms,
        )

    latest_date = _normalize_date(fields[_TENCENT_IDX_TIMESTAMP])
    if not latest_date:
        return "warning", "Reachable, but the snapshot has no usable timestamp", latency_ms
    status, message = _freshness_status(latest_date)
    return status, message, latency_ms


_SINA_FEED_URL = "https://zhibo.sina.com.cn/api/zhibo/feed"
_SINA_FEED_PARAMS = {
    "page": 1,
    "page_size": 1,
    "zhibo_id": 152,  # 新浪财经 7×24 直播间,与 sina_global_news 一致
    "tag_id": 0,
    "dire": "f",
    "dpc": 1,
}
# 新浪缺 Referer 会 403(见 sina_utils)。
_SINA_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}


def _run_sina_probe() -> tuple[ServiceStatus, str, int]:
    """探新浪 7×24 快讯 feed —— ``get_global_news`` 境内唯一可直连的第二档。

    新浪的另一个能力(个股新闻页 ``vip.stock.finance.sina.com.cn``)在 ``get_news`` 里排
    第三,前面有东财 + Tushare 两档,所以不单独探。不做新鲜度判定:新闻源没有「今天的
    行情数据」这层语义,与 Eastmoney 那张卡一致(见 data-service-freshness 设计文档)。
    """
    ok, text, latency_ms = _text_probe(
        _SINA_FEED_URL, params=_SINA_FEED_PARAMS, headers=_SINA_HEADERS
    )
    if not ok:
        return "error", text, latency_ms

    try:
        payload = json.loads(text)
    except ValueError:
        return "error", "Reachable, but the feed response was not JSON", latency_ms

    result = payload.get("result") if isinstance(payload, dict) else None
    data = result.get("data") if isinstance(result, dict) else None
    feed = data.get("feed") if isinstance(data, dict) else None
    items = feed.get("list") if isinstance(feed, dict) else None
    if not items:
        # HTTP 200 + 空列表是抓取式接口的典型静默失败,可达但取不到东西。
        return "warning", "Reachable, but the 7x24 feed returned no items", latency_ms
    return "ok", "Reachable", latency_ms


def _probe_llm_services(config: dict) -> Iterator[dict]:
    yield _event(
        service_id="llm:provider",
        name=f"LLM Provider: {config.get('llm_provider', 'unknown')}",
        kind="llm",
        status="checking",
        message="Checking configured LLM models",
    )

    report = check_and_select(config)
    for slot, slot_report in report.slots.items():
        slot_label = "Deep LLM" if slot == "deep_think_llm" else "Quick LLM"
        for candidate in slot_report.candidates:
            selected = candidate.model == slot_report.selected
            if candidate.ok:
                message = "Reachable"
                if selected and slot_report.configured != slot_report.selected:
                    message = f"Reachable; selected fallback for {slot_label}"
                elif selected:
                    message = f"Reachable; selected for {slot_label}"
                status: ServiceStatus = "ok"
            else:
                message = candidate.error or "Unavailable"
                status = "error"
            yield _event(
                service_id=f"llm:{slot}:{candidate.model}",
                name=f"{slot_label}: {candidate.model}",
                kind="llm",
                status=status,
                message=message,
                latency_ms=candidate.latency_ms,
            )
    yield _event(
        service_id="llm:provider",
        name=f"LLM Provider: {report.provider}",
        kind="llm",
        status="error" if report.any_failed else "ok",
        message="One or more LLM slots have no reachable model"
        if report.any_failed
        else "Configured LLM provider has reachable models",
    )


_DATA_SERVICES = {
    "amazingdata": {
        # 本地常驻 daemon(header 鉴权 X-API-Token + 上游登录态 logged_in),
        # 不走 url+params 的远程 API 探测模式;用专门分支复用其 /health 探活。
        "name": "AmazingData 本地服务",
        "probe": "amazingdata",
    },
    "eastmoney": {
        # East Money direct-search news (search-api-web). Needs a browser UA +
        # Referer, so it gets its own probe rather than sharing the push2 quote
        # domain's. See eastmoney_news.get_news.
        "name": "Eastmoney 直连",
        "url": "https://search-api-web.eastmoney.com/search/jsonp",
        "params": {
            "cb": "x",
            "param": '{"uid":"","keyword":"510300","type":["cmsArticleWebOld"],'
            '"pageIndex":1,"pageSize":1}',
        },
        "headers": {"User-Agent": "Mozilla/5.0", "Referer": "https://so.eastmoney.com/"},
        "env": None,
    },
    "yfinance": {
        "name": "Yahoo Finance",
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
        "params": {"range": "1d", "interval": "1d"},
        "env": None,
        "freshness": {
            "url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
            "params": {"range": "1d", "interval": "1d"},
        },
    },
    "alpha_vantage": {
        "name": "Alpha Vantage",
        "url": "https://www.alphavantage.co/query",
        "params": {"function": "GLOBAL_QUOTE", "symbol": "AAPL"},
        "env": "ALPHA_VANTAGE_API_KEY",
        "freshness": {
            "url": "https://www.alphavantage.co/query",
            "params": {"function": "GLOBAL_QUOTE", "symbol": "AAPL"},
            "api_key": "params:apikey",
        },
    },
    "tushare": {
        "name": "Tushare Pro",
        "url": "https://api.tushare.pro",
        "params": {
            "api_name": "trade_cal",
            "params": "{}",
            "fields": "cal_date,is_open",
        },
        "env": "TUSHARE_TOKEN",
        "reachability": {
            "url": "https://api.tushare.pro",
            "method": "POST",
            "json_payload": {
                "api_name": "trade_cal",
                "params": {},
                "fields": "cal_date,is_open",
            },
            "api_key": "json:token",
        },
        "freshness": {
            "url": "https://api.tushare.pro",
            "method": "POST",
            "json_payload": {
                "api_name": "daily",
                "params": {"ts_code": "000001.SZ", "limit": 1},
                "fields": "trade_date",
            },
            "api_key": "json:token",
        },
    },
    "fred": {
        "name": "FRED",
        "url": "https://api.stlouisfed.org/fred/series/observations",
        "params": {"series_id": "DGS10", "limit": "1", "file_type": "json"},
        "env": "FRED_API_KEY",
        "freshness": {
            "url": "https://api.stlouisfed.org/fred/series/observations",
            "params": {
                "series_id": "DGS10",
                "limit": "1",
                "file_type": "json",
                "sort_order": "desc",
            },
            "api_key": "params:api_key",
        },
    },
    "polymarket": {
        "name": "Polymarket",
        "url": "https://gamma-api.polymarket.com/markets",
        "params": {"limit": "1"},
        "env": None,
    },
    "tencent": {
        # 网页内部接口:零费用、免 key、无 SLA。正文是 GBK 的 ~ 分隔串而不是 JSON,
        # 且要校验字段位置,所以走专门分支而不是 url+params 模式。
        "name": "腾讯行情 (IOPV)",
        "probe": "tencent",
    },
    "sina": {
        # 同为网页内部接口。JSON 但嵌套三层且需要 Referer,也走专门分支。
        "name": "新浪财经 7×24",
        "probe": "sina",
    },
}

# 不适用「url + params 可达性探测」模式的服务:本地 daemon、需要校验正文结构的抓取式接口。
_CUSTOM_PROBES = {
    "amazingdata": _run_amazingdata_probe,
    "tencent": _run_tencent_probe,
    "sina": _run_sina_probe,
}


def _probe_data_services(config: dict) -> Iterator[dict]:
    enabled = _enabled_data_vendors(config)
    for service_id, spec in _DATA_SERVICES.items():
        name = str(spec["name"])
        if service_id not in enabled:
            yield _event(
                service_id=f"data:{service_id}",
                name=name,
                kind="data",
                status="disabled",
                message="Disabled by current configuration",
            )
            continue

        probe_kind = spec.get("probe")
        if probe_kind:
            status, message, latency_ms = _CUSTOM_PROBES[str(probe_kind)]()
            yield _event(
                service_id=f"data:{service_id}",
                name=name,
                kind="data",
                status=status,
                message=message,
                latency_ms=latency_ms,
            )
            continue

        env_var = spec.get("env")
        params = dict(spec["params"])
        api_key = None
        if env_var:
            api_key = os.getenv(str(env_var))
            if not api_key:
                yield _event(
                    service_id=f"data:{service_id}",
                    name=name,
                    kind="data",
                    status="error",
                    message=f"{env_var} is not set",
                )
                continue
            if service_id == "fred":
                params["api_key"] = api_key
            elif service_id == "tushare":
                pass
            else:
                params["apikey"] = api_key

        freshness = spec.get("freshness")
        if freshness and _same_json_probe(spec, dict(freshness)):
            status, message, latency_ms = _run_combined_freshness_probe(spec, api_key)
            yield _event(
                service_id=f"data:{service_id}",
                name=name,
                kind="data",
                status=status,
                message=message,
                latency_ms=latency_ms,
            )
            continue

        if "reachability" in spec:
            ok, message, latency_ms = _run_json_reachability_probe(spec, api_key)
        else:
            ok, message, latency_ms = _http_probe(
                str(spec["url"]), params=params, headers=spec.get("headers")
            )
        status: ServiceStatus = "ok" if ok else "error"
        if ok and freshness:
            status, message, freshness_latency_ms = _run_freshness_probe(spec, api_key)
            latency_ms += freshness_latency_ms
        yield _event(
            service_id=f"data:{service_id}",
            name=name,
            kind="data",
            status=status,
            message=message,
            latency_ms=latency_ms,
        )


def generate_service_health_events(config: dict | None = None) -> Iterator[dict]:
    """Yield service status events followed by one summary event."""
    checks_config = dict(config or DEFAULT_CONFIG)
    statuses: dict[str, dict] = {}

    try:
        for status in _probe_llm_services(checks_config):
            statuses[status["id"]] = status
            yield {"event": "service_status", "data": status}
        for status in _probe_data_services(checks_config):
            statuses[status["id"]] = status
            yield {"event": "service_status", "data": status}
    except Exception as exc:  # noqa: BLE001 - health check must report, not crash
        status = _event(
            service_id="health:internal",
            name="Service health checker",
            kind="system",
            status="error",
            message=f"{type(exc).__name__}: {exc}",
        )
        statuses[status["id"]] = status
        yield {"event": "service_status", "data": status}

    latest = list(statuses.values())
    summary = {
        "total": len(latest),
        "checking": sum(1 for item in latest if item["status"] == "checking"),
        "ok": sum(1 for item in latest if item["status"] == "ok"),
        "warning": sum(1 for item in latest if item["status"] == "warning"),
        "error": sum(1 for item in latest if item["status"] == "error"),
        "disabled": sum(1 for item in latest if item["status"] == "disabled"),
    }
    yield {"event": "summary", "data": summary}


def probe_single_service_health(service_id: str, config: dict | None = None) -> dict | None:
    """Return a fresh status for exactly one service id, or None if unknown."""
    checks_config = dict(config or DEFAULT_CONFIG)

    if service_id.startswith("data:"):
        probes = _probe_data_services(checks_config)
    elif service_id.startswith("llm:"):
        probes = _probe_llm_services(checks_config)
    else:
        probes = iter(())

    for status in probes:
        if status["id"] == service_id:
            return status
    return None
