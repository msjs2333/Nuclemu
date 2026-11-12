<script setup lang="ts">
import {computed, nextTick, ref, watch} from 'vue'
import CatalogPage from './CatalogPage.vue'
import SetupPage from './SetupPage.vue'
import InstrumentPage from './InstrumentPage.vue'
import RecordsPage from './RecordsPage.vue'
import CommandBar from './CommandBar.vue'
import StudentReader from './StudentReader.vue'
import {studentMarkdown} from './studentMaterials'
import {fmt, inputValue} from './display'
import {useSession} from './session'
import {downloadExperiment} from './api'
import type {Open, Page} from './types'

const {state, catalog, page, confirming, recovered, message, error, act, report, open, openPackage, askExit, cancelExit, finish, setPage} = useSession()
const tabs: {id: Page; label: string}[] = [{id: 'setup', label: '实验装置'}, {id: 'instrument', label: '测量仪器'}, {id: 'records', label: '实验记录'}]
const dialog = ref<HTMLDialogElement>()
const menu = ref<InstanceType<typeof CatalogPage>>()
const instruments = ref<InstanceType<typeof InstrumentPage>>()
const commands = ref<InstanceType<typeof CommandBar>>()
const reader = ref<InstanceType<typeof StudentReader>>()
const title = ref<HTMLHeadingElement>()
const kind = computed(() => state.value?.definition.devices.find(d => d.id === state.value?.device)?.kind)
const livePortable = computed(() => !!state.value?.definition.outputs?.length && !state.value?.readonly)
const exitDownloadStarted = ref(false)
const copyNotice = computed(() => state.value?.readonly
  ? '保存分析将另存独立记录，原档案或恢复草稿保持不变。' : '')
const navIcons = {
  setup: 'M3 6h4v12H3z M10 9h4v6h-4z M17 4h4v16h-4z M7 12h3m4 0h3',
  instrument: 'M3 4v16h18 M5 15h3l2-7 3 9 3-6 2 3h3',
  records: 'M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h5',
}
function navigate(tab: Page) {
  commands.value?.close()
  setPage(tab)
}
async function openLab(args: Open) {
  await open(args)
  await nextTick()
  if (page.value === 'instrument') instruments.value?.focusDevice()
  else title.value?.focus()
}
function showRecords() {
  navigate('records')
  void nextTick(() => document.querySelector<HTMLHeadingElement>('#records-title')?.focus())
}
function requestExit() {
  commands.value?.close(true)
  void report(askExit)
}
function showTool(tool: 'acquisition' | 'analysis' | 'calibration') {
  commands.value?.open('analysis')
  void nextTick(() => {
    const target = document.querySelector<HTMLDetailsElement>(tool === 'acquisition' ? '#acquisition-tools' : tool === 'calibration' ? '.calibration-tools' : '#roi')
    if (target?.tagName === 'DETAILS') target.open = true
    target?.scrollIntoView({block: 'nearest'})
    target?.querySelector<HTMLInputElement>('input, select')?.focus()
  })
}
watch(confirming, async value => {
  if (value) exitDownloadStarted.value = false
  if (value) commands.value?.close(true)
  await nextTick()
  if (value && !dialog.value?.open) dialog.value?.showModal()
  if (!value && dialog.value?.open) dialog.value.close()
})
const reason = computed(() => {
  const s = state.value
  if (!s || !confirming.value) return []
  const pending = s.unsaved, details: string[] = []
  if (pending.active_exposure) details.push(livePortable.value ? '仍有仪器正在采集' : '活动曝光' + (s.remaining_s === null ? '（手动）' : '剩余 ' + fmt(s.remaining_s) + ' s'))
  if (pending.cached_items) details.push('本场缓存 ' + pending.cached_items + ' 份已保存记录')
  if (pending.measurements.length) details.push('未保存的测量 ' + pending.measurements.length + ' 项（' +
    pending.measurements.map(m => '段 ' + (m.index + 1) + ' · ' + m.device).join('、') + '）')
  if (pending.calibrations.length) details.push('未保存的刻度 ' + pending.calibrations.join('、'))
  if (pending.settings) details.push('已更改装置工况')
  if (pending.analysis) details.push('已更改仪器或分析选择')
  return details
})
function toDevice(id: string) {
  void report(async () => {
    await act('device', {device: id})
    setPage('instrument')
    await nextTick()
    instruments.value?.focusDevice()
  })
}
function leave(save: boolean) {
  const experiment = state.value!.experiment
  if (save && livePortable.value) {
    const session = state.value!.id
    void report(async () => { await downloadExperiment(session); exitDownloadStarted.value = true })
    return
  }
  void report(async () => {
    await finish(save)
    await nextTick()
    menu.value?.focusExperiment(experiment)
  })
}
function save() { void report(async () => {
  commands.value?.close(true)
  const copied = copyNotice.value
  if (state.value?.definition.outputs?.length && !state.value.readonly) {
    await downloadExperiment(state.value.id)
    message.value = '已发起整场实验文件下载，本场缓存与采集状态保留。'
    return
  }
  await act('save', {exit: false})
  const end = state.value?.measurement_end_s ?? 0
  message.value = copied ? '已另存独立记录，原档案或恢复草稿保持不变。'
    : end ? '已保存；测量记录截至 ' + fmt(end) + ' s。' : '已保存实验设置。尚无已完成的测量段。'
}) }
function loadExperiment(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  input.value = ''
  if (file) void report(async () => { await openPackage(file); await nextTick(); instruments.value?.focusDevice() })
}
</script>

