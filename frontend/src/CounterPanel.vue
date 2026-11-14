<script setup lang="ts">
import {computed, nextTick, reactive, watch} from 'vue'
import {fmt, describe, exposure} from './display'
import {counterWindowName, deviceName, instrumentBinding} from './instrumentBindings'
import type {Course, Device, Segment, State} from './types'

type Window = {index?: number; window?: number; number?: number; exposure_s?: number; start_exposure_s?: number; end_exposure_s?: number; counts: number | number[]; complete?: boolean; parts?: {start_s: number; end_s: number; settings: Record<string, number>}[]}
type CounterState = State & {instruments?: Record<string, {windows?: Window[]; readable_exposure_s: number; counts: number[]; window_prefix_exposure_s?: number; window_prefix_counts?: number[]}>; counter_windows?: Record<string, Window[]>}
const props = defineProps<{course: Course; device: Device; segments: Segment[]; readonly: boolean; state?: CounterState}>()
const emit = defineEmits<{windowChange: [device: string, seconds: number]}>()
const binding = computed(() => instrumentBinding(props.course, props.device.id))
const group = computed(() => binding.value.devices.length > 1 ? binding.value.component : undefined)
const panels = computed(() => binding.value.devices.filter(d => d.kind === 'counter').map(device => {
  const instrument = props.state?.instruments?.[device.id]
  const windows = props.state?.counter_windows?.[device.id] ?? instrument?.windows ?? []
  const last = windows.at(-1)
  const latest = last?.complete === false ? windows.at(-2) : last
  return {device, instrument, label: counterWindowName(props.course, device.id) ?? deviceName(props.course, device.id), windows, latest, running: props.state?.gates[device.id] ?? false}
}))
function windowExposure(window: Window) { return window.exposure_s ?? ((window.end_exposure_s ?? 0) - (window.start_exposure_s ?? 0)) }
function counts(window: Window) { return Array.isArray(window.counts) ? window.counts.reduce((a, b) => a + b, 0) : window.counts }
const windowDraft = reactive<Record<string, string>>({})
function configureWindow(device: string, event: Event) {
  const input = event.target as HTMLInputElement
  if (input.reportValidity()) emit('windowChange', device, Number(input.value))
}
watch(() => props.state?.instruments, instruments => {
  for (const [device, draft] of Object.entries(windowDraft)) {
    const state = instruments?.[device]
    if (state && Number(draft) === (state.next_window_s ?? state.window_s)) delete windowDraft[device]
  }
})
const ledgers = new Map<string, HTMLElement>(), following = new Map<string, boolean>()
function follow(device: string, event: Event) {
  const box = event.target as HTMLElement
  following.set(device, box.scrollHeight - box.scrollTop - box.clientHeight < 24)
}
watch(() => panels.value.map(p => p.windows.length).join('/'), async () => {
  await nextTick()
  for (const [id, box] of ledgers) if (following.get(id) !== false) box.scrollTop = box.scrollHeight
})
</script>

