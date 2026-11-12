"""Web import uses saved item identity, without altering live acquisitions."""

from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest

from nuclemu.catalog import discover
from nuclemu.core import Session
from nuclemu.exchange import (bind_calibration, cache_calibration, capture_session,
                              export_item, load_item, load_package, package_bytes)
from nuclemu.results import Calibration
from nuclemu.web_import import apply_import, inspect_import
from nuclemu.web_session import Application


class WebImportTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.definitions = discover()
        self.definition = self.definitions["alpha"]
        self.now = 0
        app = Application(self.definitions, self.folder.name, clock=lambda: self.now)
        app.open({"experiment": "alpha", "seed": 20})
        self.lab = app.lab
        self.lab.work.set_output("alpha_detector", True)
        self.lab.work.start(10, device="mca")
        self.lab.work.advance(2)
        self.native = self.lab.work.snapshot(device="mca")
        self.lab.work.select(0)
        self.lab.analysis["mca"]["selected"] = 0

    def source(self, seed):
        session = Session(self.definition, seed=seed)
        session.configure({'source_present': 1})
        session.set_output("alpha_detector", True)
        session.start(3, device="mca")
        session.advance(3)
        snapshot = session.snapshot("mca")
        doc = capture_session(session)
        calibration = Calibration("alpha", "mca", self.definition.devices[0].channels, 0, 0, 1000, 6)
        cal_id = cache_calibration(doc, calibration)
        bind_calibration(doc, doc["items"][0]["id"], cal_id)
        self.assertEqual(snapshot.id, 1)
        return doc

    def test_two_packages_have_distinct_identity_and_preserve_live_state(self):
        source_a, source_b = self.source(30), self.source(31)
        self.assertEqual(source_a["items"][0]["title"], source_b["items"][0]["title"])
        work = self.lab.work
        before = (work.session.time_s, work.session.instrument("mca"),
                  work.session._rng.getstate(), work.session.snapshots, deepcopy(work.product()["segments"]))
        results = []
        for source in (source_a, source_b):
            inspected = inspect_import(self.lab, package_bytes(source))
            result = apply_import(self.lab, inspected["token"], inspected["items"][0]["id"])
            results.append(result)
            with self.assertRaisesRegex(ValueError, "过期"):
                apply_import(self.lab, inspected["token"], inspected["items"][0]["id"])
        self.assertNotEqual(results[0]["id"], results[1]["id"])
        self.assertEqual([r["reference"] for r in results], [None, None])
        self.assertEqual(self.lab.product_generation, 2)
        after = (work.session.time_s, work.session.instrument("mca"),
                 work.session._rng.getstate(), work.session.snapshots, deepcopy(work.product()["segments"][-1:]))
        self.assertEqual(before, after)
        self.assertEqual(work.lab.selected, 2)
        self.assertIsNone(self.lab.analysis["mca"]["reference"])
        self.lab.act(dict(action='analysis', device='mca', reference=1))
        imported = work.product()["segments"][1]
        expected = source_b["items"][0]["document"]["segments"][0]
        self.assertEqual(imported, expected)
        self.assertEqual(sum(imported["readings"]["mca"]), sum(expected["readings"]["mca"]))
        self.assertEqual(imported["end_s"] - imported["start_s"], 3)
        doc = load_package(self.lab.portable_download()[2])
        items = {item["id"]: item for item in doc["items"]}
        for result, source in zip(results, (source_a, source_b)):
            item = items[result["id"]]
            self.assertEqual(item["source"], source["items"][0]["source"])
            self.assertEqual(items[item["calibration_id"]]["document"], source["items"][1]["document"])
            bundle = load_item(export_item(doc, item["id"]))
            self.assertEqual(bundle["items"][0]["source"], item["source"])
        self.assertEqual(len(work.session.snapshots), 1)
        self.assertEqual(work.lab.calibrations, {})

    def test_multisegment_is_not_auto_selected_and_calibration_is_only_cached(self):
        session = Session(self.definition, seed=39)
        session.set_output("alpha_detector", True)
        session.start(5, device="mca")
        session.advance(2)
        session.configure({"foil_count": 5})
        session.advance(3)
        session.snapshot("mca")
        doc = capture_session(session)
        self.assertGreater(len(doc["items"][0]["document"]["segments"]), 1)
        cal_id = cache_calibration(doc, Calibration("alpha", "mca", self.definition.devices[0].channels,
                                                    0, 0, 1000, 6))
        before = self.lab.work.lab.selected
        inspected = inspect_import(self.lab, package_bytes(doc))
        result = apply_import(self.lab, inspected["token"], doc["items"][0]["id"])
        self.assertTrue(result["multi_segment"])
        self.assertIsNone(result["reference"])
        self.assertIsNone(self.lab.analysis["mca"]["reference"])
        self.assertEqual(self.lab.work.lab.selected, before + result["segments"])
        inspected = inspect_import(self.lab, package_bytes(doc))
        cal = apply_import(self.lab, inspected["token"], cal_id)
        self.assertEqual(cal["kind"], "calibration")
        self.assertEqual(cal["segments"], 0)
        self.assertEqual(self.lab.work.lab.calibrations, {})
        self.assertEqual(self.lab.product_generation, 2)

    def test_json_csv_inspect_and_newer_token_invalidates_previous(self):
        source = self.source(33)
        identity = source["items"][0]["id"]
        for fmt in ("json", "csv"):
            with self.subTest(fmt=fmt):
                old = inspect_import(self.lab, export_item(source, identity, fmt))
                current = inspect_import(self.lab, export_item(source, identity, fmt))
                with self.assertRaisesRegex(ValueError, "过期"):
                    apply_import(self.lab, old["token"], identity)
                result = apply_import(self.lab, current["token"], identity)
                self.assertEqual(result["kind"], "measurement")
                item = next(i for i in self.lab.exchange.document["items"] if i["id"] == result["id"])
                self.assertEqual(item["document"], source["items"][0]["document"])
                self.assertIn("calibration_id", item)

    def test_old_page_indices_are_rejected_after_import_shifts_the_prefix(self):
        cursor = self.lab.state()['product_cursor']
        source = self.source(33)
        inspected = inspect_import(self.lab, package_bytes(source))
        apply_import(self.lab, inspected['token'], source['items'][0]['id'])
        selected = self.lab.work.lab.selected
        for fields in (dict(action='select', index=0), dict(action='analysis', reference=0), dict(action='analysis', background=0)):
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, '记录列表已改变'):
                self.lab.act(dict(device='mca', product_cursor=cursor, **fields))
        self.assertEqual(self.lab.work.lab.selected, selected)

    def test_saved_uuid_is_part_of_delayed_calibration_context(self):
        identities = []
        for seed in (33, 34):
            source = self.source(seed)
            inspected = inspect_import(self.lab, package_bytes(source))
            identities.append(apply_import(self.lab, inspected['token'], source['items'][0]['id'])['id'])
        self.lab.act(dict(action='select', device='mca', item_id=identities[0]))
        context = self.lab.calibration_context()
        self.lab.act(dict(action='select', device='mca', item_id=identities[1]))
        with self.assertRaisesRegex(ValueError, '刻度所用设备'):
            self.lab.act(dict(action='calibrate', points=[0, 0, 1000, 4], calibration_context=context))
        self.assertEqual(self.lab.state()['selected_item_id'], identities[1])

    def test_saving_native_snapshot_does_not_rebind_import_with_same_sequence(self):
        source = self.source(33)
        inspected = inspect_import(self.lab, package_bytes(source))
        result = apply_import(self.lab, inspected['token'], source['items'][0]['id'])
        item = next(i for i in self.lab.exchange.document['items'] if i['id'] == result['id'])
        original_binding = item['calibration_id']
        self.lab.work.select(None)
        self.lab.analysis['mca']['selected'] = None
        calibration = Calibration('alpha', 'mca', self.definition.devices[0].channels, 0, 0, 1000, 3)
        self.lab.work.apply_calibration(calibration)
        self.lab.cache_calibration()
        self.lab.bind_saved_calibration(self.native)
        item = next(i for i in self.lab.exchange.document['items'] if i['id'] == result['id'])
        self.assertEqual(item['calibration_id'], original_binding)
        native = next(i for i in self.lab.exchange.document['items'] if i['kind'] == 'measurement'
                      and i['source']['package'] == self.lab.exchange.document['id'])
        self.assertNotEqual(native['calibration_id'], original_binding)

    def test_selecting_imported_spectra_restores_each_linked_calibration(self):
        for energy in (6, 3):
            source = self.source(33)
            source['items'][1]['document']['energy2'] = energy
            inspected = inspect_import(self.lab, package_bytes(source))
            apply_import(self.lab, inspected['token'], source['items'][0]['id'])
        data = self.lab.portable_download()[2]
        from nuclemu.web_portable import open_portable
        reopened = open_portable(data, self.definitions, self.lab.store, lambda: self.now)
        energies = []
        imported_indices = [rows[0] for identity, rows in reopened.work.lab.view.item_indices.items()
                            if next(i for i in reopened.exchange.document['items'] if i['id'] == identity)['source']['package']
                            != reopened.exchange.document['id']]
        first, second = imported_indices
        reopened.act(dict(action='analysis', device='mca', reference=second))
        for index, slope in ((first, .006), (second, .003), (first, .006)):
            reopened.act(dict(action='select', device='mca', index=index))
            state = reopened.state()
            calibration = reopened.work.active_calibration()
            self.assertAlmostEqual(calibration.energy(1000), slope * 1000)
            energies.append(state['readout']['energy_MeV'])
            self.assertEqual(state['reference_calibration']['energy2'], 3)
        self.assertAlmostEqual(energies[0], energies[1] * 2)
        self.assertEqual(energies[0], energies[2])
        reopened.act(dict(action='select', device='mca', index=None))
        live_cal = Calibration('alpha', 'mca', self.definition.devices[0].channels, 0, 0, 1000, 4)
        reopened.work.apply_calibration(live_cal)
        reopened.act(dict(action='select', device='mca', index=first))
        reopened.act(dict(action='select', device='mca', index=None))
        self.assertEqual(reopened.work.active_calibration(), live_cal)


if __name__ == "__main__":
    unittest.main()
