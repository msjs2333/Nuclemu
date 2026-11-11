<script setup lang="ts">
import {computed, nextTick, ref} from 'vue'
import {describe, fmt, inputValue} from './display'
import CounterPanel from './CounterPanel.vue'
import SpectrumPanel from './SpectrumPanel.vue'
import type {Act, State} from './types'

const props = defineProps<{state: State; act: Act}>()
const emit = defineEmits<{task: [fn: () => Promise<void>]; acquisitionSettings: []}>()
const mode = ref('timed'), duration = ref(10)
const selector = ref<HTMLSelectElement>()
const durationInput = ref<HTMLInputElement>()
defineExpose({focusDevice: () => selector.value?.focus()})
const instrument = computed(() => props.state.definition.devices.find(d => d.id === props.state.device)!)
const segment = computed(() => props.state.product.segments[props.state.selected ?? props.state.product.segments.length - 1])
const settings = computed(() => instrument.value.kind === 'spectrum' ? props.state.spectrum_settings ?? segment.value?.settings ?? props.state.settings : props.state.settings)
function run(name: string, fields: Record<string, unknown> = {}) {
  emit('task', () => props.act(name, fields))
}
async function start() {
  if (mode.value === 'timed' && durationInput.value && !durationInput.value.validity.valid) {
    emit('acquisitionSettings')
    await nextTick()
    durationInput.value.focus()
    durationInput.value.reportValidity()
    return
  }
  run('start', {duration: mode.value === 'manual' ? null : duration.value})
}
</script>

<template>
  <section id="instrument" class="page">
    <Teleport defer to="#acquisition-settings"><div class="menu-fields">
      <label>采集方式 <select id="mode" v-model="mode" :disabled="state.running || state.readonly"><option value="timed">定时</option><option value="manual">手动</option></select></label>
      <label id="duration-row" v-show="mode === 'timed'">曝光 / s <input ref="durationInput" id="duration" v-model.number="duration" type="number" min="0.000001" step="any"
        :disabled="state.running || state.readonly || mode === 'manual'" :required="mode === 'timed'"></label>
    </div></Teleport>
    <div class="instrument-head">
      <label class="device-select"><select ref="selector" id="device" aria-label="测量设备" :value="state.device" @change="run('device', {device: inputValue($event)})">
        <option v-for="d in state.definition.devices" :key="d.id" :value="d.id">{{ d.label }}{{ state.definition.devices.length > 1 ? ' · ' + d.id : '' }}</option>
      </select></label>
      <form id="acquisition" @submit.prevent="start">
      <button class="primary" id="start" :disabled="state.running || state.readonly">开始采集</button>
      <button type="button" id="stop" :disabled="!state.running || state.readonly" @click="run('stop')">停止采集</button>
      <output id="remaining">{{ state.remaining_s == null ? '' : '剩余 ' + fmt(state.remaining_s) + ' s' }}</output>
      </form>
    </div>
    <SpectrumPanel v-if="instrument.kind === 'spectrum'" :key="instrument.id" :device="instrument" :segments="state.product.segments"
      :index="state.selected" :analysis="state.analysis" :calibration="state.calibration" :readout="state.readout" :act="act" @task="emit('task', $event)"/>
    <CounterPanel v-else-if="instrument.kind === 'counter'" :course="state.definition" :device="instrument" :segments="state.product.segments"
      :background="state.analysis.background" @background="run('analysis', {background: $event})"/>
    <div v-else id="other">{{ segment ? instrument.label + '　' + segment.readings[instrument.id].join(' · ') : '等待读数' }}</div>
    <p id="conditions" class="instrument-conditions">{{ instrument.kind === 'spectrum' && segment ? '所选谱工况' : '装置工况' }}　{{ describe(state.definition, settings) }}</p>
  </section>
</template>
