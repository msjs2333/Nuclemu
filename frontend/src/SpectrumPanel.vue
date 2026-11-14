<script setup lang="ts">
import {computed, onBeforeUnmount, onMounted, ref, watch} from 'vue'
import {pointerChannels, drawSpectrum, spectrumExtent} from '/draw.js'
import {describe, exposure, fmt, segmentName} from './display'
import {errorMessage} from './api'
import type {Act, Calibration, CalibrationContext, Course, Device, Segment, Series, State} from './types'

type SavedMeasurement = {id: string; device: string; title: string; exposure_s: number; settings: Record<string, number>[]; calibration_id: string | null}
type Observation = {id: string; device: string; title: string; counts: number[]; exposure_s: number; segments: Segment[]; calibration_id: string | null}
const props = defineProps<{
  course: Course; device: Device; session: string; segments: Segment[]; index: number | null; analysis: State['analysis']
  calibration: Calibration | null; calibrationContext: CalibrationContext; readout: State['readout']; act: Act
  roiResult: State['roi_result']; roiContext: State['roi_context']
  referenceCalibration: Calibration | null
  currentAcquisition?: number | null; instrument?: State['instrument']
  savedMeasurements?: SavedMeasurement[]; selectedItemId?: string | null; referenceItemId?: string | null
  selectedObservation?: Observation | null; referenceObservation?: Observation | null
}>()
const emit = defineEmits<{task: [fn: () => Promise<void>]}>()
const available = computed(() => props.segments.map((segment, index) => ({segment, index}))
  .filter(({segment}) => props.device.id in segment.readings))
const legacySegments = computed(() => props.course.outputs?.length ? [] : available.value)
const current = computed(() => {
  if (props.index !== null) return props.segments[props.index]
  if (props.currentAcquisition === undefined) return available.value.at(-1)?.segment
  for (let i = available.value.length - 1; i >= 0; i--) if (available.value[i].segment.acquisition === props.currentAcquisition) return available.value[i].segment
})
const currentCounts = computed(() => {
  if (props.selectedObservation) return props.selectedObservation.counts
  if (props.index === null && props.instrument) return props.instrument.readable_exposure_s > 0 ? props.instrument.counts : null
  return current.value?.readings[props.device.id] ?? null
})
const currentExposure = computed(() => props.selectedObservation?.exposure_s ?? (props.index === null && props.instrument
  ? props.instrument.readable_exposure_s : current.value ? exposure(current.value) : 0))
const saved = computed(() => (props.savedMeasurements ?? []).filter(item => item.device === props.device.id))
const selectedValue = computed(() => props.selectedItemId ?? (props.index == null ? '' : 'segment:' + props.index))
const referenceValue = computed(() => props.referenceItemId ?? (props.analysis.reference == null ? '' : 'segment:' + props.analysis.reference))
function selectSpectrum(event: Event, reference = false) {
  const value = (event.target as HTMLSelectElement).value
  if (reference) {
    instrumentAction('analysis', value.startsWith('segment:') ? {reference: Number(value.slice(8)), reference_item_id: null} : {reference_item_id: value || null})
  } else instrumentAction('select', value.startsWith('segment:') ? {index: Number(value.slice(8))} : value ? {item_id: value} : {index: null})
}
const reference = computed(() => props.analysis.reference === null ? null : props.segments[props.analysis.reference])
const energyScale = computed(() => {
  const c = props.calibration
  if (!c || !props.analysis.energy_axis) return null
  return (channel: number) => c.energy1 + (channel - c.channel1) * (c.energy2 - c.energy1) / (c.channel2 - c.channel1)
})
const incompatible = computed(() => !!(energyScale.value && (reference.value || props.referenceObservation) && !props.referenceCalibration))
const series = computed(() => {
  const lines: Series[] = []
  function add(segment: Segment | null | undefined, label: string, channelPosition?: (channel: number) => number) {
    if (segment && props.device.id in segment.readings) lines.push({label,
      counts: segment.readings[props.device.id], divisor: props.analysis.rate_axis ? exposure(segment) : 1, channelPosition})
  }
  if (currentCounts.value && currentExposure.value > 0) {
    lines.push({label: '当前谱：' + (props.selectedObservation?.title ?? (props.index === null ? '本轮累计谱' : '历史谱')),
      counts: currentCounts.value, divisor: props.analysis.rate_axis ? currentExposure.value : 1})
  }
  if (!incompatible.value) {
    const current = props.calibration, saved = props.referenceCalibration
    const position = energyScale.value && current && saved ? (channel: number) => {
      const energy = saved.energy1 + (channel - saved.channel1) * (saved.energy2 - saved.energy1) / (saved.channel2 - saved.channel1)
      return current.channel1 + (energy - current.energy1) * (current.channel2 - current.channel1) / (current.energy2 - current.energy1)
    } : undefined
    if (props.referenceObservation) {
      const item = props.referenceObservation
      lines.push({label: '参考谱：' + item.title, counts: item.counts,
        divisor: props.analysis.rate_axis ? item.exposure_s : 1, channelPosition: position})
    } else add(reference.value, '参考谱', position)
  }
  return lines
})
const plot = ref<HTMLCanvasElement>()
const extent = computed(() => spectrumExtent(series.value, props.device.channels))
const heldRange = ref<[number, number] | null>(null)
const visibleRange = computed<[number, number]>(() => heldRange.value ??
  extent.value.range)
