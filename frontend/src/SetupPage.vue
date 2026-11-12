<script setup lang="ts">
import {computed, nextTick, onMounted, onBeforeUnmount, ref, watch} from 'vue'
import {drawConnections} from '/draw.js'
import ApparatusFigure from './ApparatusFigure.vue'
import {errorMessage} from './api'
import type {Act, Course, Part} from './types'

const props = defineProps<{course: Course; settings: Record<string, number>; readonly: boolean; act: Act;
  outputEnabled: Record<string, boolean>; gates: Record<string, boolean>}>()
const emit = defineEmits<{device: [id: string]; notice: [message: string]}>()
const selection = ref<string | null>(null)
const part = computed(() => props.course.components.find(p => p.id === selection.value))
const params = computed(() => props.course.parameters.filter(p => part.value?.parameters.includes(p.key)))
const readouts = computed(() => props.course.components.filter(p => p.kind === 'instrument' && p.device))
const stacked = computed(() => readouts.value.length === 2 && readouts.value.every(p =>
  props.course.devices.find(d => d.id === p.device)?.kind === 'counter'))
function placement(p: Part) {
  if (!stacked.value) return {}
  const index = readouts.value.findIndex(r => r.id === p.id)
  const beam = props.course.components.filter(r => !readouts.value.includes(r))
  return index < 0 ? {gridColumn: String(beam.indexOf(p) + 1), gridRow: '1 / 3'}
    : {gridColumn: String(beam.length + 1), gridRow: String(index + 1)}
}
const connections = computed(() => props.course.connections.map(edge => ({...edge,
  active: edge.kind !== 'particle' || props.settings.source_present !== 0})))
const variants = computed(() => Object.fromEntries(props.course.components.flatMap(p => {
  if (p.illustration === 'source' && p.parameters.includes('source_present') && props.settings.source_present === 0) return [[p.id, 'source-empty']]
  if (p.illustration === 'foil' && p.parameters.includes('foil_count') && props.settings.foil_count === 0) return [[p.id, 'foil-empty']]
  return []
})))
function status(p: Part) {
  if (p.output) return props.outputEnabled[p.output] ? '探测开启' : '探测关闭'
  if (p.kind === 'instrument' && p.device) return props.gates[p.device] ? '采集中' : '采集门关闭'
  if (p.illustration === 'source' && p.parameters.includes('source_present')) return props.settings.source_present === 0 ? '空源座' : '已装源'
  if (p.illustration === 'foil' && p.parameters.includes('foil_count')) return props.settings.foil_count === 0 ? '空箔架' : `${props.settings.foil_count} 片 × ${props.settings.foil_spec_um} µm`
  return ''
}
type Edit = {base: number; value: number | string}
const edits = ref<Record<string, Edit>>({})
const pending = ref<Record<string, Edit> | null>(null)
const error = ref('')
const diagram = ref<HTMLElement>()
const wiring = ref<HTMLCanvasElement>()
let observer: ResizeObserver
function paint() {
  if (wiring.value?.clientWidth) drawConnections(wiring.value, connections.value)
}
onMounted(() => { observer = new ResizeObserver(paint); observer.observe(diagram.value!); paint() })
onBeforeUnmount(() => observer.disconnect())
watch(connections, paint, {flush: 'post'})
watch(part, () => {
  edits.value = {}
  pending.value = null
  error.value = ''
}, {immediate: true})
function edit(key: string, event: Event) {
  const raw = (event.target as HTMLInputElement).value
  const value = raw === '' ? '' : Number(raw)
  const base = edits.value[key]?.base ?? props.settings[key]
  if (!pending.value?.[key] && (value === base || value === props.settings[key])) delete edits.value[key]
  else edits.value[key] = {base, value}
}
function choose(p: Part) {
  selection.value = p.id
}
async function switchOutput(event: Event) {
  const output = part.value!.output
  try { await props.act('output', {output, enabled: (event.target as HTMLInputElement).checked}) }
  catch (e) { error.value = errorMessage(e) }
}
function partLabel(id: string) { return props.course.components.find(p => p.id === id)?.label ?? id }
async function apply() {
  if (pending.value || !Object.keys(edits.value).length) return
  const editor = edits.value
  const submitted = {...editor}
  const values = Object.fromEntries(Object.entries(submitted).map(([key, edit]) => [key, edit.value]))
  pending.value = submitted
  error.value = ''
  try {
    await props.act('configure', {values})
    await nextTick()
    if (editor !== edits.value) return
    for (const [key, sent] of Object.entries(submitted)) {
      if (editor[key] === sent || editor[key]?.value === props.settings[key]) delete editor[key]
      else if (editor[key]) editor[key] = {base: props.settings[key], value: editor[key].value}
    }
    emit('notice', '已更新装置工况。')
  } catch (e) {
    if (editor === edits.value) {
      error.value = errorMessage(e)
      for (const key of Object.keys(editor)) if (editor[key].value === props.settings[key]) delete editor[key]
    }
  } finally {
    if (editor === edits.value) pending.value = null
  }
}
</script>

