<script setup lang="ts">
import {computed} from 'vue'
import {exposure, fmt, parameterText, segmentName} from './display'
import type {Course, Device, Segment} from './types'

const props = defineProps<{course: Course; device: Device; segments: Segment[]; readonly: boolean}>()
const rows = computed(() => props.segments.flatMap((seg, i) => {
  if (!(props.device.id in seg.readings)) return []
  const n = seg.readings[props.device.id][0], t = exposure(seg)
  return [{index: i, cells: [segmentName(seg, i), fmt(n), fmt(t), fmt(n / t),
    ...props.course.parameters.map(p => parameterText(p, seg.settings[p.key]))]}]
}))
</script>

<template>
  <div id="counter" class="counter-console">
    <div class="counter-ledger-head"><h2>计数记录</h2></div>
    <div class="scroll counter-ledger" tabindex="0" role="region" aria-label="计数记录表，可横向滚动"><table><thead id="count-head"><tr><th scope="col">记录</th><th>计数</th><th>曝光 / s</th><th>计数率 / s⁻¹</th><th v-for="p in course.parameters" :key="p.key" scope="col">{{ p.label }}{{ p.unit ? ' / ' + p.unit : '' }}</th></tr></thead>
      <tbody id="counts"><tr v-for="row in rows" :key="row.index"><td v-for="(cell, j) in row.cells" :key="j" :class="{'counter-number': j >= 1 && j <= 3}">{{ cell }}</td></tr>
        <tr v-if="!rows.length"><td class="counter-empty" :colspan="4 + course.parameters.length"><strong>还没有计数记录</strong>
          <p>{{ readonly ? '此存档没有已完成的计数记录。' : '点“开始采集”，记录计数和实际曝光。' }}</p></td></tr></tbody>
    </table></div>
  </div>
</template>
