import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

DIRECTORY = Path(__file__).resolve().parents[1] / 'local_career_portals'
sys.path.insert(0, str(DIRECTORY))
import portal_http
import run


class BrowserTransportTests(unittest.TestCase):
    def page(self, status=200, body=b'{"jobs": []}'):
        response = Mock(status=status, headers={'content-type': 'application/json; charset=utf-8', 'retry-after': '30'}, url='https://example.test/jobs')
        response.body.return_value = body
        page = Mock(url='https://example.test/')
        page.goto.return_value = response
        return page

    def test_urllib_parsers_receive_bytes_headers_and_status(self):
        page = self.page()
        with patch.object(portal_http, 'browser_page', return_value=page):
            with portal_http.browser_urlopen(Request('https://example.test/jobs'), timeout=20) as response:
                self.assertEqual(json.load(response), {'jobs': []})
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_charset(), 'utf-8')
                self.assertEqual(response.geturl(), 'https://example.test/jobs')
            portal_http.browser_urlopen('https://example.test/jobs')
        self.assertEqual(page.goto.call_count, 2)

    def test_429_preserves_retry_after_and_does_not_retry(self):
        page = self.page(status=429)
        with patch.object(portal_http, 'browser_page', return_value=page):
            with self.assertRaises(HTTPError) as error:
                portal_http.browser_urlopen('https://example.test/jobs')
        self.assertEqual(error.exception.code, 429)
        self.assertEqual(error.exception.headers['retry-after'], '30')
        self.assertEqual(page.goto.call_count, 1)

    def test_post_payload_stays_in_browser_network_stack(self):
        page = self.page()
        page.evaluate.return_value = {'status': 200, 'headers': {'content-type': 'application/json'}, 'url': 'https://example.test/search', 'body': '{"total": 3}'}
        request = Request('https://example.test/search', data=b'{"country":"India"}', headers={'Content-Type': 'application/json'})
        with patch.object(portal_http, 'browser_page', return_value=page):
            with portal_http.browser_urlopen(request) as response:
                self.assertEqual(json.load(response), {'total': 3})
        arguments = page.evaluate.call_args.args[1]
        self.assertEqual(arguments['method'], 'POST')
        self.assertEqual(json.loads(arguments['body']), {'country': 'India'})
        page.goto.assert_not_called()

    def test_runner_supplies_browser_transport_and_import_path(self):
        environment = run.environment({'slug': 'rubrik'})
        self.assertEqual(environment['CAREER_PORTAL_TRANSPORT'], 'browser')
        self.assertIn(str(DIRECTORY), environment['PYTHONPATH'])
        registry = json.loads((DIRECTORY / 'companies.json').read_text())
        for company in registry['companies']:
            if company['status'] in {'reuse', 'implemented'}:
                self.assertEqual(run.environment(company)['CAREER_PORTAL_TRANSPORT'], 'browser')

    def test_workday_post_opens_career_site_instead_of_empty_tenant_root(self):
        page = self.page()
        page.url = "about:blank"
        def navigate(url, **kwargs):
            page.url = url
            return Mock(status=200)
        page.goto.side_effect = navigate
        page.evaluate.return_value = {"status": 200, "headers": {}, "url": "https://tenant.myworkdayjobs.com/wday/cxs/tenant/Careers/jobs", "body": "{}"}
        request = Request("https://tenant.myworkdayjobs.com/wday/cxs/tenant/Careers/jobs", data=b"{}")
        with patch.object(portal_http, "browser_page", return_value=page):
            portal_http.browser_urlopen(request)
        self.assertEqual(page.goto.call_args.args[0], "https://tenant.myworkdayjobs.com/Careers")
