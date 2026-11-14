<script setup lang="ts">
import {computed, nextTick, ref, watch} from 'vue'
import {fmt, inputValue} from './display'
import {errorMessage} from './api'
import {deviceName, instrumentBinding, instrumentDevices} from './instrumentBindings'
import CounterPanel from './CounterPanel.vue'
import SpectrumPanel from './SpectrumPanel.vue'
import type {Act, State} from './types'

const props = defineProps<{state: State; act: Act}>()
const emit = defineEmits<{task: [fn: () => Promise<void>]; acquisitionSettings: []; loadMeasurement: [device: string, source: 'cache' | 'file']}>()
const mode = ref('manual'), duration = ref(10), countLimit = ref(100), windowSize = ref(1)
const savedNotice = ref('')
const tool = ref<'acquisition' | 'analysis'>('acquisition')
const clearBusy = ref(false)
const clearDialog = ref<HTMLDialogElement>()
const clearing = ref<{session: string; device: string; context: string; label: string; token: number | string; exposure: number; component?: string; exposures?: Record<string, number>} | null>(null)
const selector = ref<HTMLSelectElement>()
const workspace = ref<HTMLElement>()
const controlsWidth = ref(360)
let resizeStart: {x: number; width: number} | null = null
function resizeControls(event: PointerEvent) {
  resizeStart = {x: event.clientX, width: controlsWidth.value}
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function moveControls(event: PointerEvent) {
  if (resizeStart) controlsWidth.value = Math.max(280, Math.min(560, resizeStart.width + resizeStart.x - event.clientX))
}
function resizeKey(event: KeyboardEvent) {
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault()
    controlsWidth.value = Math.max(280, Math.min(560, controlsWidth.value + (event.key === 'ArrowLeft' ? 20 : -20)))
  }
}
const durationInput = ref<HTMLInputElement>()
const saveDialog = ref<HTMLDialogElement>()
const measurementName = ref('')
const saving = ref(false)
const saveError = ref('')
let saveContext: {session: string; component: string | undefined; device: string; acquisitions: Record<string, number | null>} | null = null
function defaultName() {
  const now = new Date(), pad = (n: number) => String(n).padStart(2, '0')
  return `${props.state.definition.short_code ?? props.state.experiment}_${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
}
function nameMeasurement() {
  saveError.value = ''
  saveContext = {session: props.state.id, component: binding.value.component?.id, device: props.state.device,
    acquisitions: Object.fromEntries(binding.value.devices.map(d => [d.id, props.state.instruments[d.id]?.acquisition ?? null]))}
  measurementName.value = defaultName()
  saveDialog.value?.showModal()
}
function saveNamedMeasurement() {
  const name = measurementName.value.trim(), context = saveContext
  if (!name || saving.value || !context) return
  saving.value = true
  emit('task', async () => {
    try {
      await props.act('snapshot_group', {component: context.component, device: context.device, acquisitions: context.acquisitions, title: name}, context.session)
      savedNotice.value = '已保存'
      saveDialog.value?.close()
    } catch (error) { saveError.value = errorMessage(error) }
    finally { saving.value = false }
  })
}
defineExpose({focusDevice: () => (selector.value ?? workspace.value)?.focus()})
const instrument = computed(() => props.state.definition.devices.find(d => d.id === props.state.device)!)
const segment = computed(() => {
  const segments = props.state.product.segments
  if (props.state.selected !== null) return segments[props.state.selected]
  for (let i = segments.length - 1; i >= 0; i--) if (instrument.value.id in segments[i].readings) return segments[i]
})
const independent = computed(() => !!props.state.definition.outputs?.length)
const binding = computed(() => instrumentBinding(props.state.definition, instrument.value.id))
const group = computed(() => binding.value.devices.length > 1 ? binding.value.component : undefined)
const targets = computed(() => instrumentDevices(props.state.definition))
const chassis = computed(() => props.state.definition.components.filter(p => p.kind === 'instrument' && p.device))
const groupRunning = computed(() => group.value ? group.value.devices!.some(id => props.state.gates[id]) : props.state.running)
const groupActions = computed(() => group.value ? props.state.instrument_groups?.[group.value.id] : undefined)
const hasExposure = computed(() => group.value ? group.value.devices!.some(id => (props.state.instruments[id]?.exposure_s ?? 0) > 0) : !!props.state.instrument?.readable_exposure_s)
const status = computed(() => group.value ? groupRunning.value ? '采集中' : hasExposure.value ? '暂停' : '等待开始' : props.state.running ? '采集中' : props.state.instrument?.clearing ? '清空确认中'
  : ['time_limit', 'count_limit'].includes(props.state.instrument?.stop_reason ?? '') ? '到限暂停'
  : props.state.instrument?.acquisition ? '手动暂停' : '等待开始')
watch(() => props.state.device, () => {
  const target = props.state.instrument
  mode.value = target?.count_limit != null ? 'count' : target?.duration_s != null || !independent.value ? 'timed' : 'manual'
  duration.value = target?.duration_s ?? 10
  countLimit.value = target?.count_limit ?? 100
  windowSize.value = target?.window_s ?? 1
  savedNotice.value = ''
}, {immediate: true})
function run(name: string, fields: Record<string, unknown> = {}) {
  const session = props.state.id
  emit('task', () => props.act(name, fields, session))
}
async function start() {
  if (mode.value === 'timed' && durationInput.value && !durationInput.value.validity.valid) {
    emit('acquisitionSettings')
    await nextTick()
    durationInput.value.focus()
    durationInput.value.reportValidity()
    return
  }
  const device = instrument.value.id, session = props.state.id, fields = acquisitionTargets()
  emit('task', async () => {
    if (group.value) {
      await props.act('instrument_group_config', {component: group.value.id, duration_s: fields.duration_s, count_limit: fields.count_limit}, session)
      await props.act('start_group', {component: group.value.id}, session)
    } else if (independent.value) {
      await props.act('instrument_config', {device, ...fields}, session)
      await props.act('start', {device}, session)
    } else await props.act('start', {duration: mode.value === 'manual' ? null : duration.value}, session)
  })
}
function acquisitionTargets() { return {duration_s: mode.value === 'timed' ? duration.value : null,
  count_limit: mode.value === 'count' ? countLimit.value : null, window_s: windowSize.value} }
function configureTarget() {
  if (group.value) run('instrument_group_config', {component: group.value.id, duration_s: acquisitionTargets().duration_s, count_limit: acquisitionTargets().count_limit})
  else run('instrument_config', {device: instrument.value.id, ...(props.state.running ? {window_s: windowSize.value} : acquisitionTargets())})
}
function pause() { group.value ? run('stop_group', {component: group.value.id,
  gate_cycles: Object.fromEntries(group.value.devices!.map(id => [id, props.state.instruments[id].cycle]))})
  : run('stop', {device: instrument.value.id, acquisition: props.state.active_acquisition, cycle: props.state.instrument?.cycle}) }
watch(() => [props.state.id, props.state.clear_confirmation] as const, async () => {
  const request = props.state.clear_confirmation as (State['clear_confirmation'] & {device?: string})
  if (!request) {
    clearDialog.value?.close()
    clearing.value = null
    return
  }
  const device = request.device ?? props.state.device
  const context = clearing.value?.token === request.token ? clearing.value.context : props.state.device
  if (clearing.value?.token !== request.token) measurementName.value = defaultName()
  clearing.value = {session: props.state.id, device, context, token: request.token, exposure: request.exposure_s ?? 0, component: request.component, exposures: request.exposures,
    label: props.state.definition.devices.find(d => d.id === device)?.label ?? device}
  await nextTick()
  if (!clearDialog.value?.open) clearDialog.value?.showModal()
}, {immediate: true, deep: true, flush: 'post'})
function finishClear(choice: 'save' | 'discard' | 'cancel') {
  const target = clearing.value
  if (!target || clearBusy.value) return
  clearBusy.value = true
  emit('task', async () => {
    try {
      if (target.component) await props.act('finish_clear_group', {device: target.context, component: target.component, token: target.token, choice, ...(choice === 'save' ? {title: measurementName.value.trim()} : {})}, target.session)
      else await props.act('finish_clear', {device: target.device, token: target.token, choice}, target.session)
      clearDialog.value?.close()
      clearing.value = null
    } finally { clearBusy.value = false }
  })
}
</script>

<template>
  <section id="instrument" ref="workspace" tabindex="-1" class="page">
    <nav v-if="chassis.length > 1" class="chassis-navigation" aria-label="仪器"><button v-for="part in chassis" :key="part.id" :data-instrument="part.id" :aria-current="binding.component?.id === part.id ? 'true' : undefined" @click="run('device', {device: part.device})">{{ part.label }}</button></nav>
    <div class="instrument-workspace" :class="{'spectrum-layout': instrument.kind === 'spectrum'}" :style="{'--controls-width': controlsWidth + 'px'}">
    <main class="instrument-display">
    <SpectrumPanel v-if="instrument.kind === 'spectrum'" :key="instrument.id" :course="state.definition" :device="instrument" :segments="state.product.segments"
      :index="state.selected" :analysis="state.analysis" :calibration="state.calibration" :calibration-context="state.calibration_context"
      :reference-calibration="state.reference_calibration"
      :saved-measurements="state.saved_measurements" :selected-item-id="state.selected_item_id" :reference-item-id="state.reference_item_id"
      :selected-observation="state.selected_observation" :reference-observation="state.reference_observation"
      :current-acquisition="state.instrument?.acquisition"
      :instrument="state.instrument"
      :readout="state.readout" :roi-result="state.roi_result" :roi-context="state.roi_context" :session="state.id" :act="act" @task="emit('task', $event)"/>
    <CounterPanel v-else-if="instrument.kind === 'counter'" :course="state.definition" :device="instrument" :segments="state.product.segments"
      :readonly="state.readonly" :state="state" @window-change="(device, seconds) => run('window_config', {component: group?.id, device, window_s: seconds})"/>
    <p v-if="state.readout_error" id="readout-error" class="notice" role="status">{{ state.readout_error }}</p>
    <div v-if="instrument.kind !== 'spectrum' && instrument.kind !== 'counter'" id="other">{{ segment ? instrument.label + '　' + segment.readings[instrument.id].join(' · ') : '等待读数' }}</div>
    </main>
    <div v-if="instrument.kind === 'spectrum'" class="controls-divider" role="separator" aria-label="调整仪器操作栏宽度" aria-orientation="vertical" :aria-valuenow="controlsWidth" :aria-valuemin="280" :aria-valuemax="560" tabindex="0" @pointerdown="resizeControls" @pointermove="moveControls" @pointerup="resizeStart = null" @lostpointercapture="resizeStart = null" @keydown="resizeKey"></div>
    <aside class="instrument-controls" aria-label="仪器操作">
      <label v-if="!group && state.definition.devices.length > 1" class="device-select">操作仪器
        <select ref="selector" id="device" :value="state.device" @change="run('device', {device: inputValue($event)})">
          <option v-for="d in targets" :key="d.id" :value="d.id">{{ deviceName(state.definition, d.id) }}</option>
        </select>
      </label>
      <div v-if="!group" class="instrument-status">
        <strong id="gate-status" :data-running="groupRunning">{{ status }}</strong>
        <dl v-if="!group"><div><dt>累计实际曝光</dt><dd id="exposure">{{ fmt(state.exposure_s ?? 0) }} <span>s</span></dd></div>
          <div><dt>可读计数</dt><dd id="current-readout">{{ fmt(state.instrument?.counts.reduce((a, b) => a + b, 0) ?? 0) }} <span>次</span></dd></div>
          <div class="target-readout"><dt>{{ state.instrument?.count_limit != null ? '目标计数' : state.instrument?.duration_s != null ? '目标曝光' : '采集方式' }}</dt><dd>{{ state.instrument?.count_limit != null ? fmt(state.instrument.count_limit) + ' 次' : state.instrument?.duration_s != null ? fmt(state.instrument.duration_s) + ' s' : '普通' }}</dd></div>
          <div class="remaining-readout"><template v-if="state.instrument?.duration_s != null"><dt>剩余曝光</dt><dd id="remaining">{{ state.remaining_s == null ? '—' : fmt(state.remaining_s) + ' s' }}</dd></template></div>
        </dl>
      </div>
      <form id="acquisition" class="fixed-acquisition" @submit.prevent="start">
        <button class="primary" id="start" :disabled="(group ? !groupActions?.can_start : state.running) || state.readonly || state.instrument?.clearing">{{ group ? hasExposure ? '继续测量' : '开始测量' : state.instrument?.readable_exposure_s ? '继续采集' : '开始采集' }}</button>
        <button type="button" id="stop" :disabled="(group ? !groupActions?.can_stop : !state.running) || state.readonly" @click="pause">{{ group ? '暂停测量' : '暂停采集' }}</button>
      </form>
      <div v-if="instrument.kind === 'spectrum'" class="instrument-tabs" role="tablist" aria-label="仪器工具">
        <button role="tab" :aria-selected="tool === 'acquisition'" @click="tool = 'acquisition'">采集</button>
        <button role="tab" :aria-selected="tool === 'analysis'" @click="tool = 'analysis'">谱分析</button>
      </div>
      <div v-show="tool === 'acquisition' || instrument.kind !== 'spectrum'" class="acquisition-fields">
        <div class="snapshot-actions"><button id="save-current" :disabled="state.readonly || !hasExposure || state.instrument?.clearing" @click="nameMeasurement">保存</button>
          <button id="clear" :disabled="state.readonly || state.instrument?.clearing" @click="run('begin_clear_group', {component: binding.component?.id, device: state.device})">清空</button></div>
        <output id="snapshot-notice" role="status">{{ savedNotice }}</output>
        <label>采集方式 <select id="mode" v-model="mode" :disabled="groupRunning || state.readonly"><option value="manual">普通</option><option value="timed">定时</option><option value="count">定计数</option></select></label>
        <label v-if="mode === 'timed'">目标曝光 / s <input ref="durationInput" id="duration" v-model.number="duration" type="number" min="0.000001" step="any" required :disabled="groupRunning || state.readonly"></label>
        <label v-if="mode === 'count'">目标计数 / 次 <input id="count-limit" v-model.number="countLimit" type="number" min="1" step="1" :disabled="groupRunning || state.readonly"></label>
        <label v-if="!group">统计窗 / s <input id="window-size" v-model.number="windowSize" type="number" min="0.000001" step="any" :disabled="state.readonly"></label>
        <button id="apply-acquisition" :disabled="state.readonly" @click="configureTarget">应用采集设置</button>
        <p v-if="mode === 'count'" class="notice">在完整统计窗末判断目标，计数可能超过目标。</p>
        <fieldset class="load-measurement"><legend>载入测量数据</legend>
          <button :disabled="state.readonly || state.instrument?.clearing" @click="emit('loadMeasurement', instrument.id, 'cache')">从本场实验记录选择</button>
          <button :disabled="state.readonly || state.instrument?.clearing" @click="emit('loadMeasurement', instrument.id, 'file')">从文件选择</button>
        </fieldset>
      </div>
      <div id="spectrum-analysis-tools" v-show="tool === 'analysis'" class="spectrum-analysis-tools"></div>
    </aside>
    </div>
    <dialog id="measurement-save" ref="saveDialog" aria-labelledby="measurement-save-title">
      <h2 id="measurement-save-title">保存测量</h2>
      <form @submit.prevent="saveNamedMeasurement">
        <label>名称 <input id="measurement-name" v-model="measurementName" required autofocus></label>
        <p v-if="saveError" id="measurement-save-error" role="alert">{{ saveError }}</p>
        <div class="dialog-actions"><button type="button" :disabled="saving" @click="saveDialog?.close()">取消</button><button id="measurement-save-confirm" class="primary" :disabled="saving || !measurementName.trim()">保存</button></div>
      </form>
    </dialog>
    <dialog id="clear-confirm" ref="clearDialog" @cancel.prevent="finishClear('cancel')">
      <h2>清空前要保存当前读数吗？</h2>
      <template v-if="clearing?.component"><p>本次清空整台仪器的读数。</p><p v-for="(seconds, device) in clearing.exposures" :key="device">{{ deviceName(state.definition, String(device)) }}：{{ fmt(seconds) }} s</p></template>
      <p v-else>{{ clearing?.label }}，实际可读曝光 {{ fmt(clearing?.exposure ?? 0) }} s。</p>
      <label>保存名称 <input id="clear-name" v-model="measurementName"></label>
      <div class="dialog-actions"><button id="clear-cancel" :disabled="clearBusy" autofocus @click="finishClear('cancel')">取消</button>
        <button id="clear-discard" :disabled="clearBusy" @click="finishClear('discard')">否，直接清空</button>
        <button id="clear-save" :disabled="clearBusy || !measurementName.trim()" class="primary" @click="finishClear('save')">是，保存并清空</button></div>
    </dialog>
  </section>
</template>

<style scoped>
.instrument-workspace { display:grid; grid-template-columns:minmax(0,1fr) 310px; gap:20px; align-items:start; height:calc(100dvh - 72px); }
.instrument-display { min-width:0; }
.spectrum-layout { grid-template-columns:minmax(0,1fr) 8px var(--controls-width); gap:0; }
.spectrum-layout .instrument-display { height:100%; padding-right:12px; }
.controls-divider { height:100%; cursor:col-resize; touch-action:none; border-left:1px solid #c5ccd3; background:#f7f9fa; }
.controls-divider:hover { background:#dce5ed; }
.instrument-controls { background:#f0f2f4; border-left:1px solid #c5ccd3; padding:16px; color:#202c36; height:100%; min-height:0; display:flex; flex-direction:column; overflow:hidden; }
.instrument-controls > :not(.acquisition-fields):not(.spectrum-analysis-tools) { flex-shrink:0; }
.acquisition-fields, .spectrum-analysis-tools { overflow:auto; min-height:0; padding-right:4px; }
.instrument-status dl { margin:12px 0; font-size:14px; }
.instrument-status dl > div { display:flex; justify-content:space-between; min-height:27px; gap:8px; }
dt { color:#52616d; } dd { margin:0; font-variant-numeric:tabular-nums; white-space:nowrap; }
#gate-status { display:flex; align-items:center; gap:8px; }
#gate-status::before { content:''; width:9px; height:9px; border-radius:50%; background:#76818a; }
#gate-status[data-running="true"]::before { background:#197449; }
.fixed-acquisition { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:14px 0 18px; }
.fixed-acquisition button { min-width:0; white-space:nowrap; }
.instrument-tabs { display:flex; border-bottom:1px solid #b5c0c9; margin-bottom:16px; }
.instrument-tabs button { flex:1; border:0; border-radius:0; background:transparent; border-bottom:3px solid transparent; }
.instrument-tabs button[aria-selected="true"] { border-color:#2267a8; color:#17578f; font-weight:700; }
.acquisition-fields { display:grid; gap:12px; }
.acquisition-fields label { display:grid; grid-template-columns:1fr 135px; gap:8px; align-items:center; }
.snapshot-actions { display:flex; gap:12px; }
#snapshot-notice { min-height:18px; font-size:13px; }
.load-measurement { border:0; border-top:1px solid #c5ccd3; margin:8px 0 0; padding:12px 0 0; display:grid; gap:8px; }
.load-measurement legend { font-size:14px; font-weight:600; }
.device-select { display:grid; gap:6px; margin-bottom:12px; }
.chassis-navigation { display:flex; gap:8px; margin-bottom:8px; }
.chassis-navigation [aria-current=true] { font-weight:700; border-color:#2956a1; }
</style>