<template>
  <div id="counter" class="counter-console" :class="{'single-counter': panels.length === 1}">
    <div v-if="!course.outputs?.length" class="legacy-readings">
      <p>以下为已记录的测量段，原文件未提供独立统计窗。</p>
      <table id="counts"><thead><tr><th>记录</th><th>计数 / 次</th><th>实际曝光 / s</th><th>工况</th></tr></thead>
        <tbody><tr v-for="(segment, index) in segments.filter(s => device.id in s.readings)" :key="index"><td>{{ index + 1 }}</td><td>{{ segment.readings[device.id].reduce((a,b) => a+b,0) }}</td><td>{{ fmt(exposure(segment)) }}</td><td>{{ describe(course, segment.settings) }}</td></tr></tbody>
      </table>
    </div>
    <section v-for="panel in course.outputs?.length ? panels : []" :key="panel.device.id" class="counter-window" :data-device="panel.device.id" :aria-label="panel.label">
      <header><h2>{{ panel.label }}</h2><span class="window-state" :data-running="panel.running">{{ panel.running ? '采集中' : ['time_limit', 'count_limit'].includes(state?.instruments[panel.device.id]?.stop_reason ?? '') ? '到限暂停' : state?.instruments[panel.device.id]?.acquisition ? '暂停' : '等待开始' }}</span></header>
      <p class="window-caption">最近完整窗</p>
      <div class="window-reading"><strong>{{ panel.latest ? counts(panel.latest).toLocaleString('zh-CN') : '—' }}</strong><span>次</span>
        </div>
      <p v-if="panel.instrument && panel.instrument.readable_exposure_s > 0" class="counter-total">累计读数：<strong>{{ panel.instrument.counts.reduce((a, b) => a + b, 0).toLocaleString('zh-CN') }}</strong> 次 / <span>{{ fmt(panel.instrument.readable_exposure_s) }}</span> s</p>
      <p v-if="panel.instrument?.window_prefix_exposure_s" class="counter-history">含历史累计：<strong>{{ (panel.instrument.window_prefix_counts ?? []).reduce((a, b) => a + b, 0).toLocaleString('zh-CN') }}</strong> 次 / <span>{{ fmt(panel.instrument.window_prefix_exposure_s) }}</span> s（无逐窗明细）</p>
      <label v-if="group" class="window-setting">单次曝光 / s <input :id="'window-size-' + panel.device.id" type="number" min="0.000001" step="any" :value="windowDraft[panel.device.id] ?? state?.instruments[panel.device.id]?.next_window_s ?? state?.instruments[panel.device.id]?.window_s" :disabled="readonly || state?.instruments[panel.device.id]?.clearing" @input="windowDraft[panel.device.id] = ($event.target as HTMLInputElement).value" @change="configureWindow(panel.device.id, $event)"></label>
      <div :ref="el => { if (el) ledgers.set(panel.device.id, el as HTMLElement) }" class="window-ledger" tabindex="0" role="region" :aria-label="panel.label + ' 逐窗数据'" @scroll="follow(panel.device.id, $event)"><table>
        <thead><tr><th>窗号</th><th>实际曝光 / s</th><th>计数 / 次</th></tr></thead>
        <tbody><tr v-for="(window, i) in panel.windows" :key="i"><td>{{ window.number ?? window.index ?? window.window ?? i + 1 }}<small v-if="window.complete === false" class="unfinished-window">{{ panel.running ? '未满窗' : '未满窗 · 已暂停' }}</small></td><td>{{ fmt(windowExposure(window)) }}</td><td>{{ counts(window).toLocaleString('zh-CN') }}</td></tr>
          <tr v-if="!panel.windows.length"><td colspan="3">{{ readonly ? '此存档没有逐窗数据。' : '暂无逐窗读数' }}</td></tr></tbody>
      </table></div>
    </section>
  </div>
</template>

<style scoped>
.counter-console { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; }
.single-counter { grid-template-columns:minmax(0,1fr); }
.legacy-readings { grid-column:1 / -1; }
.counter-window { border:1px solid #aab6c0; border-top:3px solid #637786; background:#fff; padding:14px 18px; }
.counter-window header { display:flex; align-items:center; justify-content:space-between; }
.counter-window h2 { font-size:18px; margin:0; }
.window-state { font-size:13px; color:#53616d; }
.window-state[data-running="true"] { color:#197449; }
.window-reading { display:grid; grid-template-columns:auto 1fr; gap:0 9px; align-items:baseline; padding:12px 0; }
.window-caption { margin:12px 0 0; color:#53616d; font-size:13px; }
.counter-total, .counter-history { margin:6px 0; font-size:14px; font-variant-numeric:tabular-nums; }
.window-reading strong { font-size:48px; line-height:1.1; font-weight:600; font-variant-numeric:tabular-nums; color:#203c50; }
.window-setting { display:flex; align-items:center; gap:8px; margin:12px 0; }
.window-ledger { max-height:calc(100dvh - 310px); overflow:auto; border-top:1px solid #c5ccd3; }
table { width:100%; border-collapse:collapse; font-size:14px; }
.window-ledger table { table-layout:fixed; }
th, td { padding:7px 8px; text-align:right; font-variant-numeric:tabular-nums; }
th:first-child, td:first-child { text-align:left; }
.unfinished-window { display:block; font-size:12px; color:#65552e; }
th { position:sticky; top:0; background:#edf1f4; }
</style>
