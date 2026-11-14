"""Compare a browser download and a scripted run at the same physical times."""

import csv
from http.client import HTTPConnection
from io import BytesIO, StringIO
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from zipfile import ZipFile

from nuclemu.web import make_server


class DownloadParityTests(unittest.TestCase):
    def test_http_products_match_cli_for_both_instruments(self):
        scenarios = (
            ("alpha", "mca", 187, [{}, {"foil_um": 5}]),
            ("beta", "counter", 42, [{"source_present": 0}, {"source_present": 1, "foil_count": 4}]),
        )
        for experiment, device, seed, settings in scenarios:
            with self.subTest(experiment=experiment), TemporaryDirectory() as directory:
                now = 0.0
                with make_server(directory=directory, clock=lambda: now) as server:
                    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": .02})
                    worker.start()
                    client = HTTPConnection("127.0.0.1", server.server_port, timeout=5)

                    def post(path, body):
                        client.request("POST", "/api/" + path, json.dumps(body),
                                       {"Content-Type": "application/json"})
                        response = client.getresponse()
                        payload = response.read()
                        self.assertEqual(response.status, 200, payload)
                        return response, payload

                    try:
                        _, opened = post("open", {"experiment": experiment, "seed": seed})
                        session = json.loads(opened)["id"]
                        target = Path(directory, "cli.json")
                        command = [sys.executable, "-m", "nuclemu", "run", experiment, "--seed", str(seed),
                                   "--device", device, "--enable-output", f"{experiment}_detector",
                                   "--output", str(target)]
                        post("action", {"session": session, "action": "output",
                                        "output": f"{experiment}_detector", "enabled": True})
                        for index, (values, duration) in enumerate(zip(settings, (2.25, 1.25))):
                            if index:
                                _, held = post("action", {"session": session, "action": "begin_clear", "device": device})
                                token = json.loads(held)["clear_confirmation"]["token"]
                                post("action", {"session": session, "action": "finish_clear", "device": device,
                                                "token": token, "choice": "discard"})
                            post("action", {"session": session, "action": "configure", "values": values})
                            post("action", {"session": session, "action": "start", "device": device, "duration": duration})
                            now += duration
                            command.extend(["--step", ",".join([str(duration), *(f"{k}={v}" for k, v in values.items())])])
                        subprocess.run(command, check=True, capture_output=True)
                        expected = json.loads(target.read_text(encoding="utf-8"))
                        response, archive = post("download", {"session": session, "products": [
                            {"device": device, "kind": "measurement", "indices": [0, 1], "format": "json"},
                            {"device": device, "kind": "measurement", "indices": [1], "format": "csv"},
                        ]})
                        self.assertEqual(response.getheader("Content-Type"), "application/zip")
                        with ZipFile(BytesIO(archive)) as bundle:
                            data, table = bundle.namelist()
                            self.assertEqual(json.loads(bundle.read(data)), expected)
                            rows = csv.DictReader(StringIO(bundle.read(table).decode("utf-8")))
                            self.assertEqual([int(row["counts"]) for row in rows],
                                             expected["segments"][1]["readings"][device])
                        response, single = post("download", {"session": session, "products": [
                            {"device": device, "kind": "measurement", "indices": [0], "format": "json"}]})
                        self.assertIn("segment-1.json", response.getheader("Content-Disposition"))
                        self.assertEqual(json.loads(single)["segments"], expected["segments"][:1])
                    finally:
                        client.close()
                        server.shutdown()
                        worker.join()
