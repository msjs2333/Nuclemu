<script setup lang="ts">
import {computed, reactive, ref} from 'vue'
import {downloadProducts, downloadExperiment, errorMessage} from './api'
import {describe, exposure, fmt, inputValue, segmentName} from './display'
import {counterWindowName, deviceName} from './instrumentBindings'
import ImportSaved from './ImportSaved.vue'
import type {Act, Course, Segment, State} from './types'

const props = defineProps<{session: string; course: Course; segments: Segment[]; calibrated: string[];
  records: State['records'];
  cached: boolean; snapshots: State['snapshots']; calibrations: State['cached_calibrations']; imported: State['imported_items']; act: Act}>()
const emit = defineEmits<{notice: [message: string]; task: [fn: () => Promise<void>]}>()
const checked = reactive(new Set<string>())
const formats = reactive(new Map<string, string>())
type RecordDetails = {settings?: Record<string, number>[]; calibration_id?: string | null}
function calibrationName(item: RecordDetails, spectrum: boolean) {
  if (!spectrum) return '—'
  return item.calibration_id ? props.calibrations.find(cal => cal.id === item.calibration_id)?.title ?? '能量刻度 ' + item.calibration_id : '未附能量刻度'
}
const rows = computed(() => {
  const course = props.course
  const devices = course.devices.map(d => ({
    ...d, name: deviceName(course, d.id),
  }))
  if (props.cached) return (props.records ?? []).map(item => {
    const device = devices.find(d => d.id === item.device)
    const details: RecordDetails = props.snapshots.find(row => row.item_id === item.id)
      ?? props.imported.find(row => row.id === item.id) as RecordDetails ?? {}
    const measured = item.measurements ?? [{id: item.id, device: item.device, exposure_s: item.exposure_s}]
    const members = item.group?.members ?? [item.device]
    return {key: 'r/' + item.id, device: item.device,
      name: item.group ? course.components.find(p => p.devices?.includes(item.device))?.label ?? device?.name ?? item.device : device?.name ?? item.device,
      index: null as number | null, snapshot: item.id as number | string | null,
      kind: item.kind === 'calibration' ? '能量刻度' : device?.kind === 'spectrum' ? '道谱' : '计数记录',
      measurement: item.title, calibration: item.kind === 'calibration' ? item.title : calibrationName(details, device?.kind === 'spectrum'),
      conditions: details.settings?.map(settings => describe(course, settings)).join(' → ') ?? '', seconds: item.exposure_s as number | null,
      secondsLabel: item.kind === 'calibration' ? '—' : members.map(id => {
        const seconds = measured.find(row => row.device === id)?.exposure_s
        return (members.length > 1 ? (counterWindowName(course, id) ?? deviceName(course, id)) + '：' : '') + (seconds == null ? '—' : fmt(seconds) + ' s')
      }).join('\n'), formats: item.kind === 'calibration' ? ['json'] : ['csv', 'json']}
  })
  const measurements = props.segments.flatMap((seg, index) => {
    const conditions = describe(course, seg.settings)
    return devices.filter(d => d.id in seg.readings).map(d => ({
      key: 'm/' + d.id + '/' + index, device: d.id, name: d.name, index: index as number | null,
      snapshot: null as number | null,
      kind: d.kind === 'spectrum' ? '道谱' : d.kind === 'counter' ? '计数记录' : '测量读数',
      calibration: d.kind === 'spectrum' ? (props.calibrated.includes(d.id) ? '本场能量刻度' : '未附能量刻度') : '—',
      measurement: segmentName(seg, index), conditions, seconds: exposure(seg) as number | null, secondsLabel: fmt(exposure(seg)) + ' s', formats: ['csv', 'json'],
    }))
  })
  for (const d of devices) {
    if (props.calibrated.includes(d.id)) measurements.push({
      key: 'c/' + d.id, device: d.id, name: d.name, index: null, kind: '能量刻度', calibration: '本场能量刻度',
      snapshot: null,
      measurement: '', conditions: '', seconds: null, secondsLabel: '—', formats: ['json'],
    })
  }
  return measurements
})
type RecordRow = (typeof rows.value)[number]
const renameDialog = ref<HTMLDialogElement>(), recordName = ref(''), renaming = ref(false)
const renameError = ref('')
let renameTarget: {session: string; id: string} | null = null
function rename(row: RecordRow) {
  renameError.value = ''
  renameTarget = {session: props.session, id: String(row.snapshot)}
  recordName.value = row.measurement
  renameDialog.value?.showModal()
}
function confirmRename() {
  const target = renameTarget, title = recordName.value.trim()
  if (!target || !title || renaming.value) return
  renaming.value = true
  emit('task', async () => {
    try {
      await props.act('rename_record', {item_id: target.id, title}, target.session)
      renameDialog.value?.close()
    } catch (error) { renameError.value = errorMessage(error) }
    finally { renaming.value = false }
  })
}
const selected = computed(() => rows.value.filter(row => checked.has(row.key)))
const allSelected = computed(() => !!rows.value.length && selected.value.length === rows.value.length)
function toggleAll() {
  if (allSelected.value) checked.clear()
  else rows.value.forEach(row => checked.add(row.key))
}
function format(row: RecordRow) { return formats.get(row.key) ?? row.formats[0] }
function label(row: RecordRow) { return [row.measurement, row.name, row.kind].filter(Boolean).join(' · ') }
async function saveProducts() {
  if (props.cached) {
    const snapshots = selected.value.map(row => ({id: row.snapshot, format: format(row)}))
    if (!snapshots.length) return
    await downloadProducts({session: props.session, snapshots})
    emit('notice', '已生成所选缓存记录的下载，其他已保存记录仍在本场。')
    return
  }
  const products = selected.value.map(row => ({
    device: row.device, indices: row.index === null ? [] : [row.index],
    kind: row.index === null ? 'calibration' : 'measurement', format: format(row),
  }))
  if (!products.length) return
  await downloadProducts({session: props.session, products})
  emit('notice', '已生成 ' + products.length + ' 项实验记录的下载。')
}
async function saveExperiment() {
  await downloadExperiment(props.session)
  emit('notice', '已生成整场实验文件，包含全部已保存记录；请保留下载的 .nuclemu 文件。')
}
</script>

