<script setup lang="ts">
import {computed, nextTick, ref, watch} from 'vue'
import CatalogPage from './CatalogPage.vue'
import SetupPage from './SetupPage.vue'
import InstrumentPage from './InstrumentPage.vue'
import RecordsPage from './RecordsPage.vue'
import CommandBar from './CommandBar.vue'
import StudentPage from './StudentPage.vue'
import MeasurementLoader from './MeasurementLoader.vue'
import {fmt, inputValue} from './display'
import {useSession} from './session'
import {downloadExperiment} from './api'
import type {Open, Page} from './types'

const {state, catalog, page, confirming, recovered, message, error, act, report, open, openPackage, replacePackage, askExit, cancelExit, finish, setPage} = useSession()
const tabs = computed<{id: Page; label: string}[]>(() => [{id: 'setup', label: '实验装置'}, {id: 'instrument', label: kind.value === 'spectrum' ? '多道谱仪' : '计数器'}, {id: 'records', label: '实验记录'}, {id: 'materials', label: '实验资料'}])
const dialog = ref<HTMLDialogElement>()
const menu = ref<InstanceType<typeof CatalogPage>>()
const instruments = ref<InstanceType<typeof InstrumentPage>>()
const commands = ref<InstanceType<typeof CommandBar>>()
const experimentFile = ref<HTMLInputElement>()
const replacementFile = ref<File | null>(null)
const previousPage = ref<Page>('setup')
const measurementLoader = ref<InstanceType<typeof MeasurementLoader>>()
function requestMeasurementLoad(device: string, source: 'cache' | 'file') { measurementLoader.value?.open(device, source) }
const title = ref<HTMLHeadingElement>()
const kind = computed(() => state.value?.definition.devices.find(d => d.id === state.value?.device)?.kind)
const livePortable = computed(() => !!state.value?.definition.outputs?.length && !state.value?.readonly)
const exitDownloadStarted = ref(false)
const convertedFile = computed(() => state.value?.readonly && state.value?.portable_loaded)
const copyNotice = computed(() => state.value?.readonly && !convertedFile.value
  ? '保存分析将另存独立记录，原档案或恢复草稿保持不变。' : '')
const navIcons = {
  setup: 'M3 6h4v12H3z M10 9h4v6h-4z M17 4h4v16h-4z M7 12h3m4 0h3',
  instrument: 'M3 4v16h18 M5 15h3l2-7 3 9 3-6 2 3h3',
  records: 'M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h5',
  materials: 'M3 4h7l2 2 2-2h7v16h-7l-2 2-2-2H3z M12 6v16',
}
function navigate(tab: Page) {
  commands.value?.close()
  if (tab === 'materials' && page.value !== 'materials') previousPage.value = page.value
  setPage(tab)
}
async function openLab(args: Open) {
  await open(args)
  await nextTick()
  if (page.value === 'instrument') instruments.value?.focusDevice()
  else title.value?.focus()
}
function requestExit() {
  commands.value?.close(true)
  void report(askExit)
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
    const replacement = replacementFile.value
    if (replacement) { await replacePackage(replacement); replacementFile.value = null; return }
    await finish(save)
    replacementFile.value = null
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
  if (!file) return
  if (state.value) {
    replacementFile.value = file
    requestExit()
  } else void report(async () => { await openPackage(file); await nextTick(); instruments.value?.focusDevice() })
}
function chooseExperiment() { commands.value?.close(); experimentFile.value?.click() }
async function returnToExperiment() { replacementFile.value = null; await cancelExit() }
</script>

