<script setup lang="ts">
import {computed, nextTick, ref, watch} from 'vue'
import CatalogPage from './CatalogPage.vue'
import SetupPage from './SetupPage.vue'
import InstrumentPage from './InstrumentPage.vue'
import RecordsPage from './RecordsPage.vue'
import CommandBar from './CommandBar.vue'
import {fmt, inputValue} from './display'
import {useSession} from './session'
import type {Page} from './types'

const {state, catalog, page, confirming, recovered, message, error, act, report, open, askExit, cancelExit, finish, setPage} = useSession()
const tabs: {id: Page; label: string}[] = [{id: 'setup', label: '实验装置'}, {id: 'instrument', label: '测量仪器'}, {id: 'records', label: '实验记录'}]
const dialog = ref<HTMLDialogElement>()
const menu = ref<InstanceType<typeof CatalogPage>>()
const instruments = ref<InstanceType<typeof InstrumentPage>>()
const commands = ref<InstanceType<typeof CommandBar>>()
const kind = computed(() => state.value?.definition.devices.find(d => d.id === state.value?.device)?.kind)
const navIcons = {
  setup: 'M3 6h4v12H3z M10 9h4v6h-4z M17 4h4v16h-4z M7 12h3m4 0h3',
  instrument: 'M3 4v16h18 M5 15h3l2-7 3 9 3-6 2 3h3',
  records: 'M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h5',
}
function navigate(tab: Page) {
  commands.value?.close()
  setPage(tab)
}
function showRecords() {
  navigate('records')
  void nextTick(() => document.querySelector<HTMLHeadingElement>('#records-title')?.focus())
}
function requestExit() {
  commands.value?.close(true)
  void report(askExit)
}
watch(confirming, async value => {
  if (value) commands.value?.close(true)
  await nextTick()
  if (value && !dialog.value?.open) dialog.value?.showModal()
  if (!value && dialog.value?.open) dialog.value.close()
})
const reason = computed(() => {
  const s = state.value
  if (!s || !confirming.value) return []
  const pending = s.unsaved, details: string[] = []
  if (pending.active_exposure) details.push('活动曝光' + (s.remaining_s === null ? '（手动）' : '剩余 ' + fmt(s.remaining_s) + ' s'))
  if (pending.measurements.length) details.push('未保存的测量 ' + pending.measurements.length + ' 项（' +
    pending.measurements.map(m => '段 ' + (m.index + 1) + ' · ' + m.device).join('、') + '）')
  if (pending.calibrations.length) details.push('未保存的刻度 ' + pending.calibrations.join('、'))
  if (pending.settings) details.push('已更改装置工况')
  if (pending.analysis) details.push('已更改仪器或分析选择')
  return details
})
function toDevice(id: string) {
  void report(async () => {
    if (id !== state.value?.device) await act('device', {device: id})
    setPage('instrument')
    await nextTick()
    instruments.value?.focusDevice()
  })
}
function leave(save: boolean) {
  const experiment = state.value!.experiment
  void report(async () => {
    await finish(save)
    await nextTick()
    menu.value?.focusExperiment(experiment)
  })
}
function save() { void report(async () => {
  commands.value?.close(true)
  await act('save', {exit: false})
  const last = state.value?.product.segments.at(-1)
  message.value = last ? '已保存；测量记录截至 ' + fmt(last.end_s) + ' s。' : '已保存实验设置。尚无已完成的测量段。'
}) }
</script>

<template>
  <header v-if="!state" class="mast"><div class="wrap brand"><span class="mark" aria-hidden="true">N</span><span>Nuclemu</span></div></header>
  <main :class="state ? 'workbench-wrap' : 'wrap'">
    <p id="error" role="alert" :hidden="!error || confirming">{{ error }}</p>
    <CatalogPage v-if="catalog && !state" ref="menu" :catalog="catalog" @open="args => report(() => open(args))"/>
    <section v-if="state" id="workspace" class="lab-shell" :key="state.id">
      <header class="lab-topbar">
        <h1 id="lab-title">{{ state.definition.title }}</h1>
        <CommandBar ref="commands" :analysis="page === 'instrument' && (kind === 'spectrum' || kind === 'counter')"
          :display="page === 'instrument' && kind === 'spectrum'">
          <template #file>
            <button id="save" @click="save">保存整场实验</button>
            <button id="open-products" @click="showRecords">选择导出产品…</button>
            <button id="leave" @click="requestExit">退出实验…</button>
          </template>
          <template #acquisition>
            <div id="acquisition-settings"></div>
            <div class="menu-fields clock-settings">
              <label>时钟倍速 <select id="speed" :value="state.speed" :disabled="state.readonly" @change="report(() => act('speed', {speed: Number(inputValue($event))}))">
                <option v-for="n in [0.25, 1, 2, 5, 10, 60]" :key="n" :value="n">{{ n }}×</option></select></label>
              <button id="pause" :disabled="state.readonly" @click="report(() => act('pause', {paused: !state!.paused}))">{{ state.paused ? '恢复时钟' : '暂停时钟' }}</button>
            </div>
          </template>
        </CommandBar>
        <div class="clock"><span id="gate-status" :class="{open: state.running}">{{ state.running ? '采集中' : '采集门关闭' }}</span>
          <output id="time" aria-label="仿真时间">{{ fmt(state.time_s) }} s</output><span v-if="state.paused">已暂停</span></div>
      </header>
      <nav class="lab-rail" aria-label="实验工作区"><button v-for="tab in tabs" :key="tab.id" :data-page="tab.id"
        :aria-current="tab.id === page ? 'page' : 'false'" @click="navigate(tab.id)">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path :d="navIcons[tab.id]"/></svg>
        <span>{{ tab.label }}</span></button></nav>
      <div class="lab-main">
      <p v-if="recovered != null || state.readonly" id="recovered" class="notice">{{ recovered != null ? '已恢复至仿真时刻 ' + fmt(recovered) + ' s 的测量。' : '正在查看已保存的实验。' }}</p>
      <p v-if="state.draft_error" class="notice" role="alert">最近草稿未更新。{{ state.draft_error }}</p>
      <SetupPage v-show="page === 'setup'" :course="state.definition" :settings="state.settings" :readonly="state.readonly" :act="act" @device="toDevice" @notice="message = $event"/>
      <InstrumentPage ref="instruments" v-show="page === 'instrument'" :state="state" :act="act" @task="report"
        @acquisition-settings="commands?.open('acquisition')"/>
      <RecordsPage v-show="page === 'records'" :session="state.id" :course="state.definition" :segments="state.product.segments"
        :calibrated="state.calibrated_devices" @task="report" @notice="message = $event"/>
      <output v-show="message" id="message" role="status">{{ message }}</output>
      </div>
    </section>
  </main>
  <dialog id="confirm" ref="dialog" aria-labelledby="exit-title" @cancel.prevent="report(cancelExit)">
    <h2 id="exit-title">退出实验</h2><p id="exit-message">{{ reason.length ? reason.join('，') + '。确认期间仿真时钟冻结。' : '退出并返回实验目录？' }}</p>
    <p id="exit-error" role="alert" :hidden="!error">{{ error }}</p><div class="dialog-actions">
      <button id="cancel" autofocus @click="report(cancelExit)">继续实验</button>
      <button id="discard" @click="leave(false)">{{ reason.length ? '放弃并退出' : '退出并返回目录' }}</button>
      <button id="save-exit" class="primary" :hidden="!reason.length" @click="leave(true)">保存实验并退出</button>
    </div>
  </dialog>
</template>
