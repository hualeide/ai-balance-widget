"""拉 Cursor / ChatGPT / Gemini / DeepSeek 额度。"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from typing import Any

import requests

BROKE_PCT = 8
TIMEOUT = 20


def _num(v: Any) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) != float("inf") else None


def _fail(msg: str) -> dict:
    return {"ok": False, "error": msg}


def _snap(amount: float, unit: str, remaining_pct: float | None, hint: str) -> dict:
    broke = remaining_pct is not None and remaining_pct <= BROKE_PCT
    return {
        "ok": True,
        "amount": amount,
        "unit": unit,
        "remainingPct": remaining_pct,
        "hint": hint,
        "broke": broke,
    }


def _cookie_jar(domains: list[str]):
    try:
        import rookiepy
    except ImportError:
        return None
    for loader in (getattr(rookiepy, "edge", None), getattr(rookiepy, "chrome", None), getattr(rookiepy, "brave", None)):
        if not loader:
            continue
        try:
            cookies = loader(domains)
        except Exception:
            continue
        if not cookies:
            continue
        jar = requests.cookies.RequestsCookieJar()
        for c in cookies:
            try:
                jar.set(c["name"], c["value"], domain=c.get("domain") or "", path=c.get("path") or "/")
            except Exception:
                continue
        if len(jar):
            return jar
    return None


def _get(url: str, jar=None, headers=None, method="GET", body=None):
    kw = {"timeout": TIMEOUT, "headers": headers or {}, "allow_redirects": True}
    if jar is not None:
        kw["cookies"] = jar
    if method == "POST":
        if isinstance(body, (dict, list)):
            kw["json"] = body
        elif body:
            kw["data"] = body
        return requests.post(url, **kw)
    return requests.get(url, **kw)


def _cursor_token() -> str | None:
    db = os.path.join(os.environ.get("APPDATA", ""), "Cursor", "User", "globalStorage", "state.vscdb")
    if not os.path.isfile(db):
        return None
    keys = (
        "cursorAuth/accessToken",
        "cursorAuth/cachedAccessToken",
        "WorkosCursorAccessToken",
    )
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for key in keys:
                row = con.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
                if row and row[0]:
                    val = row[0]
                    if isinstance(val, bytes):
                        val = val.decode("utf-8", "ignore")
                    val = str(val).strip().strip('"')
                    if val:
                        return val
            rows = con.execute(
                "SELECT key, value FROM ItemTable WHERE key LIKE '%accessToken%' OR key LIKE '%AccessToken%'"
            ).fetchall()
            for key, val in rows:
                if not val:
                    continue
                if isinstance(val, bytes):
                    val = val.decode("utf-8", "ignore")
                val = str(val).strip().strip('"')
                if val.startswith("eyJ") or len(val) > 20:
                    return val
        finally:
            con.close()
    except Exception:
        return None
    return None


def _parse_cursor(data: dict | None) -> dict | None:
    if not isinstance(data, dict):
        return None
    if data.get("isUnlimited"):
        return _snap(float("inf"), "", 100, "不限量")

    plan = (data.get("individualUsage") or {}).get("plan") or {}
    overall = (data.get("individualUsage") or {}).get("overall") or {}
    pu = data.get("planUsage") or data.get("plan_usage") or {}

    remaining = _num(plan.get("remaining"))
    if remaining is None:
        remaining = _num(overall.get("remaining"))
    if remaining is None:
        remaining = _num(pu.get("remaining"))

    limit = _num(plan.get("limit"))
    if limit is None:
        limit = _num(overall.get("limit"))
    if limit is None:
        limit = _num(pu.get("limit"))

    used = _num(plan.get("used"))
    if used is None:
        used = _num(overall.get("used"))
    included = _num(pu.get("includedSpend") or pu.get("included_spend"))
    if used is None:
        used = included
    if remaining is None and limit is not None and used is not None:
        remaining = max(0.0, limit - used)

    pct = _num(plan.get("totalPercentUsed"))
    if pct is None:
        pct = _num(pu.get("totalPercentUsed") or pu.get("total_percent_used"))
    if pct is None:
        pct = _num(plan.get("apiPercentUsed") or pu.get("apiPercentUsed"))

    auto_pct = _num(pu.get("autoPercentUsed") or pu.get("auto_percent_used") or plan.get("autoPercentUsed"))
    api_hint = ""
    if auto_pct is not None:
        auto_left = max(0, min(100, 100 - auto_pct))
        api_hint = f"Auto {int(round(auto_left))}%"

    if remaining is not None and limit and limit > 0:
        remain_pct = max(0, min(100, remaining / limit * 100))
        hint = api_hint or "本周期剩余"
        if limit >= 50:
            return _snap(remaining / 100, "USD", remain_pct, hint)
        return _snap(remaining, "次", remain_pct, hint)
    if remaining is not None:
        unit = "USD" if remaining >= 50 or (limit or 0) >= 50 else "次"
        amt = remaining / 100 if unit == "USD" else remaining
        return _snap(amt, unit, None, api_hint or "本周期剩余")
    if auto_pct is not None:
        auto_left = max(0.0, min(100.0, 100.0 - auto_pct))
        return _snap(auto_left, "%", auto_left, api_hint)
    if pct is not None:
        left = max(0, min(100, 100 - pct))
        return _snap(left, "%", left, f"已用 {round(pct)}%")
    if used is not None and limit and limit > 0:
        left = max(0.0, limit - used)
        unit = "USD" if limit >= 50 else "次"
        amt = left / 100 if unit == "USD" else left
        return _snap(amt, unit, max(0, min(100, left / limit * 100)), api_hint or "本周期剩余")
    return None


def fetch_cursor() -> dict:
    jar = _cookie_jar(["cursor.com", ".cursor.com"])
    try:
        res = _get("https://cursor.com/api/usage-summary", jar=jar, headers={"Accept": "application/json"})
        parsed = _parse_cursor(res.json() if res.content else None)
        if parsed:
            return parsed
        if res.status_code in (401, 403):
            pass
        else:
            res2 = _get(
                "https://cursor.com/api/dashboard/get-current-period-usage",
                jar=jar,
                method="POST",
                headers={"Content-Type": "application/json", "Origin": "https://cursor.com", "Accept": "application/json"},
                body={},
            )
            parsed = _parse_cursor(res2.json() if res2.content else None)
            if parsed:
                return parsed
    except Exception:
        pass
    token = _cursor_token()
    if not token:
        return _fail("请先登录 Cursor 或 cursor.com")
    try:
        res = requests.post(
            "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Connect-Protocol-Version": "1",
            },
            json={},
            timeout=TIMEOUT,
        )
        parsed = _parse_cursor(res.json() if res.content else None)
        if parsed:
            return parsed
        if res.status_code in (401, 403):
            return _fail("Cursor 登录已过期")
        return _fail("Cursor 接口结构变了")
    except Exception:
        return _fail("Cursor 请求失败")


def _walk(obj: Any, fn, depth=0):
    if not obj or not isinstance(obj, (dict, list)) or depth > 8:
        return
    fn(obj)
    if isinstance(obj, list):
        for x in obj:
            _walk(x, fn, depth + 1)
        return
    for v in obj.values():
        _walk(v, fn, depth + 1)


def _parse_chatgpt(data: dict | None) -> dict | None:
    if not isinstance(data, dict):
        return None
    rl = data.get("rate_limit")
    if isinstance(rl, dict):
        win = rl.get("primary_window") or rl.get("five_hour") or rl.get("five_hour_limit")
        if isinstance(win, dict) and win.get("used_percent") is not None:
            left = max(0, min(100, 100 - float(win["used_percent"])))
            hint = "5 小时窗口"
            sec = rl.get("secondary_window") or {}
            if isinstance(sec, dict) and sec.get("used_percent") is not None:
                hint = f"周额度剩 {round(100 - float(sec['used_percent']))}%"
            return _snap(left, "%", left, hint)
        if isinstance(win, dict) and win.get("percent_left") is not None:
            pl = _num(win.get("percent_left"))
            if pl is not None:
                return _snap(pl, "%", pl, "额度窗口")
    found = {}

    def hunt(node):
        if found or not isinstance(node, dict):
            return
        used = node.get("used_percent") or node.get("usedPercent") or node.get("percent_used")
        remaining = node.get("remaining") or node.get("remaining_messages") or node.get("percent_left")
        limit = node.get("limit") or node.get("message_cap") or node.get("max")
        u, r, l = _num(used), _num(remaining), _num(limit)
        if u is not None and u <= 100 and (l is None or l <= 100):
            found.update(_snap(max(0, 100 - u), "%", max(0, 100 - u), "剩余额度"))
        elif r is not None and l and l > 0:
            found.update(_snap(r / l * 100, "%", max(0, min(100, r / l * 100)), "剩余额度"))

    _walk(data, hunt)
    if found:
        return found
    cap = _num(data.get("message_cap"))
    if cap is not None:
        return _snap(cap, "条", None, "当前窗口")
    return None


def fetch_chatgpt() -> dict:
    jar = _cookie_jar(["chatgpt.com", ".chatgpt.com", "chat.openai.com", ".openai.com"])
    if jar is None:
        return _fail("请先在 Edge/Chrome 登录 ChatGPT")
    try:
        ses = _get("https://chatgpt.com/api/auth/session", jar=jar, headers={"Accept": "application/json"})
        data = ses.json() if ses.content else {}
        token = (data or {}).get("accessToken")
        if not token:
            return _fail("请先在浏览器登录 ChatGPT")
        account = (data or {}).get("account") or {}
        account_id = account.get("id") or account.get("account_id")
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if account_id:
            headers["ChatGPT-Account-Id"] = str(account_id)
        u = _get("https://chatgpt.com/backend-api/wham/usage", jar=jar, headers=headers)
        parsed = _parse_chatgpt(u.json() if u.content else None)
        if parsed:
            return parsed
        c = _get("https://chatgpt.com/backend-api/conversation_limit", jar=jar, headers=headers)
        parsed = _parse_chatgpt(c.json() if c.content else None)
        if parsed:
            return parsed
        return _fail("ChatGPT 额度接口不可用")
    except Exception:
        return _fail("ChatGPT 请求失败")


def _parse_gemini_html(html: str) -> dict | None:
    if not html:
        return None
    if re.search(r"Sign in|accounts\.google", html, re.I) and "gxu-" not in html:
        return None
    percents = [int(x) for x in re.findall(r"(\d+)\s*%", html)]
    if not percents:
        return None
    used = percents[0]
    remain = max(0, min(100, 100 - used))
    weekly = None
    if "week" in html.lower() or "周" in html:
        for p in percents[1:]:
            weekly = p
            break
    hint = f"周已用 {weekly}%" if weekly is not None else "今日额度"
    return _snap(remain, "%", remain, hint)


def fetch_google() -> dict:
    jar = _cookie_jar(["google.com", ".google.com", "gemini.google.com"])
    if jar is None:
        return _fail("请先在 Edge/Chrome 登录 Gemini")
    try:
        res = _get("https://gemini.google.com/usage?t=1", jar=jar, headers={"Accept": "text/html"})
        if res.status_code in (401, 403):
            return _fail("请先登录 Gemini")
        parsed = _parse_gemini_html(res.text or "")
        if parsed:
            return parsed
        if re.search(r"Sign in|登录", res.text or "", re.I):
            return _fail("请先登录 Gemini")
        return _fail("没读到 Gemini 用量页")
    except Exception:
        return _fail("Gemini 请求失败")


def fetch_deepseek(api_key: str) -> dict:
    key = (api_key or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return _fail("设置里填 DeepSeek Key")
    last = None
    for attempt in range(2):
        try:
            res = requests.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": "Bearer " + key},
                timeout=TIMEOUT,
            )
        except Exception as e:
            last = e
            if attempt == 0:
                continue
            return _fail("DeepSeek 请求失败")
        if res.status_code in (401, 403):
            return _fail("DeepSeek Key 无效")
        if res.status_code >= 500 and attempt == 0:
            continue
        if not res.ok:
            return _fail(f"DeepSeek HTTP {res.status_code}")
        try:
            data = res.json()
        except Exception:
            return _fail("DeepSeek 返回异常")
        info = None
        if isinstance(data, dict) and isinstance(data.get("balance_infos"), list) and data["balance_infos"]:
            info = data["balance_infos"][0]
        if not info or info.get("total_balance") is None:
            return _fail("DeepSeek 结构变了")
        total = _num(info.get("total_balance"))
        if total is None:
            return _fail("DeepSeek 余额异常")
        currency = str(info.get("currency") or "CNY")
        remain_pct = 100.0 if total > BROKE_PCT else max(0.0, total)
        hint = "点击刷新"
        if currency == "CNY":
            return _snap(total, "CNY", remain_pct, hint)
        return _snap(total, currency, remain_pct, hint)
    return _fail("DeepSeek 请求失败: " + str(last)[:80])


def json_get(obj: Any, path: str) -> Any:
    cur = obj
    if not path:
        return None
    cleaned = path.replace("[", ".").replace("]", "")
    for part in cleaned.split("."):
        if not part:
            continue
        if isinstance(cur, list) and part.isdigit():
            i = int(part)
            if i < 0 or i >= len(cur):
                return None
            cur = cur[i]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _bearer_json(url: str, key: str):
    res = requests.get(
        url,
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        timeout=TIMEOUT,
    )
    data = None
    try:
        data = res.json() if res.content else None
    except Exception:
        data = None
    return res.status_code, data


def fetch_api_money(url: str, key: str, paths: list[str], unit: str, label: str, currency_path: str = "") -> dict:
    if not (key or "").strip():
        return _fail(f"设置里填 {label} Key")
    try:
        status, data = _bearer_json(url, key.strip())
    except Exception:
        return _fail(f"{label} 请求失败")
    if status in (401, 403):
        return _fail(f"{label} Key 无效")
    if not data:
        return _fail(f"{label} 返回异常")
    val = None
    for p in paths:
        val = json_get(data, p)
        if val is not None:
            break
    n = _num(val)
    if n is None:
        return _fail(f"{label} 结构对不上")
    cur = unit
    if currency_path:
        c = json_get(data, currency_path)
        if c:
            cur = str(c)
    remain_pct = 100.0 if n > BROKE_PCT else max(0.0, n if cur != "%" else n)
    if cur == "%":
        remain_pct = max(0.0, min(100.0, n))
    return _snap(n, cur, remain_pct, "点击刷新")


PRESETS = [
    {
        "id": "deepseek",
        "short": "DS",
        "label": "DeepSeek",
        "url": "https://api.deepseek.com/user/balance",
        "paths": ["balance_infos.0.total_balance"],
        "unit": "CNY",
        "currency_path": "balance_infos.0.currency",
        "placeholder": "sk-...  platform.deepseek.com",
    },
    {
        "id": "openrouter",
        "short": "OR",
        "label": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/credits",
        "paths": [],
        "unit": "USD",
        "placeholder": "sk-or-...  openrouter.ai",
    },
    {
        "id": "openai",
        "short": "OpenAI",
        "label": "OpenAI API",
        "url": "",
        "paths": [],
        "unit": "USD",
        "placeholder": "sk-...  platform.openai.com（优先 Admin Key）",
    },
    {
        "id": "siliconflow",
        "short": "硅基",
        "label": "硅基流动",
        "url": "https://api.siliconflow.cn/v1/user/info",
        "paths": ["data.totalBalance", "data.balance", "data.chargeBalance"],
        "unit": "CNY",
        "placeholder": "sk-...  siliconflow.cn",
    },
    {
        "id": "moonshot",
        "short": "Kimi",
        "label": "Kimi 月之暗面",
        "url": "https://api.moonshot.cn/v1/users/me/balance",
        "paths": ["data.available_balance", "data.cash_balance", "available_balance"],
        "unit": "CNY",
        "placeholder": "sk-...  platform.moonshot.cn",
    },
]


def fetch_openrouter(key: str) -> dict:
    if not (key or "").strip():
        return _fail("设置里填 OpenRouter Key")
    key = key.strip()
    try:
        status, data = _bearer_json("https://openrouter.ai/api/v1/credits", key)
        if status not in (401, 403) and isinstance(data, dict):
            credits = _num(json_get(data, "data.total_credits"))
            usage = _num(json_get(data, "data.total_usage"))
            if credits is not None and usage is not None:
                left = max(0.0, credits - usage)
                pct = max(0.0, min(100.0, left / credits * 100)) if credits else 0.0
                return _snap(left, "USD", pct, "账户余额")
        status, data = _bearer_json("https://openrouter.ai/api/v1/key", key)
        if status in (401, 403):
            return _fail("OpenRouter Key 无效")
        left = _num(json_get(data, "data.limit_remaining"))
        limit = _num(json_get(data, "data.limit"))
        if left is None:
            return _fail("OpenRouter 结构对不上")
        pct = None
        if limit and limit > 0:
            pct = max(0.0, min(100.0, left / limit * 100))
        return _snap(left, "USD", pct if pct is not None else (100.0 if left > BROKE_PCT else left), "Key 剩余")
    except Exception:
        return _fail("OpenRouter 请求失败")


def _openai_admin_costs(api_key: str, days: int = 30) -> dict:
    """组织级 Admin Key（官方）：近 days 天 API 花费（USD）。"""
    end = int(time.time())
    start = end - days * 86400
    url = (
        "https://api.openai.com/v1/organization/costs"
        f"?start_time={start}&end_time={end}&bucket_width=1d"
    )
    try:
        r = _get(url, headers={"Authorization": f"Bearer {api_key}"})
    except Exception:
        return _fail("Admin 接口请求失败")
    if r.status_code != 200:
        return _fail(f"Admin 接口 {r.status_code}")
    data = r.json()
    total = 0.0
    for item in data.get("data") or []:
        for res in item.get("results") or []:
            amt = res.get("amount") or {}
            if str(amt.get("currency") or "usd").lower() != "usd":
                continue
            val = _num(amt.get("value"))
            if val is not None:
                total += val
    return _snap(total, "USD", None, f"近 {days} 天 API 花费")


def _openai_credit_grants(api_key: str) -> dict:
    """传统余额接口（非官方，随时可能失效）：可用余额 USD。"""
    url = "https://api.openai.com/v1/dashboard/billing/credit_grants"
    try:
        r = _get(url, headers={"Authorization": f"Bearer {api_key}"})
    except Exception:
        return _fail("余额接口请求失败")
    if r.status_code != 200:
        return _fail(f"余额接口 {r.status_code}")
    data = r.json()
    avail = _num(data.get("total_available"))
    if avail is None:
        return _fail("余额接口返回异常")
    return _snap(avail, "USD", None, "API 余额")


def fetch_openai(key: str) -> dict:
    """OpenAI API 账单：优先 Admin 官方接口（近 30 天花费），失败回退传统余额接口。"""
    if not (key or "").strip():
        return _fail("设置里填 OpenAI Key")
    key = key.strip()
    admin = _openai_admin_costs(key)
    if admin.get("ok"):
        return admin
    grants = _openai_credit_grants(key)
    if grants.get("ok"):
        return grants
    return _fail(f"{admin.get('error')}；{grants.get('error')}")


def fetch_custom(item: dict) -> dict:
    name = str(item.get("name") or "自定义")
    url = str(item.get("url") or "").strip()
    key = str(item.get("api_key") or "").strip()
    path = str(item.get("json_path") or "").strip()
    unit = str(item.get("unit") or "CNY")
    if not url or not path:
        return _fail(f"{name} 未填 URL/路径")
    if not key:
        try:
            res = requests.get(url, headers={"Accept": "application/json"}, timeout=TIMEOUT)
            data = res.json() if res.content else None
        except Exception:
            return _fail(f"{name} 请求失败")
        n = _num(json_get(data, path))
        if n is None:
            return _fail(f"{name} 结构对不上")
        pct = max(0.0, min(100.0, n)) if unit == "%" else (100.0 if n > BROKE_PCT else max(0.0, n))
        return _snap(n, unit, pct, "点击刷新")
    return fetch_api_money(url, key, [path], unit, name)


def get_api_key(conf: dict, pid: str) -> str:
    keys = conf.get("api_keys") if isinstance(conf.get("api_keys"), dict) else {}
    env_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "siliconflow": "SILICONFLOW_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
    }
    val = str(keys.get(pid) or "")
    if pid == "deepseek" and not val:
        val = str(conf.get("deepseek_api_key") or "")
    if not val:
        val = str(os.environ.get(env_map.get(pid, ""), "") or "")
    return val.strip()


FETCHERS = {
    "cursor": fetch_cursor,
    "chatgpt": fetch_chatgpt,
    "google": fetch_google,
}


def fetch_balance(provider: str, conf: dict | None = None) -> dict:
    conf = conf or {}
    if provider in FETCHERS:
        return FETCHERS[provider]()
    if provider == "deepseek":
        return fetch_deepseek(get_api_key(conf, "deepseek"))
    if provider == "openrouter":
        return fetch_openrouter(get_api_key(conf, "openrouter"))
    if provider == "openai":
        return fetch_openai(get_api_key(conf, "openai"))
    for preset in PRESETS:
        if preset["id"] == provider:
            return fetch_api_money(
                preset["url"],
                get_api_key(conf, provider),
                preset["paths"],
                preset["unit"],
                preset["label"],
                preset.get("currency_path") or "",
            )
    for item in conf.get("custom") or []:
        if isinstance(item, dict) and item.get("id") == provider:
            return fetch_custom(item)
    return _fail("未知平台")


def fmt_amount(snap: dict) -> str:
    if not snap or not snap.get("ok"):
        return "--"
    amount = snap.get("amount")
    if amount == float("inf"):
        return "∞"
    n = _num(amount)
    if n is None:
        return "--"
    unit = snap.get("unit") or ""
    if unit == "USD":
        return f"${n:.2f}"
    if unit == "CNY":
        return f"¥ {n:.2f}"
    if unit == "%":
        return f"{int(round(n))}%"
    if unit in ("次", "条"):
        return f"{int(round(n))}{unit}"
    if abs(n) >= 100:
        return f"{int(round(n))} {unit}".strip()
    return f"{n:.2f} {unit}".strip()
