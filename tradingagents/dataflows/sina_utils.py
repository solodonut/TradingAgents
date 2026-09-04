"""新浪财经接口的共享抓取层。

与腾讯的关键差异:**新浪必须带 Referer**(``hq.sinajs.cn`` 无 Referer 直接 403),
所以这里统一注入。同为网页内部接口:零费用、无需 key、无授权、无 SLA。

复用 ``akshare_utils.ak_retry``(代理绕过 + 指数退避 + 熔断)。``akshare_utils`` 不是
AKShare 的封装,而是通用抓取工具箱,AKShare 停用后仍在使用。
"""

from __future__ import annotations

import requests

from .akshare_utils import ak_retry

_TIMEOUT = 20

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    # 缺这一行 hq.sinajs.cn 会返回 403。
    "Referer": "https://finance.sina.com.cn/",
}


def fetch_text(url: str, params: dict | None = None, encoding: str = "utf-8") -> str:
    """GET ``url`` 并返回文本,走代理绕过与网络重试。

    ``encoding`` 需显式指定:新浪的老页面是 GB18030,新接口是 UTF-8,响应头都不带
    charset,靠 requests 猜会把中文变成乱码。
    """

    def _get() -> str:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = encoding
        return resp.text

    return ak_retry(_get, circuit_key=url)
