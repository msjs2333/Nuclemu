<script setup lang="ts">
import {computed} from 'vue'
import {exposure, fmt, indexValue, parameterText, segmentName} from './display'
import {counterMode} from './counterMode'
import type {Course, Device, Segment} from './types'

const props = defineProps<{course: Course; device: Device; segments: Segment[]; background: number | null;
  settings: Record<string, number>; running: boolean; readonly: boolean}>()
const emit = defineEmits<{background: [value: number | null]; configure: [values: Record<string, number> ]}>()
const mode = computed(() => {
  const binding = counterMode(props.course)
  return binding?.device === props.device.id ? binding : null
})
const conditions = computed(() => Object.entries(props.device.background_conditions ?? {}))
const referenceLabel = computed(() => conditions.value.length ? '本底记录' : '参考记录')
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
    if (bg && i === props.background) net = conditions.value.length ? '本底参考' : '所选参考'
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
  <div id="counter" class="counter-console">
    <div class="counter-controls">
      <fieldset v-if="mode" class="counter-mode" :disabled="readonly">
        <legend>{{ mode.parameter.label }}</legend>
        <div class="counter-mode-switch">
          <button v-for="option in mode.parameter.options" :key="option.value" type="button"
            :aria-pressed="settings[mode.parameter.key] === option.value"
            @click="emit('configure', {[mode.parameter.key]: option.value})">{{ option.label }}</button>
        </div>
      </fieldset>
      <label class="counter-background">{{ referenceLabel }}
        <select id="background" :value="background ?? ''" @change="emit('background', indexValue($event))">
          <option value="">不扣{{ conditions.length ? '本底' : '参考' }}</option>
          <option v-for="{seg, i} in choices" :key="i" :value="i">{{ segmentName(seg, i) }} · {{ fmt(exposure(seg)) }} s · {{ fmt(seg.readings[device.id][0]) }} 次</option>
        </select>
      </label>
    </div>
    <div class="counter-ledger-head"><h2>计数记录</h2>
      <details class="counter-formula"><summary>净率怎么算</summary><p>样品计数 ÷ 样品曝光 − 参考计数 ÷ 参考曝光。± 后为独立泊松计数的标准不确定度，负净率保留。</p></details>
    </div>
    <div class="scroll counter-ledger" tabindex="0" role="region" aria-label="计数记录表，可横向滚动"><table><thead id="count-head"><tr><th scope="col">记录</th><th v-for="p in course.parameters" :key="p.key" scope="col">{{ p.label }}{{ p.unit ? ' / ' + p.unit : '' }}</th>
      <th>曝光 / s</th><th>计数</th><th>计数率 / s⁻¹</th><th>净率 ± 标准不确定度 / s⁻¹</th></tr></thead>
      <tbody id="counts"><tr v-for="(cells, i) in rows" :key="i" :class="{'counter-reference': i === background}"><td v-for="(cell, j) in cells" :key="j" :class="{'counter-number': j > course.parameters.length}">{{ cell }}</td></tr>
        <tr v-if="!rows.length"><td class="counter-empty" :colspan="5 + course.parameters.length"><strong>还没有计数记录</strong>
          <p>{{ readonly ? '此存档没有已完成的计数记录。' : mode ? '选择本底模式，再点“开始采集”测量第一份本底。' : '点“开始采集”，记录计数和实际曝光。' }}</p></td></tr></tbody>
    </table></div>
  </div>
</template>
