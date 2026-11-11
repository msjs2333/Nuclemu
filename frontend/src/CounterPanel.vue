<script setup lang="ts">
import {computed} from 'vue'
import {exposure, fmt, indexValue, parameterText, segmentName} from './display'
import type {Course, Device, Segment} from './types'

const props = defineProps<{course: Course; device: Device; segments: Segment[]; background: number | null}>()
const emit = defineEmits<{background: [value: number | null]}>()
const conditions = computed(() => Object.entries(props.device.background_conditions ?? {}))
function matchesBackground(seg: Segment) {
  return conditions.value.every(([key, value]) => seg.settings[key] === value)
}
const choices = computed(() => props.segments.map((seg, i) => ({seg, i})).filter(({seg}) =>
  matchesBackground(seg)))
const rows = computed(() => {
  const bg = props.background === null ? null : props.segments[props.background]
  return props.segments.map((seg, i) => {
    const n = seg.readings[props.device.id][0], t = exposure(seg)
    let net = '—'
    if (bg && i === props.background) net = '本底参考'
    else if (bg && (!conditions.value.length || !matchesBackground(seg))) {
      const nb = bg.readings[props.device.id][0], tb = exposure(bg)
      net = fmt(n / t - nb / tb) + ' ± ' + fmt(Math.sqrt(n / t ** 2 + nb / tb ** 2))
    }
    return [segmentName(seg, i), ...props.course.parameters.map(p => parameterText(p, seg.settings[p.key])),
      fmt(t), fmt(n), fmt(n / t), net]
  })
})
</script>

<template>
  <div id="counter">
    <div class="tools"><label>本底记录 <select id="background" :value="background ?? ''" @change="emit('background', indexValue($event))">
      <option value="">不扣本底</option><option v-for="{seg, i} in choices" :key="i" :value="i">{{ segmentName(seg, i) }} · {{ fmt(exposure(seg)) }} s</option>
    </select></label></div>
    <div class="scroll"><table><thead id="count-head"><tr><th>记录</th><th v-for="p in course.parameters" :key="p.key">{{ p.label }}{{ p.unit ? ' / ' + p.unit : '' }}</th>
      <th>曝光 / s</th><th>计数</th><th>计数率 / s⁻¹</th><th>净率 ± 标准不确定度 / s⁻¹</th></tr></thead>
      <tbody id="counts"><tr v-for="(cells, i) in rows" :key="i"><td v-for="(cell, j) in cells" :key="j">{{ cell }}</td></tr>
        <tr v-if="!rows.length"><td :colspan="5 + course.parameters.length">等待第一段曝光</td></tr></tbody>
    </table></div>
  </div>
</template>
