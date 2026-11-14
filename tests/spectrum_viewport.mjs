import assert from 'node:assert/strict';
import test from 'node:test';
import {pointerChannels, drawSpectrum, margin, spectrumExtent} from '../nuclemu/static/draw.js';

function spectrum(length, entries, divisor = 1) {
  const counts = Array(length).fill(0);
  for (const [channel, count] of entries) counts[channel] = count;
  return {counts, divisor};
}

test('fixed channel extent includes every sample and reference without horizontal zoom', () => {
  const sample = spectrum(1024, [[900, 500], [940, 1]]);
  const reference = spectrum(1024, [[200, 1]], 4);
  assert.deepEqual(spectrumExtent([sample], 1024), {range: [0, 1023], maximum: 500});
  assert.deepEqual(spectrumExtent([sample, reference], 1024), {range: [0, 1023], maximum: 500});
  assert.deepEqual(spectrumExtent([sample, {...reference, divisor: 0}], 1024),
    spectrumExtent([sample], 1024));
});

test('empty exposure, dead sample, edge peaks and a one-channel device', () => {
  assert.deepEqual(spectrumExtent([], 7), {range: [0, 6], maximum: 0});
  assert.deepEqual(spectrumExtent([spectrum(7, [])], 7), {range: [0, 6], maximum: 0});
  assert.deepEqual(spectrumExtent([spectrum(7, [[0, 2]])], 7), {range: [0, 6], maximum: 2});
  assert.deepEqual(spectrumExtent([spectrum(7, [[6, 2]], 4)], 7), {range: [0, 6], maximum: .5});
  assert.deepEqual(spectrumExtent([spectrum(1, [[0, 1]])], 1), {range: [0, 0], maximum: 1});
});

test('pointer coordinates in a fitted view return original channel addresses, including margins', () => {
  const canvas = {clientWidth: 589, clientLeft: 1, getBoundingClientRect: () => ({left: 20})};
  const left = 20 + 1 + margin.left;
  const channelAt = pointerChannels(canvas, [840, 970]);
  canvas.clientWidth += 288; // The analysis pane can change the layout during a gesture.
  for (const [offset, expected] of [[-50, 840], [0, 840], [250, 905], [500, 970], [600, 970]]) {
    assert.equal(channelAt(left + offset), expected);
  }
  assert.equal(pointerChannels(canvas, [0, 0])(left + 500), 0);
});

test('a fitted calibrated view uses absolute channels for ticks, and clips an offscreen ROI', () => {
  globalThis.window = {devicePixelRatio: 1};
  const labels = [], fills = [], path = [];
  const context = new Proxy({
    fillText: (label, x, y) => labels.push([label, x, y]),
    moveTo: (...args) => path.push(args),
    lineTo: (...args) => path.push(args),
    beginPath: () => {path.length=0},
    fill: () => fills.push([...path])
  }, {get: (object, key) => object[key] ?? (() => {})});
  const canvas = {clientWidth: 589, clientHeight: 300, getContext: () => context};
  const draw = roi => drawSpectrum(canvas, [spectrum(1024, [[900, 1]])], 1024, roi,
    channel => channel * .006, '每道计数', [840, 970], 1);
  draw([100, 150]);
  assert.deepEqual(fills, []);
  const ticks = labels.filter(([, , y]) => y === 300 - margin.bottom + 18);
  assert.ok(ticks.length >= 2);
  for (const [label, x] of ticks) {
    const channel = 840 + 130 * (x - margin.left) / 500;
    assert.ok(Math.abs(Number(label) - channel * .006) < 1e-8);
  }
  draw([800, 900]);
  assert.equal(fills.length, 1);
  assert.deepEqual(fills[0][0], [margin.left, 300-margin.bottom]);
  assert.ok(fills[0].some(([x,y]) => Math.abs(x-(margin.left+500*60/130)) < 1e-8 && y === margin.top));
});

test('390px phone displays multiple spaced MeV marks for the foil and reference overlay', () => {
  globalThis.window = {devicePixelRatio: 1};
  const ticks = [], width = 370, height = 350;
  const context = new Proxy({
    fillText(label, x, y) {
      if (y === height - margin.bottom + 18) ticks.push({energy: Number(label), x});
    }
  }, {get: (object, key) => object[key] ?? (() => {})});
  const canvas = {clientWidth: width, clientHeight: height, getContext: () => context};
  const energy = channel => 5.155 + (channel - 859.193818) * .65 / (967.472185 - 859.193818);
  const range = [689, 997];
  drawSpectrum(canvas, [], 1024, [0, 1023], energy, '每道计数', range, 1);
  assert.deepEqual(ticks.map(t => t.energy), [4.5, 5, 5.5]);
  for (const [index, tick] of ticks.entries()) {
    if (index) assert.ok(tick.x - ticks[index - 1].x > 40);
    const channel = range[0] + (range[1] - range[0]) * (tick.x - margin.left) / (width - margin.left - margin.right);
    assert.ok(Math.abs(energy(channel) - tick.energy) < 1e-10);
  }
});
