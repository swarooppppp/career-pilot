#!/usr/bin/env python3
"""Cloudera's official Workday source using the shared India/engineering adapter."""
import sys

import fetch_workday_india_jobs as workday
import portal_http

CAREERS_URL = "https://cloudera.wd5.myworkdayjobs.com/External_Career"
API_ROOT = "https://cloudera.wd5.myworkdayjobs.com/wday/cxs/cloudera/External_Career/"


class BrowserTransport:
    """Capture native page requests; never issue a synthetic API request."""

    def __init__(self):
        self.page = None

    def __call__(self, url, payload, timeout):
        if not url.startswith(API_ROOT):
            raise ValueError("Cloudera transport only accepts its official careers API")
        from urllib.parse import urlencode
        import re
        if self.page is None:
            self.page = portal_http.browser_page()
        if payload is None:
            target = CAREERS_URL.replace(".com/", ".com/en-US/") + url[len(API_ROOT) - 1:]
            with self.page.expect_response(lambda r: r.url == url and r.request.method == "GET", timeout=timeout * 1000) as pending:
                navigation = self.page.goto(target, wait_until="domcontentloaded", timeout=timeout * 1000)
                self.check_navigation(navigation)
        else:
            facets = payload.get("appliedFacets", {})
            def matches(response):
                if response.url != API_ROOT + "jobs" or response.request.method != "POST":
                    return False
                actual = response.request.post_data_json
                return (actual.get("appliedFacets", {}) == facets
                        and actual.get("offset", 0) == payload.get("offset", 0)
                        and actual.get("searchText", "") == payload.get("searchText", ""))
            with self.page.expect_response(matches, timeout=timeout * 1000) as pending:
                if payload.get("offset", 0):
                    self.page.get_by_role("button", name=re.compile(r"^next", re.I)).click(timeout=timeout * 1000)
                else:
                    query = dict(facets)
                    if payload.get("searchText"):
                        query["q"] = payload["searchText"]
                    target = CAREERS_URL.replace(".com/", ".com/en-US/")
                    if query:
                        target += "?" + urlencode(query, doseq=True)
                    navigation = self.page.goto(target, wait_until="domcontentloaded", timeout=timeout * 1000)
                    self.check_navigation(navigation)
        response = pending.value
        if not response.ok:
            raise RuntimeError(f"Cloudera native browser request returned HTTP {response.status}; Retry-After={response.headers.get('retry-after', 'unspecified')}")
        return response.json()

    @staticmethod
    def check_navigation(response):
        if response is None or not response.ok:
            status = response.status if response else "unknown"
            retry = response.headers.get("retry-after", "unspecified") if response else "unspecified"
            raise RuntimeError(f"Cloudera careers page returned HTTP {status}; Retry-After={retry}")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == CAREERS_URL:
        args.pop(0)
    try:
        return workday.main([CAREERS_URL, "--company", "Cloudera", "--search-text", "", *args], requester=BrowserTransport())
    finally:
        portal_http.close_browser()


if __name__ == "__main__":
    main()
