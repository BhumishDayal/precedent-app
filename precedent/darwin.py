"""Darwin step after a "swap" decision: ask Darwin's agent search how to file the warranty return.

POST https://api.darwin.so/api/v3/search; status is completed | needs_input | no_match.
Works anonymously when DARWIN_API_KEY is empty. Only a dry run (DIAL_API_KEY empty) skips the network.
The last good response per model is cached in STATE_DIR/darwin_cache.json and is used (marked "cached") if a live
call fails. Every outcome becomes a row in STATE_DIR/actions.jsonl (sponsor "darwin"); a failure is never silent.

CLI:  python -m precedent.darwin time ["MODEL"]   # time one real search
"""
import json
import logging
import os
import sys
import threading
import time
import urllib.parse

import httpx

from precedent.actions import log_action
from precedent.config import DARWIN_API_KEY, DATA, DIAL_API_KEY, STATE_DIR
from precedent.decisions import now

log = logging.getLogger(__name__)
URL = os.getenv("DARWIN_SEARCH_URL", "https://api.darwin.so/api/v3/search")
CACHE = os.path.join(STATE_DIR, "darwin_cache.json")
TIMEOUT = 8
BACKOFF = (1, 2, 4)  # seconds between the 3 attempts
TOTAL_CAP = 15       # seconds for the whole search, retries included
_cache_lock = threading.Lock()  # a swap runs after_swap and find_part in parallel; both rewrite the cache file


def search(serial: str, model: str) -> tuple[dict, float]:
    """Returns (response, seconds). Read-only, so retries are safe: up to 3 attempts on 5xx / timeout / network error,
    backoff 1 s, 2 s, within a 15 s total cap (Darwin 500s intermittently). Raises the last error."""
    body = {"query": f"file a warranty return for a {model} enterprise hard drive", "maxResults": 3,
            "context": [{"type": "custom", "data": {"serial": serial, "model": model}}]}
    headers = {"Authorization": f"Bearer {DARWIN_API_KEY}"} if DARWIN_API_KEY else {}
    t0, err = time.time(), None
    for i in range(3):
        left = TOTAL_CAP - (time.time() - t0)
        if left < 1:
            break
        try:
            r = httpx.post(URL, json=body, headers=headers, timeout=min(TIMEOUT, left))
            if r.status_code < 500:
                r.raise_for_status()
                return r.json(), round(time.time() - t0, 1)
            err = httpx.HTTPStatusError(f"{r.status_code} {r.reason_phrase}", request=r.request, response=r)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            err = e
        log.warning("search attempt %d failed: %r", i + 1, err)
        if i < 2 and time.time() - t0 + BACKOFF[i] < TOTAL_CAP:
            time.sleep(BACKOFF[i])
    raise err or httpx.TimeoutException("Darwin search exceeded the 15 s cap")


def _cache_get(model: str) -> dict | None:
    try:
        with open(CACHE) as f:
            return json.load(f).get(model)
    except (OSError, ValueError):
        return None


def _cache_any() -> tuple[str, dict] | None:
    """The most recent cached search for any model (fallback when this model was never searched)."""
    try:
        with open(CACHE) as f:
            cache = json.load(f)
    except (OSError, ValueError):
        return None
    return max(cache.items(), key=lambda kv: kv[1].get("ts", "")) if cache else None


def prewarm() -> None:
    """At server startup: one search for the pinned drive's model, so a later Darwin outage has a cached answer."""
    try:
        with open(os.path.join(DATA, "samples", "demo_drive.json")) as f:
            d = json.load(f)
        res, secs = search(d["serial"], d["model"])
        _cache_put(d["model"], res, secs)
        log.info("prewarmed %s: %s in %s s", d["model"], res.get("status"), secs)
    except Exception as e:
        log.warning("prewarm failed (falls back to any cached model): %r", e)


def _cache_put(model: str, res: dict, secs: float) -> None:
    with _cache_lock:
        try:
            with open(CACHE) as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {}
        cache[model] = {"ts": now(), "seconds": secs, "res": res}
        try:
            with open(CACHE, "w") as f:
                json.dump(cache, f)
        except OSError as e:  # a cache miss later is fine; losing the live result now is not
            log.warning("could not write %s: %s", CACHE, e)


