<script setup lang="ts">
import {computed, nextTick, onMounted, onBeforeUnmount, ref, watch} from 'vue'
import {drawConnections} from '/draw.js'
import ApparatusFigure from './ApparatusFigure.vue'
import ParticleFlow from './ParticleFlow.vue'
import {errorMessage} from './api'
import type {Act, Course, Part} from './types'

const props = defineProps<{course: Course; settings: Record<string, number>; readonly: boolean; act: Act;
  outputEnabled: Record<string, boolean>; gates: Record<string, boolean>; particleFlow?: {thickness_um?: number; areal_density_g_cm2?: number} | null}>()
const animate = ref(!window.matchMedia('(prefers-reduced-motion: reduce)').matches)
const emit = defineEmits<{device: [id: string]; notice: [message: string]}>()
const selection = ref<string | null>(null)
const part = computed(() => props.course.components.find(p => p.id === selection.value))
const panel = ref<'operation' | 'introduction'>('operation')
const params = computed(() => props.course.parameters.filter(p => props.course.components.some(c => c.parameters.includes(p.key))))
const outputs = computed(() => props.course.components.filter(p => p.output))
const foilThickness = computed(() => props.particleFlow?.thickness_um)
function label(p: Part) { return p.illustration === 'foil' ? '箔架' : p.label }
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
const connections = computed(() => props.course.connections.filter(edge => edge.kind !== 'particle').map(edge => {
  const output = props.course.components.find(p => p.id === edge.source)?.output
  return {...edge, active: edge.kind === 'particle' ? props.settings.source_present !== 0 : !output || props.outputEnabled[output]}
}))
const variants = computed(() => Object.fromEntries(props.course.components.flatMap(p => {
  if (p.illustration === 'source' && p.parameters.includes('source_present') && props.settings.source_present === 0) return [[p.id, 'source-empty']]
  if (p.illustration === 'foil' && p.parameters.includes('foil_count') && props.settings.foil_count === 0) return [[p.id, 'foil-empty']]
  return []
})))
function status(p: Part) {
  if (p.output) return props.outputEnabled[p.output] ? '探测开启' : '探测关闭'
  if (p.kind === 'instrument' && p.device) return props.gates[p.device] ? '采集中' : '采集门关闭'
  if (p.illustration === 'source' && p.parameters.includes('source_present')) return props.settings.source_present === 0 ? '空源座' : '已装源'
  if (p.illustration === 'foil' && p.parameters.includes('foil_count')) return props.settings.foil_count === 0 ? '空箔架' : `铝箔（Al）· ${props.settings.foil_count} 片`
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
watch(() => props.course.id, () => {
  selection.value = null
  panel.value = 'operation'
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
  panel.value = 'introduction'
}
async function switchOutput(output: string, event: Event) {
  try { await props.act('output', {output, enabled: (event.target as HTMLInputElement).checked}) }
  catch (e) { error.value = errorMessage(e) }
}
function partLabel(id: string) { const p = props.course.components.find(p => p.id === id); return p ? label(p) : id }
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
        <ParticleFlow v-if="course.components.some(p => p.illustration === 'source')" :source-present="settings.source_present !== 0" :spectrum="course.devices.some(d => d.kind === 'spectrum')" :foil-present="(settings.foil_count ?? 0) > 0" :enabled="animate"/>
        <button v-for="p in course.components" :key="p.id" :data-part="p.id" :data-kind="p.kind"
          :style="placement(p)" :aria-pressed="p.id === selection" @click="choose(p)">
          <ApparatusFigure :parts="[p]" :variants="variants"/><span>{{ label(p) }}<small>{{ status(p) }}</small></span>
        </button>
      </div>
      <div class="flow-note"><label><input v-model="animate" type="checkbox">动画</label><span>装置状态示意</span></div>
      <details v-if="course.connections.length" id="connections" class="wiring-info">
        <summary>装置与接线</summary>
        <ul><li v-for="edge in course.connections" :key="edge.source + '/' + edge.target + '/' + edge.label">
          {{ partLabel(edge.source) }} → {{ partLabel(edge.target) }} · {{ edge.label }}</li></ul>
      </details>
      </div>
      <aside id="component" class="setup-panel">
        <div class="setup-tabs" role="tablist" aria-label="装置工具">
          <button id="operation-tab" role="tab" :aria-selected="panel === 'operation'" aria-controls="operation-panel" @click="panel = 'operation'">操作面板</button>
          <button id="introduction-tab" role="tab" :aria-selected="panel === 'introduction'" aria-controls="introduction-panel" @click="panel = 'introduction'">装置介绍</button>
        </div>
        <div v-show="panel === 'operation'" id="operation-panel" role="tabpanel" aria-labelledby="operation-tab">
        <form v-if="params.length" @submit.prevent="apply">
          <label v-for="p in params" :key="p.key">{{ p.label }}{{ p.unit ? ' / ' + p.unit : '' }}
            <select v-if="p.options?.length" :name="p.key" :value="edits[p.key]?.value ?? settings[p.key]" @change="edit(p.key, $event)" :disabled="readonly">
              <option v-for="option in p.options" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <input v-else :name="p.key" :value="edits[p.key]?.value ?? settings[p.key]" @input="edit(p.key, $event)" type="number" :min="p.minimum" :max="p.maximum"
              :step="p.integer ? 1 : 'any'" required :disabled="readonly">
          </label>
          <p v-if="foilThickness != null" class="foil-summary">{{ settings.foil_count === 0 ? '空箔架' : `铝箔（Al）· ${settings.foil_count} 片` }}<br>总厚度 {{ foilThickness }} µm</p>
          <p v-if="particleFlow?.areal_density_g_cm2 != null" class="foil-summary">面密度 {{ Number((particleFlow.areal_density_g_cm2 * 1000).toPrecision(5)) }} mg/cm²</p>
          <button v-if="!readonly" :disabled="!!pending || !Object.keys(edits).length">应用参数</button>
        </form>
        <div class="output-controls"><label v-for="p in outputs" :key="p.id" class="output-switch"><input :id="'output-' + p.output" type="checkbox" :checked="outputEnabled[p.output!]" :disabled="readonly" @change="switchOutput(p.output!, $event)">{{ label(p) }}输出</label></div>
        </div>
        <div v-show="panel === 'introduction'" id="introduction-panel" role="tabpanel" aria-labelledby="introduction-tab">
          <template v-if="part"><h2>{{ label(part) }}</h2><p>{{ part.description }}</p><p class="part-status">{{ status(part) }}</p>
            <button v-if="part.kind === 'instrument' && part.device" id="open-instrument" @click="emit('device', part.device)">打开仪器</button>
          </template>
          <p v-else>点击装置展示详情</p>
        </div>
        <p v-if="error" class="notice" role="alert">{{ error }}</p>
      </aside>
    </div>
  </section>
</template>

<style scoped>
#setup .rig { grid-template-columns: minmax(0, 1fr) 300px; gap: 22px; }
#setup #component { margin-top: 0; padding: 0 16px 18px; background: #f2f4f6; border: 1px solid #c6cdd5; border-radius: 3px; min-height: 390px; }
.setup-tabs { display: flex; margin: 0 -16px 18px; border-bottom: 1px solid #c6cdd5; }
.setup-tabs button { flex: 1; border: 0; border-radius: 0; background: transparent; padding: 12px 6px; color: #394354; }
.setup-tabs button[aria-selected=true] { background: #fff; color: #3859d9; box-shadow: inset 0 -3px #3859d9; font-weight: 600; }
#setup #component form { display: grid; gap: 14px; margin: 0; }
#setup #component label { width: 100%; font-size: 13px; color: #283442; }
#component input, #component select { width: 100%; }
#component .output-controls { margin-top: 20px; padding-top: 16px; border-top: 1px solid #c6cdd5; display: grid; gap: 12px; }
#component .output-switch input { width: auto; }
#setup #component .foil-summary { margin: 0; color: #394354; font-size: 13px; font-variant-numeric: tabular-nums; }
#setup .apparatus button[aria-pressed=true] { border: 1px solid #7396ca; border-bottom: 4px solid #3859d9; background: #edf3fc; border-radius: 3px; }
#setup .apparatus button[aria-pressed=true] span { box-shadow: none; }
#setup .wiring-info { top: 0; }
.flow-note { display: flex; gap: 14px; align-items: baseline; margin-top: 12px; color: #536170; font-size: 12px; }
.flow-note label { white-space: nowrap; }
</style>
