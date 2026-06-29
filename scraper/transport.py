from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import requests

from config import (
    PLAYWRIGHT_ESCALATE_ON_BLOCK,
    PLAYWRIGHT_ENABLED,
    PLAYWRIGHT_HEADLESS,
    PLAYWRIGHT_PROXY_URL,
    PLAYWRIGHT_TIMEOUT_MS,
    PLAYWRIGHT_USE_PROXY,
    PLAYWRIGHT_USE_STEALTH,
    PLAYWRIGHT_WAIT_UNTIL,
    REQUEST_TIMEOUT,
    USER_AGENT,
)


log = logging.getLogger(__name__)


class FetchStrategy(str, Enum):
    REQUESTS = "requests"
    PLAYWRIGHT = "playwright"
    PROXY_PLAYWRIGHT = "proxy+playwright"


@dataclass
class FetchResponse:
    url: str
    status_code: int
    text: str
    headers: dict[str, str]
    strategy: FetchStrategy
    block_reason: str | None = None

    def json(self) -> Any:
        return json.loads(self.text or "")


_BLOCK_MARKERS = (
    "just a moment",
    "attention required",
    "enable javascript and cookies to continue",
    "__cf_chl_",
    "cf-browser-verification",
    "cloudflare",
    "captcha",
    "access denied",
    "x-amzn-waf-action",
    "request blocked",
    "not authorized for pcsx",
)


def detect_block(status_code: int, text: str | None, headers: dict[str, str] | None = None) -> str | None:
    if status_code in (403, 429):
        return f"http_{status_code}"
    headers = headers or {}
    header_blob = " ".join(f"{k}:{v}" for k, v in headers.items()).lower()
    text_blob = (text or "").lower()
    if "x-amzn-waf-action" in header_blob:
        return "aws_waf"
    for marker in _BLOCK_MARKERS:
        if marker in text_blob or marker in header_blob:
            return marker
    return None


def _browser_proxy(strategy: FetchStrategy) -> dict[str, str] | None:
    if not PLAYWRIGHT_USE_PROXY:
        return None
    if strategy != FetchStrategy.PROXY_PLAYWRIGHT:
        return None
    if not PLAYWRIGHT_PROXY_URL:
        return None
    return {"server": PLAYWRIGHT_PROXY_URL}


def _apply_stealth(page) -> None:
    if not PLAYWRIGHT_USE_STEALTH:
        return
    try:
        from playwright_stealth import Stealth
    except Exception:
        return
    try:
        Stealth().apply_stealth_sync(page)
    except Exception:
        log.exception("Failed to apply playwright stealth")


def _playwright_available() -> bool:
    if not PLAYWRIGHT_ENABLED:
        return False
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


def next_strategy(current: FetchStrategy) -> FetchStrategy | None:
    if not PLAYWRIGHT_ESCALATE_ON_BLOCK:
        return None
    if current == FetchStrategy.REQUESTS:
        return FetchStrategy.PLAYWRIGHT if _playwright_available() else None
    if current == FetchStrategy.PLAYWRIGHT and PLAYWRIGHT_USE_PROXY and PLAYWRIGHT_PROXY_URL and _playwright_available():
        return FetchStrategy.PROXY_PLAYWRIGHT
    return None


def _normalize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    base = {"User-Agent": USER_AGENT}
    if headers:
        base.update(headers)
    return base


def _requests_fetch(
    url: str,
    *,
    method: str,
    headers: dict[str, str] | None = None,
    timeout: int | float = REQUEST_TIMEOUT,
    **kwargs,
) -> FetchResponse:
    merged = _normalize_headers(headers)
    resp = requests.request(
        method=method.upper(),
        url=url,
        headers=merged,
        timeout=timeout,
        **kwargs,
    )
    text = resp.text if resp.text is not None else ""
    hdrs = {k.lower(): v for k, v in resp.headers.items()}
    return FetchResponse(
        url=str(resp.url),
        status_code=resp.status_code,
        text=text,
        headers=hdrs,
        strategy=FetchStrategy.REQUESTS,
        block_reason=detect_block(resp.status_code, text, hdrs),
    )


def _playwright_fetch_html(
    url: str,
    *,
    strategy: FetchStrategy,
    headers: dict[str, str] | None = None,
    referer_url: str | None = None,
) -> FetchResponse:
    from playwright.sync_api import sync_playwright

    hdrs = _normalize_headers(headers)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=PLAYWRIGHT_HEADLESS,
            proxy=_browser_proxy(strategy),
        )
        context = browser.new_context(
            user_agent=hdrs.get("User-Agent", USER_AGENT),
            extra_http_headers={k: v for k, v in hdrs.items() if k.lower() != "user-agent"},
        )
        page = context.new_page()
        _apply_stealth(page)
        if referer_url and referer_url != url:
            try:
                page.goto(referer_url, wait_until=PLAYWRIGHT_WAIT_UNTIL, timeout=PLAYWRIGHT_TIMEOUT_MS)
            except Exception:
                pass
        response = page.goto(url, wait_until=PLAYWRIGHT_WAIT_UNTIL, timeout=PLAYWRIGHT_TIMEOUT_MS)
        text = page.content()
        final_url = page.url
        status = response.status if response is not None else 0
        out = FetchResponse(
            url=final_url,
            status_code=status,
            text=text,
            headers={},
            strategy=strategy,
        )
        out.block_reason = detect_block(out.status_code, out.text, out.headers)
        context.close()
        browser.close()
        return out


