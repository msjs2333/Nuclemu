<script setup lang="ts">
import {computed, nextTick, ref, watch} from 'vue'
import CatalogPage from './CatalogPage.vue'
import SetupPage from './SetupPage.vue'
import InstrumentPage from './InstrumentPage.vue'
import RecordsPage from './RecordsPage.vue'
import {fmt, inputValue} from './display'
import {useSession} from './session'
import type {Page} from './types'

const {state, catalog, page, confirming, recovered, message, error, act, report, open, askExit, cancelExit, finish, setPage} = useSession()
const tabs: {id: Page; label: string}[] = [{id: 'setup', label: '实验装置'}, {id: 'instrument', label: '测量仪器'}, {id: 'records', label: '实验记录'}]
const dialog = ref<HTMLDialogElement>()
const menu = ref<InstanceType<typeof CatalogPage>>()
const instruments = ref<InstanceType<typeof InstrumentPage>>()
watch(confirming, async value => {
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
  await act('save', {exit: false})
  const last = state.value?.product.segments.at(-1)
  message.value = last ? '已保存；测量记录截至 ' + fmt(last.end_s) + ' s。' : '已保存实验设置。尚无已完成的测量段。'
}) }
</script>

<template>
  <header class="mast"><div class="wrap brand"><span class="mark" aria-hidden="true">N</span><span>Nuclemu</span><span class="subtitle">A Virtual Nuclear Physics Lab</span></div></header>
  <main class="wrap">
    <p id="error" role="alert" :hidden="!error || confirming">{{ error }}</p>
    <CatalogPage v-if="catalog && !state" ref="menu" :catalog="catalog" @open="args => report(() => open(args))"/>
    <section v-if="state" id="workspace" :key="state.id">
      <div class="heading"><h1 id="lab-title">{{ state.definition.title }}</h1><button id="leave" @click="report(askExit)">退出实验 ↗</button></div>
      <p v-if="recovered != null || state.readonly" id="recovered" class="notice">{{ recovered != null ? '已恢复至仿真时刻 ' + fmt(recovered) + ' s 的测量。' : '正在查看已保存的实验。' }}</p>
      <p v-if="state.draft_error" class="notice" role="alert">最近草稿未更新。{{ state.draft_error }}</p>
      <nav aria-label="实验工作区"><div class="tabs"><button v-for="tab in tabs" :key="tab.id" :data-page="tab.id"
        :aria-current="tab.id === page ? 'page' : 'false'" @click="setPage(tab.id)">{{ tab.label }}</button></div>
        <div class="clock"><span id="gate-status" :class="{open: state.running}">{{ state.running ? '采集中' : '采集门关闭' }}</span>
          <output id="time">{{ fmt(state.time_s) }} s</output>
          <label>倍速 <select id="speed" :value="state.speed" :disabled="state.readonly" @change="report(() => act('speed', {speed: Number(inputValue($event))}))">
            <option v-for="n in [0.25, 1, 2, 5, 10, 60]" :key="n" :value="n">{{ n }}</option></select></label>
          <button id="pause" :disabled="state.readonly" @click="report(() => act('pause', {paused: !state!.paused}))">{{ state.paused ? '恢复时钟' : '暂停时钟' }}</button>
        </div>
      </nav>
      <SetupPage v-show="page === 'setup'" :course="state.definition" :settings="state.settings" :readonly="state.readonly" :act="act" @device="toDevice" @notice="message = $event"/>
      <InstrumentPage ref="instruments" v-show="page === 'instrument'" :state="state" :act="act" @task="report"/>
      <RecordsPage v-show="page === 'records'" :session="state.id" :course="state.definition" :segments="state.product.segments"
        :calibrated="state.calibrated_devices" @save="save" @task="report" @notice="message = $event"/>
      <output id="message" role="status">{{ message }}</output>
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
