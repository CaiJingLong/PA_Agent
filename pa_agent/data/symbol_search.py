"""Search stock / index / fund / futures codes via Sina's suggest API.

Covers A-shares (SH/SZ/BJ), HK stocks, US stocks, ETFs, funds, futures and
indices.  No API key required; the endpoint returns GBK-encoded JavaScript
(``var suggestdata="...";``) which we parse into structured rows.

Each result is a dict::

    {"code", "name", "market", "type"}

where ``market`` is a short label (``SH``/``SZ``/``HK``/``US``/``期货``/...)
and ``type`` is the security type name (``A股``/``港股``/``美股``/...).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_SINA_SUGGEST_URL = "https://suggest3.sinajs.cn/suggest/type="
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}

try:
    from curl_cffi import requests as _http  # type: ignore
    _IMPERSONATE = "chrome120"
except ImportError:  # pragma: no cover
    import requests as _http  # type: ignore
    _IMPERSONATE = None


# fullcode prefix → market label.  Sina's ``fields[3]`` carries the exchange
# prefix (sh/sz/bj/hk/of/us/...), which is the only reliable way to tell
# ``sh000001`` (上证指数) apart from ``sz000001`` (平安银行) — Sina tags both
# with type code ``11`` ("A股").
_PREFIX_MARKET: dict[str, str] = {
    "sh": "SH",
    "sz": "SZ",
    "bj": "BJ",
    "hk": "HK",
    "of": "基金",
    "us": "US",
    "nf": "期货",
    "fo": "期货",
}

# Sina type code (field index 1) → type label.  Market label is derived from
# the fullcode prefix instead, so this map only carries the security type.
_TYPE_LABEL: dict[str, str] = {
    "11": "A股",
    "12": "指数",
    "13": "指数",
    "21": "基金",
    "23": "LOF",
    "24": "基金",
    "31": "港股",
    "33": "港股",
    "41": "美股",
    "42": "美股",
    "71": "加密",
    "73": "加密",
    "81": "期货",
    "82": "期货",
    "83": "期权",
    "87": "期货",
    "103": "美股",
    "104": "美股",
    "105": "美股",
    "106": "美股",
    "201": "基金",
}

_VAR_RE = re.compile(r'var\s+suggestdata\s*=\s*"(?P<body>.*)"\s*;', re.DOTALL)


class SymbolSearchError(Exception):
    """Raised when the suggest API cannot be reached or returns junk."""


def _market_for(fullcode: str, type_code: str) -> str:
    """Market label from the fullcode exchange prefix.

    Falls back to the type-code map only when the prefix is unrecognized
    (e.g. crypto / futures without an ``nf``/``fo`` prefix).
    """
    fc = (fullcode or "").lower()
    for prefix in ("sh", "sz", "bj", "hk", "of", "us", "nf", "fo"):
        if fc.startswith(prefix):
            return _PREFIX_MARKET[prefix]
    # Fallbacks for prefixes not in _PREFIX_MARKET.
    if type_code in ("31", "33"):
        return "HK"
    if type_code in ("41", "42", "103", "104", "105", "106"):
        return "US"
    if type_code in ("71", "73"):
        return "加密"
    if type_code in ("81", "82", "83", "87"):
        return "期货"
    return ""


def _type_label(fullcode: str, type_code: str) -> str:
    """Security type label.

    Sina tags SH/SZ indices (e.g. ``sh000001`` 上证指数, ``sz399001`` 深证成指)
    with type code ``11`` — same as plain A-shares — so we detect indices by
    code pattern: ``sh000xxx`` and ``sz399xxx`` are indices.
    """
    fc = (fullcode or "").lower()
    code6 = fc[2:8] if len(fc) >= 8 else fc
    if fc.startswith("sh") and code6.startswith("000"):
        return "指数"
    if fc.startswith("sz") and code6.startswith("399"):
        return "指数"
    return _TYPE_LABEL.get(type_code, "")


def _normalize_code(code: str, type_code: str, fullcode: str) -> str:
    """Return the code to fill into the symbol combo.

    HK stocks: strip leading zeros (``00700`` → ``700``) to match the
    TradingView / eastmoney convention used elsewhere in the app.
    A-shares: keep the 6-digit code as-is.
    """
    if type_code in ("31", "33") or fullcode.lower().startswith("hk"):
        return code.lstrip("0") or code
    return code


def search_symbols(keyword: str, *, count: int = 30, timeout: float = 5.0) -> list[dict[str, str]]:
    """Search codes by keyword (code fragment or Chinese/English name).

    Returns up to ``count`` dicts sorted in the order Sina returns them
    (relevance-ranked).  Raises :class:`SymbolSearchError` on transport/parse
    failure.
    """
    kw = (keyword or "").strip()
    if not kw:
        return []

    kwargs: dict[str, object] = {
        "params": {"key": kw, "name": "suggestdata"},
        "headers": _HEADERS,
        "timeout": timeout,
    }
    if _IMPERSONATE:
        kwargs["impersonate"] = _IMPERSONATE

    try:
        resp = _http.get(_SINA_SUGGEST_URL, **kwargs)  # type: ignore[arg-type]
        resp.raise_for_status()
        # Sina returns GBK; curl_cffi/requests expose .encoding and .text.
        if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "ascii"):
            resp.encoding = "gbk"
        text = resp.text
    except Exception as exc:
        logger.warning("symbol search failed for %r: %s", kw, exc)
        raise SymbolSearchError(f"搜索接口请求失败: {exc}") from exc

    m = _VAR_RE.search(text)
    body = m.group("body") if m else ""
    if not body:
        return []

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in body.split(";"):
        record = record.strip()
        if not record:
            continue
        fields = record.split(",")
        if len(fields) < 5:
            continue
        # fields: [keyword, type, code, fullcode, name, ...]
        type_code = fields[1].strip()
        code = fields[2].strip()
        fullcode = fields[3].strip()
        name = fields[4].strip()
        if not code:
            continue
        norm = _normalize_code(code, type_code, fullcode)
        mkt = _market_for(fullcode, type_code)
        typ = _type_label(fullcode, type_code)
        key = f"{mkt}:{norm}:{name}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "code": norm,
                "fullcode": fullcode,
                "name": name or norm,
                "market": mkt,
                "type": typ,
            }
        )
        if len(out) >= count:
            break
    return out
