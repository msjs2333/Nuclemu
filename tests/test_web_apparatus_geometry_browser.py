"""Desktop apparatus geometry, state illustrations and measurement isolation."""

import json
from pathlib import Path
import unittest

import test_catalog_records_browser as fixtures
from nuclemu.core import Device, Experiment, Parameter

if fixtures.sync_playwright:
    from playwright.sync_api import expect


@unittest.skipUnless(fixtures.sync_playwright, 'Install Playwright to run desktop checks')
class ApparatusGeometryBrowserTests(unittest.TestCase):
    setUp = fixtures.CatalogRecordsBrowserTests.setUp
    stop_server = fixtures.CatalogRecordsBrowserTests.stop_server
    enter = fixtures.CatalogRecordsBrowserTests.enter
    screenshot = fixtures.CatalogRecordsBrowserTests.screenshot

    def state(self):
        return self.page.request.get(self.url + '/api/state').json()

    def load_images(self):
        self.page.wait_for_function("""() => {
            const images = [...document.querySelectorAll('#apparatus img')];
            return images.length === 4 && images.every(i => i.complete && i.naturalWidth && i.width > 0);
        }""")

    def test_empty_parts_dual_housing_and_shared_baseline(self):
        self.enter('beta')
        self.load_images()
        state = self.state()
        self.assertEqual(state['settings']['source_present'], 0)
        self.assertEqual(state['settings']['foil_count'], 0)
        expect(self.page.locator('[data-illustration=source]')).to_have_attribute('src', '/rig-source-empty.webp')
        expect(self.page.locator('[data-illustration=foil]')).to_have_attribute('src', '/rig-foil-empty.webp')
        expect(self.page.locator('[data-asset=counter-dual]')).to_have_attribute('src', '/rig-counter-dual.webp')
        expect(self.page.locator('#apparatus .rig-symbol')).to_have_count(0)
        expect(self.page.locator('#apparatus [data-kind=instrument]')).to_have_count(1)
        expect(self.page.locator('#component [name=source_present]')).to_be_visible()
        expect(self.page.get_by_role('switch', name='β 探测器输出')).not_to_be_checked()
        for width, height in [(1366, 768), (1440, 900)]:
            self.page.set_viewport_size({'width': width, 'height': height})
            self.load_images()
            self.page.wait_for_function("""() => {
                const all = [...document.querySelectorAll('#apparatus img')];
                return all.every(i => parseFloat(i.style.width) > 0);
            }""")
            geometry = self.page.evaluate("""() => {
                const feet = {'source': [480,444], 'foil': [480,463], 'beta-probe':[450,415], 'counter':[480,426]};
                return [...document.querySelectorAll('#apparatus img')].map(i => {
                    const r=i.getBoundingClientRect(), f=feet[i.dataset.illustration];
                    return {kind:i.dataset.illustration, foot:r.top+r.height*f[1]/f[0],
                        beam:r.top+r.height*Number(i.dataset.beamY)};
                });
            }""")
            feet = [item['foot'] for item in geometry]
            beams = [item['beam'] for item in geometry if item['kind'] != 'counter']
            self.assertLess(max(feet) - min(feet), 1.5, geometry)
            self.assertLess(max(beams) - min(beams), 1.5, geometry)
            self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), width)
            panel = self.page.locator('#component').bounding_box()
            scene = self.page.locator('#apparatus').bounding_box()
            self.assertGreaterEqual(panel['y'] + panel['height'], scene['y'] + scene['height'])
            self.assertLessEqual(panel['y'] + panel['height'], height)
            self.screenshot(f'apparatus-beta-empty-{width}')

    def test_selection_is_separate_from_instrument_entry_and_tabs_work_by_keyboard(self):
        self.enter('alpha')
        self.page.locator('#operation-tab').press('ArrowRight')
        expect(self.page.locator('#introduction-tab')).to_be_focused()
        expect(self.page.locator('#introduction-panel')).to_have_text('点击装置展示详情')
        self.page.locator('[data-part=detector]').click()
        expect(self.page.locator('#component h2')).to_have_text('硅探测器')
        expect(self.page.locator('#open-instrument')).to_have_count(0)
        expect(self.page.locator('[data-page=setup]')).to_have_attribute('aria-current', 'page')
        self.page.locator('[data-part=mca]').click()
        expect(self.page.locator('#component h2')).to_have_text('多道谱仪')
        expect(self.page.locator('#apparatus #open-instrument')).to_be_visible()
        expect(self.page.locator('[data-page=setup]')).to_have_attribute('aria-current', 'page')
        self.page.locator('#open-instrument').click()
        expect(self.page.locator('[data-page=instrument]')).to_have_attribute('aria-current', 'page')
        self.assertEqual(self.state()['device'], 'mca')

    def test_course_without_apparatus_keeps_parameter_editors(self):
        course = Experiment('apparatus-unbound-parameters', '装置参数', '',
            (Parameter('gain', '增益', '', 1, 1, 8, True),
             Parameter('threshold', '阈值', '', 1, 1, 8, True),
             Parameter('offset', '偏置', '', 1, 1, 8, True)),
            (Device('counter', 'counter', '计数器'),),
            lambda settings, start, end, rng: {'counter': [0]})
        self.server.app.definitions[course.id] = course
        self.page.reload()
        self.enter(course.id)
        for name in ('gain', 'threshold', 'offset'):
            expect(self.page.locator(f'#component [name={name}]')).to_have_count(1)
            self.page.locator(f'#component [name={name}]').fill('2')
        expect(self.page.locator('#component fieldset').filter(has_text='实验参数')).to_contain_text('偏置')
        self.page.locator('#component form button').click()
        expect(self.page.locator('#component form button')).to_be_disabled()
        self.assertEqual(self.state()['settings'], {'gain': 2, 'threshold': 2, 'offset': 2})

    def test_source_fan_empty_background_and_animation_do_not_change_readings(self):
        self.enter('beta')
        self.load_images()
        self.page.locator('.flow-note input').uncheck()
        count_pixels = """() => {
            const c=document.querySelector('.particle-flow'), g=c.getContext('2d');
            const data=g.getImageData(0,0,c.width,c.height).data;
            let warm=0, visible=0;
            for(let i=0;i<data.length;i+=4) {
                if(data[i+3]) visible++;
                if(data[i+3] && data[i]>data[i+1]*1.3 && data[i+1]>data[i+2]*1.3) warm++;
            }
            return {warm, visible};
        }"""
        self.page.wait_for_function('(' + count_pixels + ')().visible > 0')
        empty = self.page.evaluate(count_pixels)
        self.assertEqual(empty['warm'], 0)
        self.assertGreater(empty['visible'], 0)
        self.page.locator('#component [name=source_present]').select_option('1')
        self.page.locator('#component [name=foil_count]').fill('2')
        self.page.locator('#component form button').click()
        expect(self.page.locator('#component form button')).to_be_disabled()
        expect(self.page.locator('[data-illustration=source]')).to_have_attribute('src', '/rig-source.webp')
        expect(self.page.locator('[data-illustration=foil]')).to_have_attribute('src', '/rig-foil.webp')
        expect(self.page.locator('#apparatus .foil-material')).to_have_text('Al')
        expect(self.page.locator('#component .foil-summary')).to_contain_text('200 µm')
        expect(self.page.locator('#component .foil-summary')).to_contain_text('54 mg/cm²')
        self.page.wait_for_function('(' + count_pixels + ')().warm > 0')
        self.screenshot('apparatus-beta-loaded-fan')
        # Start through the instrument, then compare the two virtual observations
        # at one fixed model time while toggling only the apparatus illustration.
        self.page.get_by_role('switch', name='β 探测器输出').check()
        self.page.locator('[data-page=instrument]').click()
        self.page.locator('#start').click()
        expect(self.page.locator('#stop')).to_be_enabled()
        self.now += 2
        self.page.locator('[data-page=setup]').click()
        before = self.state()
        self.page.locator('.flow-note input').check()
        self.page.locator('.flow-note input').uncheck()
        after = self.state()
        for key in ('instruments', 'counter_windows', 'gates', 'settings'):
            self.assertEqual(before[key], after[key], key)

    def test_counter_asset_metadata_and_schematic_cable_attachment(self):
        import hashlib
        index = json.loads(Path('nuclemu/static/apparatus-assets.json').read_text(encoding='utf-8'))
        asset = index['assets'][0]
        self.assertEqual(hashlib.sha256(Path(asset['path']).read_bytes()).hexdigest(), asset['sha256'])
        self.enter('beta')
        self.load_images()
        anchors = self.page.locator('[data-asset=counter-dual]').evaluate("""i => ({
            x:Number(i.dataset.inX), y:Number(i.dataset.beamY),
            width:i.naturalWidth,height:i.naturalHeight
        })""")
        self.assertEqual([anchors['width'], anchors['height']], asset['size_px'])
        self.assertEqual([anchors['x'], anchors['y']], asset['connection_anchors']['input_normalized'])
        # The cable terminates on the visible housing edge, not the A/B glass.
        self.assertGreaterEqual(anchors['x'] * 426, asset['body_bbox_px_alpha_gt_180'][0])
        self.assertLess(anchors['x'] * 426, 20)


if __name__ == '__main__':
    unittest.main()
