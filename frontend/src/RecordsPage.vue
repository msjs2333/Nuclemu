<script setup lang="ts">
import {computed, reactive} from 'vue'
import {downloadProducts} from './api'
import {describe, segmentName} from './display'
import type {Course, Segment} from './types'

const props = defineProps<{session: string; course: Course; segments: Segment[]; calibrated: string[]}>()
const emit = defineEmits<{notice: [message: string]; task: [fn: () => Promise<void>]}>()
const selections = reactive<Record<string, {checked: boolean; format: string}>>({})
const rows = computed(() => {
  const course = props.course
  const list = props.segments.flatMap((seg, index) => course.devices.map(d => ({
    key: 'm/' + d.id + '/' + index, device: d.id, index: index as number | null, formats: ['csv', 'json'],
    label: segmentName(seg, index) + ' · ' + d.label + ' · ' + describe(course, seg.settings),
  })))
  for (const id of props.calibrated) list.push({key: 'c/' + id, device: id, index: null, formats: ['json'],
    label: course.devices.find(d => d.id === id)!.label + ' · 两点能量刻度'})
  return list
})
function choice(row: (typeof rows.value)[number]) {
  return selections[row.key] ??= {checked: false, format: row.formats[0]}
}
async function saveProducts() {
  const products = []
  for (const row of rows.value) {
    const {checked, format} = choice(row)
    if (!checked) continue
    const calibration = row.index === null
    products.push({device: row.device, indices: calibration ? [] : [row.index],
      kind: calibration ? 'calibration' : 'measurement', format})
  }
  if (!products.length) throw Error('请先选择要导出的测量产品。')
  await downloadProducts({session: props.session, products},
    products.length === 1 ? 'nuclemu.' + products[0].format : 'nuclemu-products.zip')
  emit('notice', '已生成 ' + products.length + ' 项测量产品的下载。')
}
</script>

<template>
  <section id="records" class="page"><div class="section-title"><h2 id="records-title" tabindex="-1">测量产品</h2></div>
    <div id="products"><div v-for="row in rows" :key="row.key" class="product" :data-key="row.key" :data-device="row.device" :data-index="row.index ?? ''">
      <label><input type="checkbox" v-model="choice(row).checked"> {{ row.label }}</label>
      <select v-model="choice(row).format" :aria-label="row.label + '的导出格式'"><option v-for="f in row.formats" :key="f" :value="f">{{ f.toUpperCase() }}</option></select>
    </div><p v-if="!rows.length" class="subtle">完成采集后可导出测量产品。</p></div>
    <button id="export" class="primary" :disabled="!rows.length" @click="emit('task', saveProducts)">导出所选产品</button>
  </section>
</template>
