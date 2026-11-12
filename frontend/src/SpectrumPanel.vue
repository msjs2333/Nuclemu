<script setup lang="ts">
import {computed, onBeforeUnmount, onMounted, ref, watch} from 'vue'
import {pointerChannels, drawSpectrum, spectrumExtent} from '/draw.js'
import {describe, exposure, fmt, indexValue, segmentName} from './display'
import type {Act, Calibration, CalibrationContext, Course, Device, Segment, Series, State} from './types'

const props = defineProps<{
  course: Course; device: Device; session: string; segments: Segment[]; index: number | null; analysis: State['analysis']
  calibration: Calibration | null; calibrationContext: CalibrationContext; readout: State['readout']; act: Act
  referenceCalibration: Calibration | null
  currentAcquisition?: number | null; instrument?: State['instrument']
}>()
const emit = defineEmits<{task: [fn: () => Promise<void>]}>()
const available = computed(() => props.segments.map((segment, index) => ({segment, index}))
  .filter(({segment}) => props.device.id in segment.readings))
const current = computed(() => {
  if (props.index !== null) return props.segments[props.index]
  if (props.currentAcquisition === undefined) return available.value.at(-1)?.segment
  for (let i = available.value.length - 1; i >= 0; i--) if (available.value[i].segment.acquisition === props.currentAcquisition) return available.value[i].segment
})
const currentCounts = computed(() => {
  if (props.index === null && props.instrument) return props.instrument.readable_exposure_s > 0 ? props.instrument.counts : null
  return current.value?.readings[props.device.id] ?? null
})
const currentExposure = computed(() => props.index === null && props.instrument
  ? props.instrument.readable_exposure_s : current.value ? exposure(current.value) : 0)
const reference = computed(() => props.analysis.reference === null ? null : props.segments[props.analysis.reference])
const energyScale = computed(() => {
  const c = props.calibration
  if (!c || !props.analysis.energy_axis) return null
  return (channel: number) => c.energy1 + (channel - c.channel1) * (c.energy2 - c.energy1) / (c.channel2 - c.channel1)
})
const incompatible = computed(() => !!(energyScale.value && reference.value && !props.referenceCalibration))
const series = computed(() => {
  const lines: Series[] = []
  function add(segment: Segment | null | undefined, label: string, channelPosition?: (channel: number) => number) {
    if (segment && props.device.id in segment.readings) lines.push({label: [label, describe(props.course, segment.settings), fmt(exposure(segment)) + ' s'].filter(Boolean).join(' · '),
      counts: segment.readings[props.device.id], divisor: props.analysis.rate_axis ? exposure(segment) : 1, channelPosition})
  }
  if (currentCounts.value && currentExposure.value > 0) {
    if (props.index === null && props.instrument) lines.push({label: '本轮累计 · ' + fmt(currentExposure.value) + ' s',
      counts: currentCounts.value, divisor: props.analysis.rate_axis ? currentExposure.value : 1})
    else add(current.value, props.index === null ? '当前谱' : '历史谱')
  }
  if (!incompatible.value) {
    const current = props.calibration, saved = props.referenceCalibration
    const position = energyScale.value && current && saved ? (channel: number) => {
      const energy = saved.energy1 + (channel - saved.channel1) * (saved.energy2 - saved.energy1) / (saved.channel2 - saved.channel1)
      return current.channel1 + (energy - current.energy1) * (current.channel2 - current.channel1) / (current.energy2 - current.energy1)
    } : undefined
    add(reference.value, '参考谱', position)
  }
  return lines
})
const plot = ref<HTMLCanvasElement>()
const rangeMode = ref<'fit' | 'full'>('fit')
const extent = computed(() => spectrumExtent(series.value, props.device.channels))
const heldRange = ref<[number, number] | null>(null)
const visibleRange = computed<[number, number]>(() => heldRange.value ??
  (rangeMode.value === 'fit' ? extent.value.range : [0, props.device.channels - 1]))