<template>
  <header v-if="!state" class="mast"><div class="wrap brand"><span class="mark" aria-hidden="true">N</span><span>Nuclemu</span></div></header>
  <main :class="state ? 'workbench-wrap' : 'wrap'">
    <p id="error" role="alert" :hidden="!error || confirming">{{ error }}</p>
    <input ref="experimentFile" id="open-package" type="file" accept=".nuclemu" hidden @change="loadExperiment">
    <CatalogPage v-if="catalog && !state" ref="menu" :catalog="catalog" @open="args => report(() => openLab(args))" @load="chooseExperiment"/>
    <section v-if="state" id="workspace" class="lab-shell" :class="{'spectrum-workspace': page === 'instrument' && kind === 'spectrum', 'instrument-page-open': page === 'instrument'}" :key="state.id">
      <header class="lab-topbar">
        <h1 ref="title" id="lab-title" tabindex="-1">{{ state.definition.title }}</h1>
        <CommandBar ref="commands">
          <template #file>
            <button id="load-experiment" @click="chooseExperiment">载入实验</button>
            <button id="save" :disabled="convertedFile" @click="save">保存实验</button>
            <button id="leave" class="danger" @click="requestExit">退出实验</button>
          </template>
          <template #simulation>
            <div class="menu-fields clock-settings">
              <label>仿真倍率 <select id="speed" :value="state.speed" :disabled="state.readonly" @change="report(() => act('speed', {speed: Number(inputValue($event))}))">
                <option v-for="n in [0.25, 1, 2, 5, 10, 60]" :key="n" :value="n">{{ n }}×</option></select></label>
              <p>倍率 {{ state.speed }}×：现实 1 秒对应 {{ state.speed }} 仿真秒。探测输出和采集门决定仿真是否推进。</p>
            </div>
          </template>
        </CommandBar>

      </header>
      <nav class="lab-rail" aria-label="实验工作区"><button v-for="tab in tabs" :key="tab.id" :data-page="tab.id"
        :aria-current="tab.id === page ? 'page' : 'false'" @click="navigate(tab.id)">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path :d="navIcons[tab.id]"/></svg>
        <span>{{ tab.label }}</span></button></nav>
      <div class="lab-main">
      <p v-if="recovered != null || (state.readonly && !convertedFile)" id="recovered" class="notice">{{ recovered != null ? '已恢复至仿真时刻 ' + fmt(recovered) + ' s 的测量。' : '正在查看已保存的实验。' }}</p>
      <p v-if="state.draft_error" class="notice" role="alert">最近草稿未更新。{{ state.draft_error }}</p>
      <p v-if="convertedFile" id="portable-view" class="notice">历史转存文件只供查看，可从实验记录导出读数。</p>
      <p v-else-if="state.portable_loaded && state.selected !== null" id="portable-view" class="notice">正在查看文件中已保存的读数。仪器当前门关闭，开始后建立新的测量轮次。</p>
      <p v-if="Object.keys(state.portable_unresolved).length" class="notice">部分分析引用未对应一份完整保存的读数。已保存的各段仍可查看；请选择所需记录核对工况。</p>
      <SetupPage v-show="page === 'setup'" :course="state.definition" :settings="state.settings" :readonly="state.readonly" :act="act"
        :particle-flow="state.particle_flow" :output-enabled="state.output_enabled" :gates="state.gates" @device="toDevice" @notice="message = $event"/>
      <InstrumentPage ref="instruments" v-show="page === 'instrument'" :state="state" :act="act" @task="fn => { message = ''; report(fn) }"
        @load-measurement="requestMeasurementLoad"/>
      <RecordsPage v-show="page === 'records'" :session="state.id" :course="state.definition" :segments="state.product.segments"
        :calibrated="state.calibrated_devices" :snapshots="state.snapshots" :cached="!!state.definition.outputs?.length && !state.readonly"
        :calibrations="state.cached_calibrations"
        :imported="state.imported_items" :act="act"
        @task="report" @notice="message = $event"/>
      <output v-show="message" id="message" role="status">{{ message }}</output>
      <StudentPage v-show="page === 'materials'" :course="state.definition" :status="(state.running ? '采集中' : '待机') + (state.exposure_s !== null ? ' · 曝光 ' + fmt(state.exposure_s) + ' s' : '')" @back="navigate(previousPage)"/>
      <MeasurementLoader ref="measurementLoader" :session="state.id" :act="act" @task="report" @notice="message = $event"/>
      </div>
    </section>
  </main>
  <dialog id="confirm" ref="dialog" aria-labelledby="exit-title" @cancel.prevent="report(returnToExperiment)">
    <h2 id="exit-title">{{ replacementFile ? '载入实验' : '退出实验' }}</h2><p id="exit-message">{{ reason.length ? reason.join('，') + '。确认期间仿真时钟冻结。' : '退出并返回实验目录？' }}</p>
    <p v-if="livePortable" class="notice">本场缓存只保留在当前服务中。下载整场文件后可在另一台电脑重开；取消下载或尚未保存文件时可返回实验。</p>
    <p v-if="exitDownloadStarted" id="exit-download-status">浏览器已发起下载。确认文件已保存后再退出。</p>
    <p v-if="copyNotice" id="copy-notice">{{ copyNotice }}</p>
    <p id="exit-error" role="alert" :hidden="!error">{{ error }}</p><div class="dialog-actions">
      <button id="cancel" autofocus @click="report(returnToExperiment)">继续实验</button>
      <button id="discard" @click="leave(false)">{{ replacementFile ? '放弃本场并载入' : reason.length ? '放弃并退出' : '退出并返回目录' }}</button>
      <button id="save-exit" class="primary" :hidden="convertedFile || (!reason.length && !livePortable)" @click="leave(true)">{{ livePortable ? '下载整场实验' : state?.readonly ? '保存副本并退出' : '保存实验并退出' }}</button>
      <button v-if="exitDownloadStarted" id="exit-after-download" @click="leave(false)">{{ replacementFile ? '文件已保存，载入' : '文件已保存，退出' }}</button>
    </div>
  </dialog>
</template>
