"""腾讯行情接口(``qt.gtimg.cn`` / ``web.ifzq.gtimg.cn``)的共享抓取层。

腾讯这两个域是网页/App 内部接口:零费用、不需要 key、**不需要 Referer**(新浪的
``hq.sinajs.cn`` 无 Referer 会 403,腾讯没有这个限制)。无授权、无 SLA —— 所以它在默认
配置里只放链尾兜底,见 docs/data-sources.md 第 7.1 / 9.3.2 节。

复用 ``akshare_utils`` 的网络设施(``ak_retry`` = 代理绕过 + 指数退避 + 熔断)。
``akshare_utils`` 不是 AKShare 的封装,而是通用的抓取工具箱,AKShare 停用后仍在使用。
"""

from __future__ import annotations

import requests

from .akshare_utils import ak_retry

# 快照接口返回 GBK,且响应头不带 charset —— requests 会猜成 ISO-8859-1 并把中文名
# 变成乱码,必须显式指定。K 线接口是 UTF-8 JSON,所以编码作为参数传入。
_TIMEOUT = 15


def fetch_text(url: str, params: dict | None = None, encoding: str = "utf-8") -> str:
    """GET ``url`` 并返回文本,走代理绕过与网络重试。

    非网络异常(解析、坏代码)直接上抛 —— 重试它们只是浪费时间。网络类异常由
    ``ak_retry`` 重试,耗尽后上抛,由 ``route_to_vendor`` 归入 ``_NETWORK_ERRORS``
    并降级成 DATA_SOURCE_UNAVAILABLE 哨兵而不是 crash 整个 run。
    """

    def _get() -> str:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        resp.encoding = encoding
        return resp.text

    return ak_retry(_get, circuit_key=url)


def parse_quote_fields(raw: str) -> list[str]:
    """把 ``v_sh510300="1~名称~...~";`` 拆成字段列表。

    上游用 ``~`` 分隔,实测 A 股/ETF 均为 88 个字段。返回空列表表示上游给了空响应
    (限频或被拦),由调用方转成 ``NoMarketDataError``。
    """
    if not isinstance(raw, str) or '="' not in raw:
        return []
    body = raw.split('="', 1)[1]
    body = body.rstrip().rstrip(";").rstrip('"')
    if not body:
        return []
    return body.split("~")