const centroidText = computed(() => {
  if (!extent.value.maximum) return series.value.length ? '可见谱暂无计数，显示全道范围。' : '等待采集，显示全道范围。'
  const centroid = props.readout?.centroid
  if (centroid == null) return '选区无计数'
  const [first, last] = props.analysis.roi
  const label = first === 0 && last === props.device.channels - 1 ? '全谱重心' : '选区峰心'
  return label + ' ' + fmt(centroid) + ' 道'
})
let observer: ResizeObserver
function paint() {
  if (plot.value?.clientWidth) drawSpectrum(plot.value, series.value, props.device.channels, props.analysis.roi,
    energyScale.value, props.analysis.rate_axis ? '每道计数率 / s⁻¹' : '每道计数', visibleRange.value, extent.value.maximum)
}
watch([series, energyScale, visibleRange, () => props.analysis.roi], paint, {flush: 'post'})
onMounted(() => {
  observer = new ResizeObserver(paint)
  observer.observe(plot.value!)
  void document.fonts.ready.then(paint)
})
onBeforeUnmount(() => observer.disconnect())
const first = ref(0), last = ref(0)
watch(() => props.analysis.roi.join('/'), () => { [first.value, last.value] = props.analysis.roi }, {immediate: true})
const points = ref<(number | string)[]>([])
const calibrationFile = ref<HTMLInputElement>()
const calibrationNotice = ref('')
let submitted: number[] | null = null
function copyContext(context: CalibrationContext): CalibrationContext {
  return {...context, settings: {...context.settings}}
}
let formContext: CalibrationContext
let fileTarget: {context: CalibrationContext; session: string} | null = null
watch(() => props.calibrationContext, context => {
  calibrationNotice.value = ''
  formContext = copyContext(context)
  const c = props.calibration
  points.value = c ? [c.channel1, c.energy1, c.channel2, c.energy2] : ['', '', '', '']
  submitted = null
}, {immediate: true})
watch(() => props.calibration, c => {
  calibrationNotice.value = ''
  const values = c ? [c.channel1, c.energy1, c.channel2, c.energy2] : ['', '', '', '']
  // An acknowledgement can arrive after the learner starts typing the next pair.
  if (!submitted || !values.every((v, i) => v === submitted![i])) points.value = values
  submitted = null
}, {immediate: true})
function applyCalibration() {
  calibrationNotice.value = ''
  const calibration = points.value.map(Number)
  const context = copyContext(formContext)
  const session = props.session
  submitted = calibration
  emit('task', async () => {
    try { await props.act('calibrate', {points: calibration, calibration_context: context}, session) }
    finally { if (submitted === calibration) submitted = null }
  })
}
function instrumentAction(name: string, fields: Record<string, unknown>, device = props.device.id) {
  const session = props.session
  emit('task', () => props.act(name, {device, ...fields}, session))
}
function change(key: string, value: unknown, device = props.device.id) {
  instrumentAction('analysis', {[key]: value}, device)
}
function checked(e: Event) { return (e.target as HTMLInputElement).checked }
let drag: {first: number; device: string; channelAt: (clientX: number) => number} | null = null
function startDrag(e: PointerEvent) {
  if (e.button !== 0 || !e.isPrimary) return
  heldRange.value = visibleRange.value
  const channelAt = pointerChannels(plot.value!, heldRange.value)
  drag = {first: channelAt(e.clientX), device: props.device.id, channelAt}
  plot.value!.setPointerCapture(e.pointerId)
}
function endDrag(e: PointerEvent) {
  if (!e.isPrimary || drag === null || !heldRange.value) return
  const finish = drag.channelAt(e.clientX)
  change('roi', [Math.min(drag.first, finish), Math.max(drag.first, finish)], drag.device)
  cancelDrag()
}
function cancelDrag() {
  drag = null
  heldRange.value = null
}
function chooseCalibrationFile() {
  fileTarget = {context: copyContext(formContext), session: props.session}
  calibrationFile.value?.click()
}
function saveCalibration() {
  const device = props.device.id, session = props.session
  const context = copyContext(props.calibrationContext)
  calibrationNotice.value = ''
  emit('task', async () => {
    await props.act('cache_calibration', {device, calibration_context: context}, session)
    calibrationNotice.value = '刻度已保存到本场记录'
  })
}
function load(e: Event) {
  const input = e.target as HTMLInputElement, file = input.files?.[0]
  const target = fileTarget ?? {context: copyContext(formContext), session: props.session}
  fileTarget = null
  input.value = ''
  if (file) emit('task', async () => props.act('load_calibration', {
    calibration: JSON.parse(await file.text()), calibration_context: target.context,
  }, target.session))
}
</script>