<template>
  <section id="setup" class="page">
    <div class="rig"><div><div class="section-title"><h2>装置示意</h2></div>
      <div id="apparatus" ref="diagram" class="apparatus" :class="{'dual-readouts': stacked}"
        :style="stacked ? {'--beam-parts': course.components.length - 2} : {}" @load.capture="paint">
        <canvas class="wiring" ref="wiring" aria-hidden="true"></canvas>
        <button v-for="p in course.components" :key="p.id" :data-part="p.id" :data-kind="p.kind"
          :style="placement(p)" :aria-pressed="p.id === selection" @click="choose(p)">
          <ApparatusFigure :parts="[p]" :variants="variants"/><span>{{ p.label }}<small>{{ status(p) }}</small></span>
        </button>
      </div>
      <div class="connection-key"><span>{{ settings.source_present === 0 ? '┄ 粒子路径（空源）' : '⇢ 粒子传播路径' }}</span><span>● 电缆与信号端口</span></div>
      <details v-if="course.connections.length" id="connections" class="wiring-info">
        <summary>装置接线</summary>
        <ul><li v-for="edge in course.connections" :key="edge.source + '/' + edge.target + '/' + edge.label">
          {{ partLabel(edge.source) }} → {{ partLabel(edge.target) }} · {{ edge.label }}</li></ul>
      </details>
      </div>
      <aside id="component" v-if="part"><h2>{{ part.label }}</h2><p>{{ part.description }}</p>
        <p class="part-status">{{ status(part) }}</p>
        <label v-if="part.output" class="output-switch"><input id="part-output" type="checkbox"
          :checked="outputEnabled[part.output]" :disabled="readonly" @change="switchOutput">探测输出</label>
        <form v-if="params.length" @submit.prevent="apply">
          <label v-for="p in params" :key="p.key">{{ p.label }}{{ p.unit ? ' / ' + p.unit : '' }}
            <select v-if="p.options?.length" :name="p.key" :value="edits[p.key]?.value ?? settings[p.key]" @change="edit(p.key, $event)" :disabled="readonly">
              <option v-for="option in p.options" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <input v-else :name="p.key" :value="edits[p.key]?.value ?? settings[p.key]" @input="edit(p.key, $event)" type="number" :min="p.minimum" :max="p.maximum"
              :step="p.integer ? 1 : 'any'" required :disabled="readonly">
          </label>
          <button v-if="!readonly" :disabled="!!pending">应用参数</button>
        </form>
        <p v-if="error" class="notice" role="alert">{{ error }}</p>
        <button v-if="part.kind === 'instrument' && part.device" id="open-instrument" @click="emit('device', part.device)">打开{{ course.devices.find(d => d.id === part?.device)?.label }}</button>
      </aside>
      <aside v-else id="component" class="component-empty"><h2>查看器材</h2><p>单击器材查看说明与设置。选择读出仪器后，再打开它的面板。</p></aside>
    </div>
  </section>
</template>
