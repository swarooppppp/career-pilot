"""Explicit HTTP or isolated headless Chrome transport for public career feeds."""
import atexit
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

_session = None


def browser_enabled():
    return os.environ.get("CAREER_PORTAL_TRANSPORT", "http") == "browser"


def close_browser():
    global _session
    if _session is not None:
        playwright, browser, context, page = _session
        _session = None
        try:
            browser.close()
        finally:
            playwright.stop()


def browser_page():
    global _session
    if _session is None:
        from playwright.sync_api import sync_playwright
        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context()
            page = context.new_page()
            context.new_cdp_session(page).send("Network.enable", {
                "maxTotalBufferSize": 100_000_000, "maxResourceBufferSize": 50_000_000})
            _session = playwright, browser, context, page
        except Exception:
            playwright.stop()
            raise
        atexit.register(close_browser)
    return _session[3]


def read(url, timeout):
    if not browser_enabled():
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout) as response:
            return response.read().decode("utf-8")
    page = browser_page()
    response = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
    if response is None or not response.ok:
        raise RuntimeError(f"Career portal returned HTTP {response.status if response else 'unknown'} for {url}")
    try:
        return response.text()
    except Exception:
        if "json" in response.headers.get("content-type", ""):
            pre = page.locator("pre")
            return pre.inner_text() if pre.count() == 1 else page.locator("body").inner_text()
        return page.content()


def request_json(url, payload, timeout):
    if payload is None:
        return json.loads(read(url, timeout))
    if not browser_enabled():
        request = Request(url, data=json.dumps(payload).encode(), headers={
            "User-Agent": "Mozilla/5.0", "Accept": "application/json", "Content-Type": "application/json"})
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    # APIRequestContext uses Node networking, which can fail while Chrome's
    # own network stack succeeds. Make the POST in a same-origin page instead.
    page = browser_page()
    parsed = urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if urlsplit(page.url).netloc != parsed.netloc:
        parts = parsed.path.strip("/").split("/")
        landing = origin + "/" + parts[3] if parts[:2] == ["wday", "cxs"] and len(parts) > 3 else origin
        landed = page.goto(landing, wait_until="domcontentloaded", timeout=timeout * 1000)
        if parts[:2] == ["wday", "cxs"] and urlsplit(page.url).netloc != parsed.netloc:
            raise RuntimeError(f"Career portal redirected to unavailable host {page.url} (HTTP {landed.status if landed else 'unknown'})")
    response = page.evaluate("""async ({url, payload, timeout}) => {
        const response = await fetch(url, {method: 'POST',
            headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
            body: JSON.stringify(payload), signal: AbortSignal.timeout(timeout * 1000)});
        return {status: response.status, body: await response.text()};
    }""", {"url": url, "payload": payload, "timeout": timeout})
    if not 200 <= response["status"] < 300:
        raise RuntimeError(f"Career portal returned HTTP {response['status']} for {url}")
    return json.loads(response["body"])