<template>
  <div id="spectrum">
    <Teleport defer to="#panel-display"><div class="menu-fields">
      <label>当前谱 <select id="sample" :value="index ?? ''" @change="instrumentAction('select', {index: indexValue($event)})">
        <option value="">{{ instrument ? '本轮累计谱' : '跟随最新段' }}</option><option v-for="{segment, index: i} in available" :key="i" :value="i">{{ segmentName(segment, i) }}</option></select></label>
      <label>参考谱 <select id="reference" :value="analysis.reference ?? ''" @change="change('reference', indexValue($event))">
        <option value="">无参考谱</option><option v-for="{segment, index: i} in available" :key="i" :value="i">{{ segmentName(segment, i) }}</option></select></label>
      <label>横轴范围 <select id="spectrum-range" v-model="rangeMode">
        <option value="fit">适合可见谱</option><option value="full">固定全道范围</option></select></label>
      <label><input type="checkbox" id="energy" :disabled="!calibration" :checked="!!energyScale" @change="change('energy_axis', checked($event))"> MeV 横轴</label>
      <label><input type="checkbox" id="rate" :checked="analysis.rate_axis" @change="change('rate_axis', checked($event))"> 按曝光归一</label>
    </div></Teleport>
    <canvas id="plot" ref="plot" :aria-label="`道谱，显示 ${visibleRange[0]} 至 ${visibleRange[1]} 道。可在分析菜单输入选区道号。`" height="260"
      @pointerdown="startDrag" @lostpointercapture="cancelDrag" @pointerup="endDrag"></canvas>
    <div class="spectrum-readout"><div id="legend" class="legend"><span v-for="line in series" :key="line.label">{{ line.label }}</span></div>
      <output id="peak">{{ centroidText }}
        {{ readout?.energy_MeV == null ? '' : ' · ' + Number(readout.energy_MeV.toFixed(5)) + ' MeV' }}</output>
    </div>
    <output v-if="currentCounts" id="spectrum-total">总计数 {{ readout?.counts == null ? '—' : fmt(readout.counts) }} 次 · 可读曝光 {{ fmt(currentExposure) }} s</output>
    <p v-if="incompatible" class="notice">参考谱没有适用的能量刻度。切回道号轴可叠加两张谱。</p>
    <Teleport defer to="#panel-analysis">
    <form id="roi" class="menu-fields" @submit.prevent="change('roi', [first, last])"><strong>选区 ROI</strong>
      <label>起道 <input id="first" v-model.number="first" type="number" min="0" :max="device.channels - 1" required step="1"></label>
      <label>止道 <input id="last" v-model.number="last" type="number" min="0" :max="device.channels - 1" required step="1"></label>
      <button>计算峰心</button>
    </form>
    <output id="roi-result" aria-live="polite">
      <strong>ROI {{ analysis.roi[0] }}–{{ analysis.roi[1] }} 道</strong>
      <template v-if="readout">
        <span>选区计数 {{ readout.roi_counts == null ? '—' : fmt(readout.roi_counts) }} 次</span>
        <span>峰心 {{ readout.centroid == null ? '无计数' : fmt(readout.centroid) + ' 道' }}</span>
        <span>能量 {{ readout.energy_MeV == null ? '—' : Number(readout.energy_MeV.toFixed(5)) + ' MeV' }}</span>
      </template>
      <span v-else>等待可读曝光。</span>
    </output>
    <details class="calibration-tools"><summary>两点能量刻度</summary>
      <form id="calibrate" class="menu-fields" @submit.prevent="applyCalibration">
        <label v-for="(field, i) in ['参考道 1', '能量 1 / MeV', '参考道 2', '能量 2 / MeV']" :key="field">{{ field }}
          <input :name="['c1','e1','c2','e2'][i]" v-model.number="points[i]" type="number" step="any" required></label>
        <button>应用刻度</button>
      </form>
      <div class="calibration-file-actions">
        <button id="load-calibration" type="button" @click="chooseCalibrationFile">载入刻度</button>
        <button id="save-calibration" type="button" :disabled="!calibration" @click="saveCalibration">保存刻度</button>
      </div>
      <input ref="calibrationFile" id="cal-file" type="file" accept=".json" hidden @cancel="fileTarget = null" @change="load">
      <output v-if="calibrationNotice" id="calibration-notice" role="status">{{ calibrationNotice }}</output>
    </details></Teleport>
  </div>
</template>

<style scoped>
#spectrum-total { display: block; font-size: 13px; }
.calibration-file-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
#calibration-notice { display: block; margin-top: 8px; font-size: 13px; }
#roi-result { display: grid; gap: 4px; margin: 8px 0 14px; font-size: 13px; overflow-wrap: anywhere; }
</style>
