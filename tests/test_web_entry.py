"""External links can open the HTML workbench without relaxing API origin checks."""

from http.client import HTTPConnection
import json
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from nuclemu.web import make_server


class WorkbenchEntryTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.server = make_server(directory=self.folder.name)
        self.worker = Thread(target=self.server.serve_forever, kwargs={"poll_interval": .02})
        self.worker.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.worker.join()
        self.server.server_close()

    def request(self, path, *, method="GET", headers=None):
        request_headers = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate",
                           "Sec-Fetch-Dest": "document"}
        request_headers.update(headers or {})
        body = None
        if method == "POST":
            body = json.dumps({"experiment": "beta"})
            request_headers["Content-Type"] = "application/json"
        client = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            client.request(method, path, body, request_headers)
            response = client.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            client.close()

    def test_normal_external_top_level_links_open_only_html_entrypoints(self):
        for path in ("/", "/lab/beta/#instrument", "/experiment/alpha/"):
            with self.subTest(path=path):
                status, mime, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn("text/html", mime)
                self.assertIn(b"Nuclemu", body)
        self.assertIsNone(self.server.app.lab)

    def test_api_post_static_assets_and_subresource_fetches_stay_restricted(self):
        for path, method, headers in (
            ("/api/catalog", "GET", {}),
            ("/api/state", "GET", {}),
            ("/api/open", "POST", {}),
            ("/api/action", "POST", {}),
            ("/index.html", "GET", {}),
            ("/assets/app.js", "GET", {}),
            ("/", "GET", {"Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}),
            ("/lab/beta/", "GET", {"Sec-Fetch-Dest": "iframe"}),
        ):
            with self.subTest(path=path, method=method, headers=headers):
                self.assertEqual(self.request(path, method=method, headers=headers)[0], 403)
        self.assertIsNone(self.server.app.lab)

    def test_navigation_still_checks_loopback_host_and_origin(self):
        for headers in ({"Host": "untrusted.example"}, {"Origin": "https://untrusted.example"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/", headers=headers)[0], 403)
        status, _, _ = self.request("/api/catalog", headers={"Sec-Fetch-Site": "same-origin",
                                                            "Sec-Fetch-Mode": "cors"})
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