<template>
  <header v-if="!state" class="mast"><div class="wrap brand"><span class="mark" aria-hidden="true">N</span><span>Nuclemu</span></div></header>
  <main :class="state ? 'workbench-wrap' : 'wrap'">
    <p id="error" role="alert" :hidden="!error || confirming">{{ error }}</p>
    <label v-if="!state" class="open-experiment">打开实验文件 <input id="open-package" type="file" accept=".nuclemu" @change="loadExperiment"></label>
    <CatalogPage v-if="catalog && !state" ref="menu" :catalog="catalog" @open="args => report(() => openLab(args))"/>
    <section v-if="state" id="workspace" class="lab-shell" :class="{'spectrum-workspace': page === 'instrument' && kind === 'spectrum'}" :key="state.id">
      <header class="lab-topbar">
        <h1 ref="title" id="lab-title" tabindex="-1">{{ state.definition.title }}</h1>
        <CommandBar ref="commands" :analysis="page === 'instrument' && kind === 'spectrum'"
          :display="page === 'instrument' && kind === 'spectrum'">
          <template #file>
            <button id="save" @click="save">{{ state.readonly ? '保存分析副本' : '保存整场实验' }}</button>
            <button id="open-products" @click="showRecords">选择导出产品…</button>
            <button id="leave" @click="requestExit">退出实验…</button>
          </template>
          <template #analysis>
            <div v-if="page === 'instrument' && kind === 'spectrum'" class="inspector-heading">
              <h2>谱分析</h2>
              <button type="button" aria-label="关闭谱分析" @click="commands?.close(true)">
                <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="m4 4 8 8m0-8-8 8" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
              </button>
            </div>
            <div v-if="page === 'instrument' && kind === 'spectrum'" class="tool-tabs" role="group" aria-label="仪器工具">
              <button id="tool-acquisition" @click="showTool('acquisition')">采集</button>
              <button id="tool-analysis" @click="showTool('analysis')">谱分析</button>
              <button id="tool-calibration" @click="showTool('calibration')">刻度</button>
            </div>
          </template>
          <template #acquisition>
            <div id="acquisition-settings"></div>
          </template>
          <template #simulation>
            <div class="menu-fields clock-settings">
              <label>仿真倍率 <select id="speed" :value="state.speed" :disabled="state.readonly" @change="report(() => act('speed', {speed: Number(inputValue($event))}))">
                <option v-for="n in [0.25, 1, 2, 5, 10, 60]" :key="n" :value="n">{{ n }}×</option></select></label>
              <button id="pause" :disabled="state.readonly" @click="report(() => act('pause', {paused: !state!.paused}))">{{ state.paused ? '继续仿真' : '暂停仿真' }}</button>
            </div>
          </template>
        </CommandBar>
        <button v-if="studentMarkdown(state.definition)" id="student-materials" @click="reader?.open()">实验资料</button>
      </header>
      <nav class="lab-rail" aria-label="实验工作区"><button v-for="tab in tabs" :key="tab.id" :data-page="tab.id"
        :aria-current="tab.id === page ? 'page' : 'false'" @click="navigate(tab.id)">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path :d="navIcons[tab.id]"/></svg>
        <span>{{ tab.label }}</span></button></nav>
      <div class="lab-main">
      <p v-if="recovered != null || state.readonly" id="recovered" class="notice">{{ recovered != null ? '已恢复至仿真时刻 ' + fmt(recovered) + ' s 的测量。' : '正在查看已保存的实验。' }}</p>
      <p v-if="state.draft_error" class="notice" role="alert">最近草稿未更新。{{ state.draft_error }}</p>
      <p v-if="state.portable_loaded && state.selected !== null" id="portable-view" class="notice">正在查看文件中已保存的读数。仪器当前门关闭，开始后建立新的测量轮次。</p>
      <p v-if="Object.keys(state.portable_unresolved).length" class="notice">部分分析引用未对应一份完整保存的读数。已保存的各段仍可查看；请选择所需记录核对工况。</p>
      <SetupPage v-show="page === 'setup'" :course="state.definition" :settings="state.settings" :readonly="state.readonly" :act="act"
        :output-enabled="state.output_enabled" :gates="state.gates" @device="toDevice" @notice="message = $event"/>
      <InstrumentPage ref="instruments" v-show="page === 'instrument'" :state="state" :act="act" @task="report"
        @acquisition-settings="commands?.open('acquisition')"/>
      <RecordsPage v-show="page === 'records'" :session="state.id" :course="state.definition" :segments="state.product.segments"
        :calibrated="state.calibrated_devices" :snapshots="state.snapshots" :cached="!!state.definition.outputs?.length && !state.readonly"
        :calibrations="state.cached_calibrations"
        :imported="state.imported_items" :act="act"
        @task="report" @notice="message = $event"/>
      <output v-show="message" id="message" role="status">{{ message }}</output>
      <StudentReader ref="reader" :course="state.definition" :status="(state.definition.devices.find(d => d.id === state?.device)?.label ?? '') + ' · ' + (state.running ? '采集中' : '已暂停') + (state.exposure_s !== null ? ' · 曝光 ' + fmt(state.exposure_s) + ' s' : '')"/>
      </div>
    </section>
  </main>
  <dialog id="confirm" ref="dialog" aria-labelledby="exit-title" @cancel.prevent="report(cancelExit)">
    <h2 id="exit-title">退出实验</h2><p id="exit-message">{{ reason.length ? reason.join('，') + '。确认期间仿真时钟冻结。' : '退出并返回实验目录？' }}</p>
    <p v-if="livePortable" class="notice">本场缓存只保留在当前服务中。下载整场文件后可在另一台电脑重开；取消下载或尚未保存文件时可返回实验。</p>
    <p v-if="exitDownloadStarted" id="exit-download-status">浏览器已发起下载。确认文件已保存后再退出。</p>
    <p v-if="copyNotice" id="copy-notice">{{ copyNotice }}</p>
    <p id="exit-error" role="alert" :hidden="!error">{{ error }}</p><div class="dialog-actions">
      <button id="cancel" autofocus @click="report(cancelExit)">继续实验</button>
      <button id="discard" @click="leave(false)">{{ reason.length ? '放弃并退出' : '退出并返回目录' }}</button>
      <button id="save-exit" class="primary" :hidden="!reason.length && !livePortable" @click="leave(true)">{{ livePortable ? '下载整场实验' : state?.readonly ? '保存副本并退出' : '保存实验并退出' }}</button>
      <button v-if="exitDownloadStarted" id="exit-after-download" @click="leave(false)">文件已保存，退出</button>
    </div>
  </dialog>
</template>
