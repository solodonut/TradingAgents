"""AmazingData 常驻服务的 HTTP 客户端:探测 + 调用。

从 ad-api skill 原样复制而来(仅依赖标准库 urllib,自包含,无需额外安装)。
服务在跑时优先用它取数(经本地 HTTP 复用登录态,不占用 AmazingData 单点登录);
不在跑时调用方应回退到其他 vendor(tushare/akshare)。

读取环境变量 AD_API_TOKEN、AD_API_PORT(默认 8888);也可用 AD_API_BASE 覆盖 base。
"""
import json as _json
import os
import urllib.error
import urllib.request

# 服务永远是本地(127.0.0.1 或 AD_API_BASE 指向的本机);本项目环境设了 HTTP_PROXY/
# HTTPS_PROXY,urllib 默认会把 localhost 也经代理转发、被代理 403 拒绝。用空 ProxyHandler
# 的 opener 强制直连,绕过代理。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _base(base=None):
    if base:
        return base.rstrip("/")
    if os.environ.get("AD_API_BASE"):
        return os.environ["AD_API_BASE"].rstrip("/")
    port = os.environ.get("AD_API_PORT", "8888")
    return f"http://127.0.0.1:{port}"


def service_available(base=None, timeout=2.0):
    """探测 /health;仅当 HTTP 200 且 logged_in 为真时返回 True。"""
    url = _base(base) + "/health"
    try:
        with _OPENER.open(url, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = _json.loads(resp.read().decode("utf-8"))
            return bool(body.get("logged_in"))
    except Exception:
        return False


def call(path, method="GET", params=None, json=None, base=None, timeout=60.0):
    """调用服务端点。自动带 X-API-Token。非 2xx 抛 RuntimeError。返回解析后的 dict。"""
    url = _base(base) + path
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    data = None
    headers = {"X-API-Token": os.environ.get("AD_API_TOKEN", "")}
    if json is not None:
        data = _json.dumps(json).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return _json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e
