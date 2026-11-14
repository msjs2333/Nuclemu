"""Whole-counter exchange uses existing measurements and their stable identities."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from nuclemu.core import Session, Experiment, Device, Component, SignalOutput
from nuclemu.experiments import beta
from nuclemu.exchange import (capture_session, native_snapshot_id, link_measurements,
    list_records, rename_record, decode_measurements, export_item, load_item,
    import_item, package_bytes, load_package, batch_download, validate_document)
from test_cli import invoke

DEVICES=('counter','counter_b')


def saved_set():
    s=Session(beta.EXPERIMENT,seed=187)
    s.set('source_present',1);s.set_output(beta.DETECTOR_OUTPUT,True)
    s.configure_acquisition('counter_b',window_s=5)
    s.start_group(DEVICES);s.advance(3)
    snapshots=tuple(s.snapshot(d) for d in DEVICES)
    doc=capture_session(s)
    identity=link_measurements(doc,[native_snapshot_id(doc,snap) for snap in snapshots],
                               '同名读数',members=DEVICES)
    return s,doc,identity


class GroupExchangeTests(unittest.TestCase):
    def test_counter_box_and_another_instrument_keep_distinct_files_and_gates(self):
        course=Experiment('box-and-spectrum','Counter box and spectrum','',(),
            (Device('a','counter','A',input='out-a'),Device('b','counter','B',input='out-b'),
             Device('mca','spectrum','Separate MCA',2,input='out-mca')),
            lambda settings,start,end,rng:{'out-a':(round(10*(end-start)),),
                'out-b':(round(20*(end-start)),),'out-mca':(round(3*(end-start)),round(4*(end-start)))},
            outputs=(SignalOutput('out-a','A'),SignalOutput('out-b','B'),SignalOutput('out-mca','MCA',2)),
            components=(Component('box','instrument','Counter',device='a',devices=('a','b')),
                        Component('mca-box','instrument','MCA',device='mca')))
        session=Session(course)
        for output in course.outputs:session.set_output(output.id,True)
        session.configure_acquisition('b',window_s=5)
        session.start_group(('a','b'));session.start(device='mca');session.advance(3)
        candidates=session.snapshot_group(('a','b'))
        session.snapshot('mca')
        doc=capture_session(session)
        identity=link_measurements(doc,[native_snapshot_id(doc,s) for s in candidates],members=('a','b'))
        self.assertEqual(len(list_records(doc)),2)
        other=deepcopy(doc['items'][-1])
        for fmt in ('csv','json'):
            bundle=load_item(export_item(doc,identity,fmt))
            self.assertEqual([i['document']['snapshot']['device'] for i in bundle['items']],['a','b'])
            decoded=decode_measurements(bundle,course,('a','b'))
            before=session.instrument('mca')
            session.load_measurements(('a','b'),[d.snapshot for d in decoded],overwrite=True)
            self.assertEqual(session.instrument('mca'),before)
            self.assertTrue(session.instrument('mca').running)
            session.start_group(('a','b'));session.advance(1)
        self.assertEqual(doc['items'][-1],other)
        loaded=load_package(package_bytes(doc))
        self.assertEqual(loaded['items'][-1],other)
        rename_record(loaded,identity,'Counter only')
        self.assertEqual(loaded['items'][-1],other)
        before=session.instrument('mca')
        requests=session.begin_clear_group(('a','b'))
        session.finish_clear_group(('a','b'),{r.device:r.token for r in requests},'discard')
        self.assertEqual(session.instrument('mca'),before)
        self.assertEqual([session.instrument(d).exposure_s for d in ('a','b')],[0,0])

    def test_candidate_file_can_be_built_before_atomic_snapshot_cache_commit(self):
        session=Session(beta.EXPERIMENT,seed=187)
        session.start_group(DEVICES);session.advance(1)
        previous=capture_session(session)
        def writer(candidates):
            doc=capture_session(session,previous,additional_snapshots=candidates)
            identity=link_measurements(doc,[native_snapshot_id(doc,s) for s in candidates],members=DEVICES)
            self.assertEqual(len(list_records(load_package(package_bytes(doc)))),1)
            self.assertEqual(len(decode_measurements(doc,beta.EXPERIMENT,DEVICES,identity)),2)
            raise OSError('write failed')
        with self.assertRaisesRegex(OSError,'write failed'):
            session.snapshot_group(DEVICES,writer=writer)
        self.assertEqual(session.snapshots,())
        self.assertEqual(previous['items'],[])

    def test_asymmetric_windows_real_partial_and_both_formats_round_trip(self):
        s,doc,identity=saved_set()
        self.assertEqual(len(list_records(doc)),1)
        for fmt in ('json','csv'):
            with self.subTest(format=fmt):
                bundle=load_item(export_item(doc,identity,fmt))
                self.assertEqual(bundle['items'],doc['items'])
                decoded=decode_measurements(bundle,beta.EXPERIMENT,DEVICES,identity)
                self.assertEqual([len(d.snapshot.windows) for d in decoded],[3,1])
                self.assertFalse(decoded[1].snapshot.windows[0].complete)
                self.assertEqual(decoded[1].snapshot.windows[0].end_exposure_s,3)
                fresh=Session(beta.EXPERIMENT,seed=187)
                for d in decoded:fresh.load_measurement(d.snapshot.device,d.snapshot)
                fresh.set('source_present',1);fresh.set_output(beta.DETECTOR_OUTPUT,True)
                fresh.start_group(DEVICES);fresh.advance(2)
                self.assertEqual([fresh.instrument(d).exposure_s for d in DEVICES],[5,5])
                self.assertTrue(fresh.instrument_windows('counter_b')[0].complete)
                self.assertEqual(fresh.instrument_windows('counter_b')[0].end_exposure_s,5)
        self.assertEqual(load_package(package_bytes(doc)),doc)

    def test_duplicate_names_import_remaps_only_ids_and_rename_keeps_references(self):
        _,doc,identity=saved_set()
        source=load_item(export_item(doc,identity,'csv'))
        before=deepcopy(doc)
        new_id=import_item(doc,source,identity)
        self.assertNotEqual(new_id,identity)
        self.assertEqual(doc['items'][:2],before['items'])
        self.assertEqual(len(list_records(doc)),2)
        copied=doc['items'][2:]
        self.assertEqual(copied[0]['group']['items'],[i['id'] for i in copied])
        self.assertEqual([i['source'] for i in copied],[i['source'] for i in before['items']])
        rename_record(doc,new_id,'改名')
        self.assertEqual([i['title'] for i in doc['items']],['同名读数']*2+['改名']*2)
        name,mime,data=batch_download(doc,[dict(id=identity,format='csv'),dict(id=new_id,format='json')])
        self.assertEqual(mime,'application/zip')
        with ZipFile(BytesIO(data)) as zipped:
            self.assertEqual(len(set(zipped.namelist())),2)
            self.assertTrue(all(len(load_item(zipped.read(n))['items'])==2 for n in zipped.namelist()))

    def test_missing_or_repeated_member_is_rejected_without_importing(self):
        _,doc,identity=saved_set()
        for ids in ([identity,identity],[identity,'missing']):
            broken=deepcopy(doc);broken['items'][0]['group']['items']=ids
            with self.assertRaises(ValueError):validate_document(broken)
        before=deepcopy(doc)
        with self.assertRaises(ValueError):link_measurements(doc,[identity,identity])
        self.assertEqual(doc,before)

    def test_single_side_set_is_distinct_from_legacy_single(self):
        _,doc,identity=saved_set()
        doc['items']=doc['items'][:1]
        doc['items'][0]['group']['items']=[identity]
        decoded=decode_measurements(load_item(export_item(doc,identity,'csv')),beta.EXPERIMENT,DEVICES)
        self.assertEqual(len(decoded),1)
        self.assertEqual(list_records(doc)[0]['group']['members'],list(DEVICES))
        doc['items'][0].pop('group')
        self.assertNotIn('group',list_records(doc)[0])
        self.assertEqual(len(decode_measurements(load_item(export_item(doc,identity)),beta.EXPERIMENT,DEVICES)),1)

    def test_actual_cli_export_import_rename_and_batch_files(self):
        _,doc,identity=saved_set()
        with TemporaryDirectory() as tmp:
            root=Path(tmp);package=root/'original.nuclemu';package.write_bytes(package_bytes(doc))
            for fmt in ('csv','json'):
                single=root/f'group.{fmt}'
                result=invoke('files','export',str(package),'--item',identity,'--output',str(single))
                self.assertEqual(result.returncode,0,result.stderr)
                merged=root/f'merged-{fmt}.nuclemu'
                result=invoke('files','import',str(package),str(single),'--item',identity,'--output',str(merged))
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(len(list_records(load_package(merged))),2)
            renamed=root/'renamed.nuclemu'
            result=invoke('files','rename',str(package),'--item',identity,'--title','任意同名','--output',str(renamed))
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(all(i['title']=='任意同名' for i in load_package(renamed)['items']))
            output=root/'selected.zip'
            result=invoke('files','batch-export',str(package),'--item',identity+':csv',
                          '--item',identity+':json','--output',str(output))
            self.assertEqual(result.returncode,0,result.stderr)
            with ZipFile(output) as zipped:self.assertEqual(len(zipped.namelist()),2)


if __name__=='__main__':unittest.main()