function calculateRoi() {
  instrumentAction('calculate_roi', {roi: [first.value, last.value], roi_context: props.roiContext})
}
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
watch(() => props.analysis.roi.join('/'), (_next, previous) => {
  if (previous === undefined || [first.value, last.value].join('/') === previous) [first.value, last.value] = props.analysis.roi
}, {immediate: true})
const points = ref<(number | string)[]>([])
const calibrationFile = ref<HTMLInputElement>()
const calibrationNotice = ref('')
const calibrationSaveDialog = ref<HTMLDialogElement>()
const calibrationName = ref('')
const savingCalibration = ref(false)
const calibrationSaveError = ref('')
let calibrationSaveTarget: {device: string; session: string; context: CalibrationContext} | null = null
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
function nameCalibration() {
  calibrationSaveError.value = ''
  const now = new Date(), pad = (n: number) => String(n).padStart(2, '0')
  calibrationName.value = `${props.course.short_code ?? props.course.id}_${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}_calibration`
  calibrationSaveTarget = {device: props.device.id, session: props.session,
    context: copyContext(props.calibrationContext)}
  calibrationSaveDialog.value?.showModal()
}
function saveCalibration() {
  const target = calibrationSaveTarget, title = calibrationName.value.trim()
  if (!target || !title || savingCalibration.value) return
  savingCalibration.value = true
  calibrationSaveError.value = ''
  calibrationNotice.value = ''
  emit('task', async () => {
    try {
      await props.act('cache_calibration', {device: target.device, calibration_context: target.context, title}, target.session)
      calibrationNotice.value = '刻度已保存到本场记录'
      calibrationSaveDialog.value?.close()
    } catch (error) {
      calibrationSaveError.value = errorMessage(error)
      throw error
    } finally { savingCalibration.value = false }
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
    <Teleport defer to="#spectrum-analysis-tools"><div class="menu-fields spectrum-selection">
      <label>当前谱 <select id="sample" :value="selectedValue" @change="selectSpectrum($event)">
        <option value="">本轮累计谱</option>
        <optgroup v-if="saved.length" label="已保存道谱"><option v-for="item in saved" :key="item.id" :value="item.id">{{ item.title }} · {{ fmt(item.exposure_s) }} s</option></optgroup>
        <optgroup v-if="legacySegments.length" label="历史记录"><option v-for="{segment, index: i} in legacySegments" :key="i" :value="'segment:' + i">{{ segmentName(segment, i) }}</option></optgroup>
      </select></label>
      <label>参考谱 <select id="reference" :value="referenceValue" @change="selectSpectrum($event, true)">
        <option value="">无参考谱</option>
        <optgroup v-if="saved.length" label="已保存道谱"><option v-for="item in saved" :key="item.id" :value="item.id">{{ item.title }} · {{ fmt(item.exposure_s) }} s</option></optgroup>
        <optgroup v-if="legacySegments.length" label="历史记录"><option v-for="{segment, index: i} in legacySegments" :key="i" :value="'segment:' + i">{{ segmentName(segment, i) }}</option></optgroup>
      </select></label>
      <label><input type="checkbox" id="energy" :disabled="!calibration" :checked="!!energyScale" @change="change('energy_axis', checked($event))"> MeV 横轴</label>
      <label><input type="checkbox" id="rate" :checked="analysis.rate_axis" @change="change('rate_axis', checked($event))"> 按曝光归一</label>
    </div></Teleport>
    <canvas id="plot" ref="plot" :aria-label="`道谱，显示 ${visibleRange[0]} 至 ${visibleRange[1]} 道。可在谱分析中输入选区道号。`" height="420"
      @pointerdown="startDrag" @lostpointercapture="cancelDrag" @pointerup="endDrag"></canvas>
    <div id="legend" class="legend"><span v-for="line in series" :key="line.label">{{ line.label }}</span></div>
    <p v-if="incompatible" class="notice">参考谱没有适用的能量刻度。切回道号轴可叠加两张谱。</p>
    <Teleport defer to="#spectrum-analysis-tools">
    <form id="roi" class="menu-fields" @submit.prevent="calculateRoi"><strong>选区 ROI</strong>
      <label>起道 <input id="first" v-model.number="first" type="number" min="0" :max="device.channels - 1" required step="1"></label>
      <label>止道 <input id="last" v-model.number="last" type="number" min="0" :max="device.channels - 1" required step="1"></label>
      <button>计算 ROI 重心</button>
    </form>
    <output id="roi-result" aria-live="polite">
      <template v-if="roiResult">
        <strong>ROI {{ roiResult.roi[0] }}–{{ roiResult.roi[1] }} 道 · 截止曝光 {{ fmt(roiResult.exposure_s) }} s</strong>
        <span>选区计数 {{ fmt(roiResult.readout.roi_counts ?? 0) }} 次</span>
        <span>重心 {{ roiResult.readout.centroid == null ? '无计数' : fmt(roiResult.readout.centroid) + ' 道' }}</span>
        <span>能量 {{ roiResult.readout.energy_MeV == null ? '—' : Number(roiResult.readout.energy_MeV.toFixed(5)) + ' MeV' }}</span>
      </template>
      <span v-else>选择道界后点击计算 ROI 重心。</span>
    </output>
    <details class="calibration-tools"><summary>两点能量刻度</summary>
      <form id="calibrate" class="menu-fields" @submit.prevent="applyCalibration">
        <label v-for="(field, i) in ['参考道 1', '能量 1 / MeV', '参考道 2', '能量 2 / MeV']" :key="field">{{ field }}
          <input :name="['c1','e1','c2','e2'][i]" v-model.number="points[i]" type="number" step="any" required></label>
        <button>应用刻度</button>
      </form>
      <div class="calibration-file-actions">
        <button id="load-calibration" type="button" @click="chooseCalibrationFile">载入刻度</button>
        <button id="save-calibration" type="button" :disabled="!calibration" @click="nameCalibration">保存刻度</button>
      </div>
      <input ref="calibrationFile" id="cal-file" type="file" accept=".json" hidden @cancel="fileTarget = null" @change="load">
      <output v-if="calibrationNotice" id="calibration-notice" role="status">{{ calibrationNotice }}</output>
    </details></Teleport>
    <dialog id="calibration-save-dialog" ref="calibrationSaveDialog" aria-labelledby="calibration-save-title"
      @cancel="savingCalibration && $event.preventDefault()">
      <h2 id="calibration-save-title">保存能量刻度</h2>
      <form class="calibration-name-form" @submit.prevent="saveCalibration">
        <label>名称 <input id="calibration-name" v-model="calibrationName" required autofocus :disabled="savingCalibration"></label>
        <p v-if="calibrationSaveError" id="calibration-save-error" role="alert">{{ calibrationSaveError }}</p>
        <div class="dialog-actions">
          <button id="calibration-save-cancel" type="button" :disabled="savingCalibration" @click="calibrationSaveDialog?.close()">取消</button>
          <button id="calibration-save-confirm" class="primary" :disabled="savingCalibration || !calibrationName.trim()">保存刻度</button>
        </div>
      </form>
    </dialog>
  </div>
</template>

<style scoped>
#spectrum { height:100%; min-height:0; display:flex; flex-direction:column; }
#spectrum #plot { display:block; width:100%; height:0; flex:1; min-height:240px; background:#fff; border:2px solid #71818e; border-radius:0; }
.legend { flex-shrink:0; padding:8px 0; }
.menu-fields { display:grid; gap:10px; }
.menu-fields label { display:grid; gap:4px; }
.spectrum-selection { grid-template-columns:repeat(2,minmax(0,1fr)); }
.spectrum-selection select { min-width:0; width:100%; }
.spectrum-selection details { grid-column:1/-1; }
.spectrum-selection label:has(input[type=checkbox]) { display:flex; align-items:center; gap:6px; }
#roi { grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px 10px; margin-top:12px; }
#roi strong, #roi button { grid-column:1/-1; }
#roi input { width:100%; min-width:0; }
.calibration-file-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
#calibration-notice { display: block; margin-top: 8px; font-size: 13px; }
#roi-result { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:4px; margin:8px 0 14px; font-size:13px; overflow-wrap:anywhere; }
#roi-result strong { grid-column:1/-1; }
.calibration-name-form { display:grid; gap:12px; }
.calibration-name-form label { display:grid; gap:6px; }
#calibration-name { width:100%; min-width:min(320px,70vw); }
</style>
