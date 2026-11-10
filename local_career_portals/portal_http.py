"""Explicit HTTP or isolated headless Chrome transport for public career feeds."""
import atexit
from io import BytesIO
from email.message import Message
from urllib.error import HTTPError
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


class BrowserResponse(BytesIO):
    """Small urllib-compatible response for existing portal parsers."""
    def __init__(self, body, status, url, headers):
        super().__init__(body)
        self.status = self.code = status
        self.url = url
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key] = value

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url

    def info(self):
        return self.headers


def browser_urlopen(request, data=None, timeout=60, **kwargs):
    """Send legacy urllib requests through Chrome, retaining parser/error contracts.

    Chrome performs the network I/O; Playwright's Node APIRequestContext is not
    used. A process-local browser/context is reused until the adapter exits.
    """
    url = request.full_url if isinstance(request, Request) else str(request)
    payload = data if data is not None else getattr(request, "data", None)
    method = request.get_method() if isinstance(request, Request) else ("POST" if payload is not None else "GET")
    headers = dict(request.header_items()) if isinstance(request, Request) else {}
    headers = {key: value for key, value in headers.items() if key.lower() not in {"user-agent", "host", "content-length", "accept-encoding"}}
    seconds = min(float(timeout) if isinstance(timeout, (int, float)) and timeout > 0 else 60, 60)
    page = browser_page()
    if method == "GET" and payload is None:
        page.set_extra_http_headers(headers)
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=seconds * 1000)
            if response is None:
                raise RuntimeError(f"Career portal returned no response for {url}")
            status, response_headers, final_url = response.status, response.headers, response.url
            try:
                body = response.body()
            except Exception:
                if "json" in response_headers.get("content-type", ""):
                    pre = page.locator("pre")
                    body = (pre.inner_text() if pre.count() == 1 else page.locator("body").inner_text()).encode()
                else:
                    body = page.content().encode()
        finally:
            page.set_extra_http_headers({})
    else:
        parsed = urlsplit(url)
        if urlsplit(page.url).netloc != parsed.netloc:
            parts = parsed.path.strip("/").split("/")
            workday = parts[:2] == ["wday", "cxs"] and len(parts) > 3
            landing = f"{parsed.scheme}://{parsed.netloc}" + ("/" + parts[3] if workday else "")
            page.goto(landing, wait_until="domcontentloaded", timeout=seconds * 1000)
            if workday and urlsplit(page.url).netloc != parsed.netloc:
                raise RuntimeError(f"Career portal redirected to unavailable host {page.url}")
        result = page.evaluate("""async ({url, method, headers, body, seconds}) => {
            const response = await fetch(url, {method, headers, body,
                signal: AbortSignal.timeout(seconds * 1000)});
            return {status: response.status, url: response.url,
                headers: Object.fromEntries(response.headers.entries()), body: await response.text()};
        }""", {"url": url, "method": method, "headers": headers,
                "body": payload.decode("utf-8") if isinstance(payload, bytes) else payload, "seconds": seconds})
        status, response_headers, final_url = result["status"], result["headers"], result["url"]
        body = result["body"].encode()
    response = BrowserResponse(body, status, final_url, response_headers)
    if status >= 400:
        raise HTTPError(final_url, status, f"HTTP {status}", response.headers, response)
    return response
