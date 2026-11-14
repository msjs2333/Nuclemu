<script setup lang="ts">
import {computed} from 'vue'
import {exposure, fmt, indexValue, segmentName} from './display'
import type {Course, Device, Segment, State} from './types'

const props = defineProps<{course: Course; device: Device; segments: Segment[]; background: number | null; readouts: State['counter_analysis']}>()
const emit = defineEmits<{background: [value: number | null]}>()
const conditions = computed(() => Object.entries(props.device.background_conditions ?? {}))
const referenceLabel = computed(() => conditions.value.length ? '本底记录' : '参考记录')
function matchesBackground(seg: Segment) {
  return conditions.value.every(([key, value]) => seg.settings[key] === value)
}
const choices = computed(() => props.segments.map((seg, i) => ({seg, i})).filter(({seg}) =>
  props.device.id in seg.readings && matchesBackground(seg)))
const rows = computed(() => {
  const bg = props.background === null ? null : props.segments[props.background]
  return props.segments.flatMap((seg, i) => {
    if (!(props.device.id in seg.readings)) return []
    const result = props.readouts.find(row => row.index === i)
    let net = '—'
    if (bg && i === props.background) net = conditions.value.length ? '本底参考' : '所选参考'
    else if (bg && (!conditions.value.length || !matchesBackground(seg))) {
      if (result?.error) net = result.error
      else if (result?.net_rate != null && result.uncertainty != null) net = fmt(result.net_rate) + ' ± ' + fmt(result.uncertainty)
    }
    return [{index: i, name: segmentName(seg, i), net}]
  })
})
</script>

<template>
  <section id="counter-analysis" class="counter-analysis" aria-labelledby="counter-analysis-title">
    <div class="counter-ledger-head"><h2 id="counter-analysis-title">实验分析</h2>
      <details class="counter-formula"><summary>净率怎么算</summary><p>样品计数 ÷ 样品曝光 − 参考计数 ÷ 参考曝光。± 后为独立泊松计数的标准不确定度，负净率保留。</p></details>
    </div>
    <label class="counter-background">{{ referenceLabel }}
      <select id="background" :value="background ?? ''" @change="emit('background', indexValue($event))">
        <option value="">不扣{{ conditions.length ? '本底' : '参考' }}</option>
        <option v-for="{seg, i} in choices" :key="i" :value="i">{{ segmentName(seg, i) }} · {{ fmt(exposure(seg)) }} s · {{ fmt(seg.readings[device.id][0]) }} 次</option>
      </select>
    </label>
    <div class="scroll counter-analysis-ledger" tabindex="0" role="region" aria-label="净率分析表，可横向滚动"><table><thead><tr><th scope="col">记录</th><th scope="col">净率 ± 标准不确定度 / s⁻¹</th></tr></thead>
      <tbody id="net-results"><tr v-for="row in rows" :key="row.index" :class="{'counter-reference': row.index === background}"><th scope="row">{{ row.name }}</th><td class="counter-number">{{ row.net }}</td></tr>
        <tr v-if="!rows.length"><td class="counter-empty" colspan="2">完成采集后，可选择参考记录计算净率。</td></tr>
      </tbody>
    </table></div>
  </section>
</template>
