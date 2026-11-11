<script setup lang="ts">
import {computed, onBeforeUnmount, onMounted, ref, watch} from 'vue'
import {channelAt, drawSpectrum} from '/draw.js'
import {exposure, fmt, indexValue, segmentName} from './display'
import type {Act, Calibration, Device, Segment, Series, State} from './types'

const props = defineProps<{
  device: Device; segments: Segment[]; index: number | null; analysis: State['analysis']
  calibration: Calibration | null; readout: State['readout']; act: Act
}>()
const emit = defineEmits<{task: [fn: () => Promise<void>]}>()
const current = computed(() => props.segments[props.index ?? props.segments.length - 1])
const reference = computed(() => props.analysis.reference === null ? null : props.segments[props.analysis.reference])
const energyScale = computed(() => {
  const c = props.calibration
  if (!c || !props.analysis.energy_axis) return null
  return (channel: number) => c.energy1 + (channel - c.channel1) * (c.energy2 - c.energy1) / (c.channel2 - c.channel1)
})
const incompatible = computed(() => !!(energyScale.value && reference.value && props.calibration?.conditions.some(
  ([key, value]) => reference.value!.settings[key] !== value)))
const series = computed(() => {
  const lines: Series[] = []
  function add(segment: Segment | null | undefined, label: string) {
    if (segment) lines.push({label: label + ' · ' + fmt(exposure(segment)) + ' s',
      counts: segment.readings[props.device.id], divisor: props.analysis.rate_axis ? exposure(segment) : 1})
  }
  add(current.value, '当前谱')
  if (!incompatible.value) add(reference.value, '参考谱')
  return lines
})
const plot = ref<HTMLCanvasElement>()
let observer: ResizeObserver
function paint() {
  if (plot.value?.clientWidth) drawSpectrum(plot.value, series.value, props.device.channels, props.analysis.roi,
    energyScale.value, props.analysis.rate_axis ? '每道计数率 / s⁻¹' : '每道计数')
}
watch([series, energyScale, () => props.analysis.roi], paint, {flush: 'post'})
onMounted(() => { observer = new ResizeObserver(paint); observer.observe(plot.value!); paint() })
onBeforeUnmount(() => observer.disconnect())
const first = ref(0), last = ref(0)
watch(() => props.analysis.roi.join('/'), () => { [first.value, last.value] = props.analysis.roi }, {immediate: true})
const points = ref<(number | string)[]>([])
let submitted: number[] | null = null
watch(() => props.calibration, c => {
  const values = c ? [c.channel1, c.energy1, c.channel2, c.energy2] : ['', '', '', '']
  // An acknowledgement can arrive after the learner starts typing the next pair.
  if (!submitted || !values.every((v, i) => v === submitted![i])) points.value = values
  submitted = null
}, {immediate: true})
function applyCalibration() {
  const calibration = points.value.map(Number)
  submitted = calibration
  emit('task', async () => {
    try { await props.act('calibrate', {points: calibration}) }
    finally { if (submitted === calibration) submitted = null }
  })
}
function change(key: string, value: unknown) { emit('task', () => props.act('analysis', {[key]: value})) }
function checked(e: Event) { return (e.target as HTMLInputElement).checked }
let drag: number | null = null
function startDrag(e: PointerEvent) {
  if (e.button !== 0) return
  drag = channelAt(plot.value!, e, props.device.channels)
  plot.value!.setPointerCapture(e.pointerId)
}
function endDrag(e: PointerEvent) {
  if (drag === null) return
  const finish = channelAt(plot.value!, e, props.device.channels)
  change('roi', [Math.min(drag, finish), Math.max(drag, finish)])
  drag = null
}
function load(e: Event) {
  const input = e.target as HTMLInputElement, file = input.files?.[0]
  input.value = ''
  if (file) emit('task', async () => props.act('load_calibration', {calibration: JSON.parse(await file.text())}))
}
</script>

<template>
  <div id="spectrum">
    <Teleport defer to="#panel-display"><div class="menu-fields">
      <label>当前谱 <select id="sample" :value="index ?? ''" @change="emit('task', () => act('select', {index: indexValue($event)}))">
        <option value="">跟随最新段</option><option v-for="(s, i) in segments" :key="i" :value="i">{{ segmentName(s, i) }}</option></select></label>
      <label>参考谱 <select id="reference" :value="analysis.reference ?? ''" @change="change('reference', indexValue($event))">
        <option value="">无参考谱</option><option v-for="(s, i) in segments" :key="i" :value="i">{{ segmentName(s, i) }}</option></select></label>
      <label><input type="checkbox" id="energy" :disabled="!calibration" :checked="!!energyScale" @change="change('energy_axis', checked($event))"> MeV 横轴</label>
      <label><input type="checkbox" id="rate" :checked="analysis.rate_axis" @change="change('rate_axis', checked($event))"> 按曝光归一</label>
    </div></Teleport>
    <canvas id="plot" ref="plot" aria-label="道谱，亦可在下方输入选区道号" height="260"
      @pointerdown="startDrag" @pointercancel="drag = null" @pointerup="endDrag"></canvas>
    <div class="spectrum-readout"><div id="legend" class="legend"><span v-for="line in series" :key="line.label">{{ line.label }}</span></div>
      <output id="peak">{{ readout?.centroid == null ? '无可测峰心' : '峰心 ' + fmt(readout.centroid) + ' 道' }}
        {{ readout?.energy_MeV == null ? '' : ' · ' + Number(readout.energy_MeV.toFixed(5)) + ' MeV' }}</output>
    </div>
    <p v-if="incompatible" class="notice">参考谱的刻度工况不同。切回道号轴可叠加两张谱。</p>
    <Teleport defer to="#panel-analysis">
    <form id="roi" class="menu-fields" @submit.prevent="change('roi', [first, last])"><strong>选区 ROI</strong>
      <label>起道 <input id="first" v-model.number="first" type="number" min="0" :max="device.channels - 1" required step="1"></label>
      <label>止道 <input id="last" v-model.number="last" type="number" min="0" :max="device.channels - 1" required step="1"></label>
      <button>计算峰心</button>
    </form>
    <details class="calibration-tools"><summary>两点能量刻度</summary>
      <form id="calibrate" class="menu-fields" @submit.prevent="applyCalibration">
        <label v-for="(field, i) in ['参考道 1', '能量 1 / MeV', '参考道 2', '能量 2 / MeV']" :key="field">{{ field }}
          <input :name="['c1','e1','c2','e2'][i]" v-model.number="points[i]" type="number" step="any" required></label>
        <button>应用刻度</button>
      </form><label>载入刻度 JSON <input id="cal-file" type="file" accept=".json" @change="load"></label>
    </details></Teleport>
  </div>
</template>