<template>
  <section id="records" class="page">
    <div class="section-title records-heading">
      <h2 id="records-title" tabindex="-1">实验记录</h2>
      <div class="records-actions">
        <ImportSaved v-if="cached" :session="session" :act="act" @task="emit('task', $event)" @notice="emit('notice', $event)"/>
        <button v-if="cached" id="download-experiment" @click="emit('task', saveExperiment)">下载整场实验</button>
      </div>
    </div>
    <div v-if="rows.length" class="product-selection">
      <label><input type="checkbox" :checked="allSelected" :indeterminate="selected.length > 0 && !allSelected" @change="toggleAll"> 全选</label>
      <output aria-live="polite">已选 {{ selected.length }} / {{ rows.length }} 项</output>
      <button id="export" class="primary" :disabled="!selected.length" @click="emit('task', saveProducts)">导出所选</button>
    </div>
    <table v-if="rows.length" class="product-table" aria-label="可导出的实验记录">
      <thead><tr><th scope="col">记录类型与设备</th><th scope="col">测量记录</th><th scope="col">工况</th><th scope="col">实际曝光</th><th scope="col">能量刻度</th><th scope="col">格式</th></tr></thead>
      <tbody id="products">
        <tr v-for="row in rows" :key="row.key" class="product" :data-key="row.key" :data-device="row.device"
          :data-index="row.index ?? ''" :class="{'is-selected': checked.has(row.key)}">
          <th scope="row"><label class="product-name">
            <input type="checkbox" :checked="checked.has(row.key)" :aria-label="label(row)"
              @change="checked.has(row.key) ? checked.delete(row.key) : checked.add(row.key)">
            <span><strong>{{ row.kind }}</strong><span class="product-device">{{ row.name }}</span></span>
          </label></th>
          <td class="product-measurement" data-label="测量记录">{{ row.measurement || '—' }}<button v-if="cached" :data-rename-record="row.snapshot" class="rename-record" @click="rename(row)">改名</button></td>
          <td class="product-settings" data-label="工况">{{ row.conditions || '—' }}</td>
          <td class="product-exposure" data-label="实际曝光">{{ row.secondsLabel }}</td>
          <td class="product-calibration" data-label="能量刻度">{{ row.calibration }}</td>
          <td class="product-format" data-label="格式">
            <select :value="format(row)" :aria-label="label(row) + '的导出格式'" @change="formats.set(row.key, inputValue($event))">
              <option v-for="f in row.formats" :key="f" :value="f">{{ f.toUpperCase() }}</option>
            </select>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else id="products" class="product-empty">当前没有实验记录，请进行测量或在本页面导入</p>
    <dialog id="record-rename" ref="renameDialog" aria-labelledby="record-rename-title"><h2 id="record-rename-title">记录改名</h2><form @submit.prevent="confirmRename"><label>名称 <input id="record-name" v-model="recordName" required autofocus></label><p v-if="renameError" role="alert">{{ renameError }}</p><div class="dialog-actions"><button type="button" :disabled="renaming" @click="renameDialog?.close()">取消</button><button id="rename-confirm" class="primary" :disabled="renaming || !recordName.trim()">保存名称</button></div></form></dialog>
  </section>
</template>
