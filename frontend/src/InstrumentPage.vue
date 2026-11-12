<script setup lang="ts">
import {computed, nextTick, ref, watch} from 'vue'
import {fmt, inputValue} from './display'
import CounterPanel from './CounterPanel.vue'
import CounterAnalysis from './CounterAnalysis.vue'
import SpectrumPanel from './SpectrumPanel.vue'
import type {Act, State} from './types'

const props = defineProps<{state: State; act: Act}>()
const emit = defineEmits<{task: [fn: () => Promise<void>]; acquisitionSettings: []}>()
const mode = ref('manual'), duration = ref(10), countLimit = ref(100), windowSize = ref(1)
const savedNotice = ref('')
const clearDialog = ref<HTMLDialogElement>()
const clearing = ref<{session: string; device: string; label: string; token: number; exposure: number} | null>(null)
const selector = ref<HTMLSelectElement>()
const durationInput = ref<HTMLInputElement>()
defineExpose({focusDevice: () => selector.value?.focus()})
const instrument = computed(() => props.state.definition.devices.find(d => d.id === props.state.device)!)
const segment = computed(() => {
  const segments = props.state.product.segments
  if (props.state.selected !== null) return segments[props.state.selected]
  for (let i = segments.length - 1; i >= 0; i--) if (instrument.value.id in segments[i].readings) return segments[i]
})
const input = computed(() => props.state.definition.outputs?.find(o => o.id === instrument.value.input))
const independent = computed(() => !!props.state.definition.outputs?.length)
const status = computed(() => props.state.running ? '采集中' : props.state.instrument?.clearing ? '清空确认中'
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
function changeAnalysis(fields: Record<string, unknown>) {
  run('analysis', {device: instrument.value.id, ...fields})
}
async function start() {
  if (mode.value === 'timed' && durationInput.value && !durationInput.value.validity.valid) {
    emit('acquisitionSettings')
    await nextTick()
    durationInput.value.focus()
    durationInput.value.reportValidity()
    return
  }
  const device = instrument.value.id, session = props.state.id, fields = targets()
  emit('task', async () => {
    if (independent.value) {
      await props.act('instrument_config', {device, ...fields}, session)
      await props.act('start', {device}, session)
    } else await props.act('start', {duration: mode.value === 'manual' ? null : duration.value}, session)
  })
}
function targets() { return {duration_s: mode.value === 'timed' ? duration.value : null,
  count_limit: mode.value === 'count' ? countLimit.value : null, window_s: windowSize.value} }
function configureTarget() { run('instrument_config', {device: instrument.value.id, ...targets()}) }
function saveCurrent() {
  const device = instrument.value.id, session = props.state.id
  emit('task', async () => {
    await props.act('snapshot', {device}, session)
    savedNotice.value = '当前读数已保存到本场记录，仪器继续保持原状态。'
  })
}
function requestClear() {
  const device = instrument.value.id, label = instrument.value.label, session = props.state.id
  emit('task', async () => {
    await props.act('begin_clear', {device}, session)
    await nextTick()
    const request = props.state.clear_confirmation
    if (request && props.state.id === session && props.state.device === device) {
      clearing.value = {device, label, session, token: request.token, exposure: request.exposure_s}
      await nextTick()
      clearDialog.value?.showModal()
    }
  })
}
function finishClear(choice: 'save' | 'discard' | 'cancel') {
  const target = clearing.value!
  emit('task', async () => {
    try { await props.act('finish_clear', {device: target.device, token: target.token, choice}, target.session) }
    finally { clearDialog.value?.close(); clearing.value = null }
  })
}
</script>

<template>
  <section id="instrument" class="page">
    <Teleport v-if="instrument.kind === 'spectrum' && independent" defer to="#panel-analysis">
      <details id="acquisition-tools" class="acquisition-tools"><summary>采集设置</summary><div class="menu-fields">
        <label>采集方式 <select id="instrument-mode" v-model="mode" :disabled="state.running || state.readonly"><option value="manual">普通</option><option value="timed">定时</option><option value="count">定计数</option></select></label>
        <label v-if="mode === 'timed'">累计曝光 / s <input id="instrument-duration" v-model.number="duration" type="number" min="0.000001" step="any" :disabled="state.running || state.readonly"></label>
        <label v-if="mode === 'count'">累计计数目标 <input id="instrument-count-limit" v-model.number="countLimit" type="number" min="1" step="1" :disabled="state.running || state.readonly"></label>
        <label>统计窗 / s <input v-model.number="windowSize" type="number" min="0.000001" step="any" :disabled="state.running || state.readonly"></label>
        <button id="instrument-apply-acquisition" :disabled="state.running || state.readonly" @click="configureTarget">应用采集设置</button>
      </div></details>
    </Teleport>
    <Teleport defer to="#acquisition-settings"><div class="menu-fields">
      <label>采集方式 <select id="mode" v-model="mode" :disabled="state.running || state.readonly"><option value="manual">普通</option><option value="timed">定时</option><option v-if="independent" value="count">定计数</option></select></label>
      <label id="duration-row" v-show="mode === 'timed'">曝光 / s <input ref="durationInput" id="duration" v-model.number="duration" type="number" min="0.000001" step="any"
        :disabled="state.running || state.readonly || mode === 'manual'" :required="mode === 'timed'"></label>
      <label v-if="mode === 'count'">累计计数目标 <input id="count-limit" v-model.number="countLimit" type="number" min="1" step="1" :disabled="state.running || state.readonly"></label>
      <label v-if="independent">统计窗 / s <input id="window-size" v-model.number="windowSize" type="number" min="0.000001" step="any" :disabled="state.running || state.readonly"></label>
      <button v-if="independent" id="apply-acquisition" :disabled="state.running || state.readonly" @click="configureTarget">应用采集设置</button>
      <p v-if="mode === 'count'" class="notice">计数在完整统计窗末判断，实得计数可能超过目标。</p>
    </div></Teleport>
    <div class="instrument-head">
      <label class="device-select"><select ref="selector" id="device" aria-label="测量设备" :value="state.device" @change="run('device', {device: inputValue($event)})">
        <option v-for="d in state.definition.devices" :key="d.id" :value="d.id">{{ d.label }}{{ state.definition.devices.length > 1 ? ' · ' + d.id : '' }}</option>
      </select></label>
      <span v-if="instrument.kind === 'spectrum'" class="device-range">{{ fmt(instrument.channels) }} 道</span>
      <span v-if="input" class="input-status">{{ input.label }} · {{ state.output_enabled[input.id] ? '输入开启' : '输入关闭' }}</span>
      <button v-if="independent" id="instrument-settings" @click="emit('acquisitionSettings')">采集设置</button>
      <form id="acquisition" @submit.prevent="start">
      <button class="primary" id="start" :disabled="state.running || state.readonly || state.instrument?.clearing">{{ independent && state.instrument?.acquisition ? '继续采集' : '开始采集' }}</button>
      <button type="button" id="stop" :disabled="!state.running || state.readonly" @click="run('stop', {device: instrument.id, acquisition: state.active_acquisition, cycle: state.instrument?.cycle})">{{ independent ? '暂停采集' : '停止采集' }}</button>
      <output v-if="state.exposure_s !== null" id="exposure">实际曝光 {{ fmt(state.exposure_s) }} s</output>
      <output v-if="state.instrument" id="current-readout">当前可读 {{ fmt(state.instrument.counts.reduce((a, b) => a + b, 0)) }} 次 / {{ fmt(state.instrument.readable_exposure_s) }} s</output>
      <output id="remaining">{{ state.remaining_s == null ? '' : '剩余 ' + fmt(state.remaining_s) + ' s' }}</output>
      </form>
    </div>
    <div v-if="independent" class="instrument-actions">
      <span id="gate-status" :data-running="state.running">{{ status }}</span>
      <button id="save-current" :disabled="state.readonly || !state.instrument?.readable_exposure_s || state.instrument?.clearing" @click="saveCurrent">保存</button>
      <button id="clear" :disabled="state.readonly || state.instrument?.clearing" @click="requestClear">清空</button>
      <output id="cache-count">本场已保存 {{ state.snapshots.filter(s => s.device === instrument.id).length + state.imported_items.filter(s => s.device === instrument.id).length }} 份</output>
    </div>
    <span v-else id="gate-status" :data-running="state.running">{{ state.running ? '采集中' : '采集门关闭' }}</span>
    <p v-if="savedNotice" id="snapshot-notice" role="status">{{ savedNotice }}</p>
    <SpectrumPanel v-if="instrument.kind === 'spectrum'" :key="instrument.id" :course="state.definition" :device="instrument" :segments="state.product.segments"
      :index="state.selected" :analysis="state.analysis" :calibration="state.calibration" :calibration-context="state.calibration_context"
      :reference-calibration="state.reference_calibration"
      :current-acquisition="state.instrument?.acquisition"
      :instrument="state.instrument"
      :readout="state.readout" :session="state.id" :act="act" @task="emit('task', $event)"/>
    <CounterPanel v-else-if="instrument.kind === 'counter'" :course="state.definition" :device="instrument" :segments="state.product.segments"
      :readonly="state.readonly"/>
    <CounterAnalysis v-if="instrument.kind === 'counter'" :course="state.definition" :device="instrument" :segments="state.product.segments"
      :background="state.analysis.background" :readouts="state.counter_analysis" @background="changeAnalysis({background: $event})"/>
    <p v-if="state.readout_error" id="readout-error" class="notice" role="status">{{ state.readout_error }}</p>
    <div v-if="instrument.kind !== 'spectrum' && instrument.kind !== 'counter'" id="other">{{ segment ? instrument.label + '　' + segment.readings[instrument.id].join(' · ') : '等待读数' }}</div>
    <details v-if="state.snapshots.length" id="saved-readings">
      <summary>本场已保存读数</summary>
      <ul><li v-for="s in state.snapshots" :key="s.id" :data-snapshot="s.id">记录 {{ s.id }} · {{ state.definition.devices.find(d => d.id === s.device)?.label }} · {{ fmt(s.exposure_s) }} s · {{ fmt(s.counts) }} 次</li></ul>
    </details>
    <dialog id="clear-confirm" ref="clearDialog" @cancel.prevent="finishClear('cancel')">
      <h2>清空前要保存当前读数吗？</h2>
      <p>{{ clearing?.label }}，实际可读曝光 {{ fmt(clearing?.exposure ?? 0) }} s。其他仪器继续采集。</p>
      <div class="dialog-actions"><button id="clear-cancel" autofocus @click="finishClear('cancel')">取消</button>
        <button id="clear-discard" @click="finishClear('discard')">否，直接清空</button>
        <button id="clear-save" class="primary" @click="finishClear('save')">是，保存并清空</button></div>
    </dialog>
  </section>
</template>