def summarize(res: dict) -> str:
    """One plain-ASCII SMS line for the result."""
    r = res.get("response") or {}
    agents = r.get("agents") or []
    top = f" Top match: {agents[0].get('name')} ({agents[0].get('readiness')})." if agents else ""
    if res.get("status") == "needs_input":
        text = f"Darwin needs one thing to file the warranty return: {r.get('question')}{top}"
    elif res.get("status") == "no_match":
        text = f"Darwin found no agent for the warranty return: {r.get('noMatchReason')}"
    else:
        text = f"Darwin: {r.get('overview') or 'warranty return path found.'}{top}"
    return text.encode("ascii", "replace").decode()[:600]


def stage_line(res: dict) -> str:
    r = res.get("response") or {}
    agents = r.get("agents") or []
    top = f"{agents[0].get('name')} ({agents[0].get('readiness')})" if agents else "no agent"
    if res.get("status") == "needs_input":
        out = f"gap: {r.get('question')} Top match {top}"
    elif res.get("status") == "no_match":
        out = f"gap: {r.get('noMatchReason')}"
    else:
        out = top
    return f"Darwin searched agents for a warranty return -> {out}"


def _probe_mcp(url: str) -> str:
    """Verify an MCP route: initialize + tools/list (no provider tool is called blindly)."""
    h = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "precedent", "version": "1"}}}
    with httpx.Client(timeout=5) as c:
        r = c.post(url, json=init, headers=h)
        if r.status_code >= 400:
            return f"initialize -> HTTP {r.status_code}"
        sid = r.headers.get("mcp-session-id")
        r = c.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers={**h, **({"mcp-session-id": sid} if sid else {})})
        try:
            tools = [t["name"] for t in r.json()["result"]["tools"]]
            return f"{len(tools)} tools listed ({', '.join(tools[:4])})"
        except Exception:
            return f"tools/list -> HTTP {r.status_code}"


def contact_agents(alert: dict, res: dict, max_agents: int = 2, budget: float = 12.0) -> list:
    """Documented fallback when Act can't start (darwin.so/docs/search/using-results): contact a returned agent
    directly ONLY via a verified, published route; never invent an endpoint. Each attempt -> an action row
    (sponsor "darwin_agent"). Runs in the swap's background thread; never blocks the decision."""
    aid, rows, t0 = alert["alert_id"], [], time.time()
    agents = ((res.get("response") or {}).get("agents") or [])[:max_agents]
    if not agents:
        return [log_action(aid, "darwin_agent", "none",
                           f"Darwin -> no candidate agent to contact ({res.get('status')}); the gap stays open")]
    for a in agents:
        name = a.get("name") or a.get("agentSlug") or "agent"
        if a.get("canStartThread"):
            rows.append(log_action(aid, "darwin_agent", "act_available",
                                   f"Darwin -> {name}: Act route available, but Act is disabled for now; using direct contact"))
        methods = a.get("connectionMethods") or []
        if not methods:
            how = "connection prompt ready for a capable AI client" if a.get("connectionPrompt") else "nothing to contact"
            rows.append(log_action(aid, "darwin_agent", "no_route",
                                   f"Darwin -> {name}: no published connection method (readiness {a.get('readiness')}); {how}",
                                   {"connectionPrompt": (a.get("connectionPrompt") or "")[:2000]}))
            continue
        for m in methods:
            if time.time() - t0 > budget:
                return rows
            proto = str(m.get("protocol") or m.get("type") or m.get("kind") or "http").lower()
            url, status = m.get("endpointUrl"), m.get("endpointStatus")
            if not url or status == "not_published":
                rows.append(log_action(aid, "darwin_agent", "no_route",
                                       f"Darwin -> {name} via {proto}: endpoint {status or 'unknown'}; see {m.get('documentationUrl') or 'provider docs'}"))
                continue
            if urllib.parse.urlsplit(str(url)).scheme != "https":  # a third party picked this URL: no plain-http targets
                rows.append(log_action(aid, "darwin_agent", "no_route", f"Darwin -> {name} via {proto}: endpoint not https, skipped"))
                continue
            try:
                result = _probe_mcp(url) if "mcp" in proto and "web" not in proto else f"HTTP {httpx.get(url, timeout=5).status_code}"
                rows.append(log_action(aid, "darwin_agent", "contacted", f"Darwin -> contacted {name} via {proto}: {result}"))
            except Exception as e:
                rows.append(log_action(aid, "darwin_agent", "error", f"Darwin -> {name} via {proto}: unreachable ({str(e)[:60]})"))
    return rows