def _playwright_fetch_json(
    url: str,
    *,
    strategy: FetchStrategy,
    headers: dict[str, str] | None = None,
    referer_url: str | None = None,
    method: str = "GET",
    json_payload: Any = None,
) -> FetchResponse:
    from playwright.sync_api import sync_playwright

    hdrs = _normalize_headers(headers)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=PLAYWRIGHT_HEADLESS,
            proxy=_browser_proxy(strategy),
        )
        context = browser.new_context(
            user_agent=hdrs.get("User-Agent", USER_AGENT),
            extra_http_headers={k: v for k, v in hdrs.items() if k.lower() != "user-agent"},
        )
        page = context.new_page()
        _apply_stealth(page)
        if referer_url:
            try:
                page.goto(referer_url, wait_until=PLAYWRIGHT_WAIT_UNTIL, timeout=PLAYWRIGHT_TIMEOUT_MS)
            except Exception:
                pass
        api = context.request
        method = method.upper()
        if method == "POST":
            resp = api.post(url, data=json_payload if isinstance(json_payload, str) else None, json=json_payload if isinstance(json_payload, (dict, list)) else None, headers=hdrs)
        else:
            resp = api.get(url, headers=hdrs)
        text = resp.text()
        status = resp.status
        final_url = resp.url
        out = FetchResponse(
            url=final_url,
            status_code=status,
            text=text,
            headers={},
            strategy=strategy,
        )
        out.block_reason = detect_block(out.status_code, out.text, out.headers)
        context.close()
        browser.close()
        return out


def fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    expect: str = "html",
    referer_url: str | None = None,
    strategy: FetchStrategy = FetchStrategy.REQUESTS,
    auto_escalate: bool = True,
    timeout: int | float = REQUEST_TIMEOUT,
    json_payload: Any = None,
    **kwargs,
) -> FetchResponse:
    method = method.upper()
    current = strategy
    while True:
        try:
            if current == FetchStrategy.REQUESTS:
                if method == "POST":
                    resp = _requests_fetch(
                        url,
                        method=method,
                        headers=headers,
                        timeout=timeout,
                        json=json_payload if isinstance(json_payload, (dict, list)) else None,
                        data=json_payload if isinstance(json_payload, str) else None,
                        **kwargs,
                    )
                else:
                    resp = _requests_fetch(url, method=method, headers=headers, timeout=timeout, **kwargs)
            elif expect == "json":
                resp = _playwright_fetch_json(
                    url,
                    strategy=current,
                    headers=headers,
                    referer_url=referer_url,
                    method=method,
                    json_payload=json_payload,
                )
            else:
                resp = _playwright_fetch_html(
                    url,
                    strategy=current,
                    headers=headers,
                    referer_url=referer_url,
                )
        except Exception as exc:
            log.warning("Fetch failed for %s via %s: %s", url, current.value, type(exc).__name__)
            resp = FetchResponse(
                url=url,
                status_code=0,
                text="",
                headers={},
                strategy=current,
                block_reason=f"exception:{type(exc).__name__}",
            )
        if not auto_escalate or not resp.block_reason:
            return resp
        nxt = next_strategy(current)
        if nxt is None:
            return resp
        log.info("Escalating fetch for %s from %s to %s due to %s", url, current.value, nxt.value, resp.block_reason)
        current = nxt


def capture_json_via_page_fetch(
    page_url: str,
    *,
    trigger_urls: list[str],
    route_glob: str,
    headers: dict[str, str] | None = None,
    strategy: FetchStrategy = FetchStrategy.PLAYWRIGHT,
) -> list[FetchResponse]:
    if not _playwright_available():
        return []
    from playwright.sync_api import sync_playwright

    hdrs = _normalize_headers(headers)
    captured: list[FetchResponse] = []
    intercepted_urls: set[str] = set()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=PLAYWRIGHT_HEADLESS,
            proxy=_browser_proxy(strategy),
        )
        context = browser.new_context(
            user_agent=hdrs.get("User-Agent", USER_AGENT),
            extra_http_headers={k: v for k, v in hdrs.items() if k.lower() != "user-agent"},
        )
        page = context.new_page()
        _apply_stealth(page)

        def handle_route(route) -> None:
            intercepted_urls.add(route.request.url)
            route.continue_()

        page.route(route_glob, handle_route)
        page.goto(page_url, wait_until=PLAYWRIGHT_WAIT_UNTIL, timeout=PLAYWRIGHT_TIMEOUT_MS)

        for trigger_url in trigger_urls:
            try:
                result = page.evaluate(
                    """async ({url, headers}) => {
                        const response = await fetch(url, {
                            method: 'GET',
                            headers,
                            credentials: 'include'
                        });
                        return {
                            url: response.url,
                            status: response.status,
                            text: await response.text()
                        };
                    }""",
                    {"url": trigger_url, "headers": hdrs},
                )
            except Exception as exc:
                log.warning("Playwright route fetch failed for %s: %s", trigger_url, type(exc).__name__)
                continue
            response = FetchResponse(
                url=result.get("url") or trigger_url,
                status_code=int(result.get("status") or 0),
                text=result.get("text") or "",
                headers={},
                strategy=strategy,
            )
            response.block_reason = detect_block(response.status_code, response.text, response.headers)
            captured.append(response)

        context.close()
        browser.close()

    if intercepted_urls:
        log.info("Intercepted %d browser API call(s) via %s", len(intercepted_urls), route_glob)
    return captured
