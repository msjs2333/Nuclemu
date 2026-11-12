<script setup lang="ts">
import {computed, reactive} from 'vue'
import {downloadProducts, downloadExperiment} from './api'
import {describe, exposure, fmt, inputValue, segmentName} from './display'
import ImportSaved from './ImportSaved.vue'
import type {Act, Course, Segment, State} from './types'

const props = defineProps<{session: string; course: Course; segments: Segment[]; calibrated: string[];
  cached: boolean; snapshots: State['snapshots']; calibrations: State['cached_calibrations']; imported: State['imported_items']; act: Act}>()
const emit = defineEmits<{notice: [message: string]; task: [fn: () => Promise<void>]}>()
const checked = reactive(new Set<string>())
const formats = reactive(new Map<string, string>())
const rows = computed(() => {
  const course = props.course
  const devices = course.devices.map(d => ({
    ...d, name: course.devices.some(other => other !== d && other.label === d.label) ? d.label + ' · ' + d.id : d.label,
  }))
  if (props.cached) return [...props.snapshots.map(snapshot => ({
    key: 's/' + snapshot.id, device: snapshot.device, name: devices.find(d => d.id === snapshot.device)!.name,
    index: null as number | null, snapshot: snapshot.id, kind: '已保存测量', measurement: '记录 ' + snapshot.id,
    conditions: snapshot.settings.map(settings => describe(course, settings)).join(' → '), seconds: snapshot.exposure_s as number | null, formats: ['csv', 'json'],
  })), ...props.calibrations.map(cal => ({key: 'c/' + cal.id, device: cal.device,
    name: devices.find(d => d.id === cal.device)!.name, index: null as number | null,
    snapshot: cal.id as number | string, kind: '已保存刻度', measurement: cal.title,
    conditions: '', seconds: null as number | null, formats: ['json']})), ...props.imported.map(item => ({
    key: 'i/' + item.id, device: item.device, name: devices.find(d => d.id === item.device)?.name ?? item.device,
    index: null as number | null, snapshot: item.id as number | string, kind: '导入记录', measurement: item.title,
    conditions: '保留原来源', seconds: item.exposure_s as number | null, formats: ['csv', 'json']}))]
  const measurements = props.segments.flatMap((seg, index) => {
    const conditions = describe(course, seg.settings)
    return devices.filter(d => d.id in seg.readings).map(d => ({
      key: 'm/' + d.id + '/' + index, device: d.id, name: d.name, index: index as number | null,
      snapshot: null as number | null,
      kind: d.kind === 'spectrum' ? '道谱' : d.kind === 'counter' ? '计数表' : '测量读数',
      measurement: segmentName(seg, index), conditions, seconds: exposure(seg) as number | null, formats: ['csv', 'json'],
    }))
  })
  for (const d of devices) {
    if (props.calibrated.includes(d.id)) measurements.push({
      key: 'c/' + d.id, device: d.id, name: d.name, index: null, kind: '两点能量刻度',
      snapshot: null,
      measurement: '', conditions: '', seconds: null, formats: ['json'],
    })
  }
  return measurements
})
type Product = (typeof rows.value)[number]
const selected = computed(() => rows.value.filter(row => checked.has(row.key)))
const allSelected = computed(() => !!rows.value.length && selected.value.length === rows.value.length)
function toggleAll() {
  if (allSelected.value) checked.clear()
  else rows.value.forEach(row => checked.add(row.key))
}
function format(row: Product) { return formats.get(row.key) ?? row.formats[0] }
function label(row: Product) { return [row.measurement, row.name, row.kind].filter(Boolean).join(' · ') }
async function saveProducts() {
  if (props.cached) {
    const snapshots = selected.value.map(row => ({id: row.snapshot, format: format(row)}))
    if (!snapshots.length) return
    await downloadProducts({session: props.session, snapshots}, 'nuclemu-saved-items.zip')
    emit('notice', '已生成所选缓存记录的下载，其他已保存记录仍在本场。')
    return
  }
  const products = selected.value.map(row => ({
    device: row.device, indices: row.index === null ? [] : [row.index],
    kind: row.index === null ? 'calibration' : 'measurement', format: format(row),
  }))
  if (!products.length) return
  await downloadProducts({session: props.session, products},
    products.length === 1 ? 'nuclemu.' + products[0].format : 'nuclemu-products.zip')
  emit('notice', '已生成 ' + products.length + ' 项测量产品的下载。')
}
async function saveExperiment() {
  await downloadExperiment(props.session)
  emit('notice', '已生成整场实验文件，包含全部已保存记录；请保留下载的 .nuclemu 文件。')
}
</script>

<template>
  <section id="records" class="page">
    <div class="section-title records-heading">
      <h2 id="records-title" tabindex="-1">测量产品</h2>
      <button id="export" class="primary" :disabled="!selected.length" @click="emit('task', saveProducts)">导出所选产品</button>
      <button v-if="cached" id="download-experiment" @click="emit('task', saveExperiment)">下载整场实验</button>
      <ImportSaved v-if="cached" :session="session" :act="act" @task="emit('task', $event)" @notice="emit('notice', $event)"/>
    </div>
    <div v-if="rows.length" class="product-selection">
      <label><input type="checkbox" :checked="allSelected" :indeterminate="selected.length > 0 && !allSelected" @change="toggleAll"> 全选</label>
      <output aria-live="polite">已选 {{ selected.length }} / {{ rows.length }} 项</output>
    </div>
    <table v-if="rows.length" class="product-table" aria-label="可导出的测量产品">
      <thead><tr><th scope="col">产品</th><th scope="col">测量记录</th><th scope="col">工况</th><th scope="col">实际曝光</th><th scope="col">格式</th></tr></thead>
      <tbody id="products">
        <tr v-for="row in rows" :key="row.key" class="product" :data-key="row.key" :data-device="row.device"
          :data-index="row.index ?? ''" :class="{'is-selected': checked.has(row.key)}">
          <th scope="row"><label class="product-name">
            <input type="checkbox" :checked="checked.has(row.key)" :aria-label="label(row)"
              @change="checked.has(row.key) ? checked.delete(row.key) : checked.add(row.key)">
            <span><strong>{{ row.kind }}</strong><span class="product-device">{{ row.name }}</span></span>
          </label></th>
          <td class="product-measurement" data-label="测量记录">{{ row.measurement || '—' }}</td>
          <td class="product-settings" data-label="工况">{{ row.conditions || '—' }}</td>
          <td class="product-exposure" data-label="实际曝光">{{ row.seconds == null ? '—' : fmt(row.seconds) + ' s' }}</td>
          <td class="product-format" data-label="格式">
            <select :value="format(row)" :aria-label="label(row) + '的导出格式'" @change="formats.set(row.key, inputValue($event))">
              <option v-for="f in row.formats" :key="f" :value="f">{{ f.toUpperCase() }}</option>
            </select>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else id="products" class="product-empty">{{ cached ? '在仪器上保存读数后，在这里勾选下载；未保存的当前读数不会随整场文件带走。' : '完成一次采集后，可在这里选择测量产品和导出格式。' }}</p>
  </section>
</template>