def find_part(alert: dict, send=None) -> dict:
    """After "replace": ask Darwin for agents that can source the replacement part. Logs one action row
    (sponsor darwin_part) and texts the technician one line. Cached per model; dry-run without a Dial key."""
    from precedent import tech
    aid, model = alert["alert_id"], alert["model"]
    if not DIAL_API_KEY:
        return log_action(aid, "darwin_part", "dry-run", f"Would ask Darwin for a replacement {model} (practice mode).")
    key = f"part:{model}"
    try:
        body = {"query": f"find the replacement part for a {model} enterprise hard drive (find a supplier)", "maxResults": 5}
        headers = {"Authorization": f"Bearer {DARWIN_API_KEY}"} if DARWIN_API_KEY else {}
        t0 = time.time()
        r = httpx.post(URL, json=body, headers=headers, timeout=12)
        r.raise_for_status()
        res = r.json()
        _cache_put(key, res, round(time.time() - t0, 1))
    except (httpx.HTTPError, ValueError) as e:
        log.warning("part search for %s failed: %r", model, e)
        hit = _cache_get(key)
        if not hit:
            return log_action(aid, "darwin_part", "error", f"Couldn't reach Darwin to find a replacement {model} right now.")
        res = hit["res"]
    names = [a.get("name") for a in ((res.get("response") or {}).get("agents") or []) if a.get("name")]
    if names:
        line = (f"Darwin found {len(names)} agent{'s' if len(names) != 1 else ''} that can source a replacement for "
                f"{model}: {', '.join(names)}.")
    else:
        line = f"Darwin found no agent that can source a replacement {model} yet."
    row = log_action(aid, "darwin_part", res.get("status") or "?", line, {"agents": names, "searchId": res.get("searchId")})
    if send and names:
        try:
            send(tech.TECH_TARGET or alert.get("phone"), f"Replacement part: Darwin found {len(names)} agent(s): {', '.join(names[:2])}.")
        except Exception as e:
            log.warning("part text failed: %s", e)
    return row


def candidates(res: dict) -> int:
    return len((res.get("response") or {}).get("agents") or [])


def after_swap(alert: dict, send) -> dict:
    """Search (live, else cached), log one action row, text the summary via send(phone, body). Never raises."""
    aid, model = alert["alert_id"], alert["model"]
    if not DIAL_API_KEY:  # rehearsal / smoke: no network
        return log_action(aid, "darwin", "dry-run", f"Darwin (dry-run): would search agents for a {model} warranty return")
    cached = None  # None | "cached" | "cached (similar model)"
    try:
        res, secs = search(alert["serial"], model)
        _cache_put(model, res, secs)
    except Exception as e:
        log.warning("live search failed after retries: %r", e)
        hit, other = _cache_get(model), None
        if hit is None and (anyhit := _cache_any()):
            other, hit = anyhit
        if hit is None:
            why = ("timed out" if isinstance(e, httpx.TimeoutException) else str(e)[:60]) or "unavailable"
            return log_action(aid, "darwin", "error",
                              f"Darwin searched agents for a warranty return -> search unavailable after 3 attempts "
                              f"({why}); no cached result yet", {"error": repr(e)[:300]})
        res, secs = hit["res"], hit["seconds"]
        cached = "cached" if other is None else "cached (similar model)"
    text = summarize(res)
    if cached is None:
        line = stage_line(res) + f" ({candidates(res)} agent{'' if candidates(res) == 1 else 's'} in {secs} s)"
    elif other is None:
        line = stage_line(res) + f" (cached {secs} s result; live search failed)"
    else:
        line = stage_line(res) + f" (cached result for similar model {other}; live search failed)"
    row = log_action(aid, "darwin", "cached" if cached else res.get("status"), line,
                     {"text": text, "searchId": res.get("searchId"), "seconds": secs, "candidates": candidates(res),
                      "cached": cached, "serial": alert["serial"]})
    try:
        send(alert["phone"], text)
    except Exception as e:
        log.warning("text failed: %s", e)
    try:
        contact_agents(alert, res)
    except Exception:
        log.exception("contacting agents failed")
    return row


if __name__ == "__main__":
    if sys.argv[1:2] == ["time"]:
        m = sys.argv[2] if len(sys.argv) > 2 else "TOSHIBA MG10ACA20TE"
        res, secs = search("44H0B01BV4MJ", m)
        _cache_put(m, res, secs)
        print(f"status={res.get('status')} candidates={candidates(res)} seconds={secs}")
        print(stage_line(res))
    else:
        print(__doc__)
