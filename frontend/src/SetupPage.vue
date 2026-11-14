<script setup lang="ts">
import {computed, nextTick, onMounted, onBeforeUnmount, ref, watch} from 'vue'
import {drawConnections} from '/draw.js'
import ApparatusFigure from './ApparatusFigure.vue'
import ParticleFlow from './ParticleFlow.vue'
import MarkdownBody from './MarkdownBody.vue'
import {apparatusOverview} from './apparatusOverview'
import {errorMessage} from './api'
import type {Act, Course, Part} from './types'

const props = defineProps<{course: Course; settings: Record<string, number>; readonly: boolean; act: Act;
  outputEnabled: Record<string, boolean>; gates: Record<string, boolean>; historicalMode?: boolean; particleFlow?: {thickness_um?: number; areal_density_g_cm2?: number} | null}>()
const animate = ref(!window.matchMedia('(prefers-reduced-motion: reduce)').matches)
const emit = defineEmits<{device: [id: string]; notice: [message: string]}>()
const selection = ref<string | null>(null)
const overview = computed(() => props.historicalMode ? '' : apparatusOverview(props.course))
const part = computed(() => props.course.components.find(p => p.id === selection.value))
const panel = ref<'operation' | 'introduction'>('operation')
const controls = computed(() => {
  // A shared physical parameter has one editor, owned by its first declared part.
  const owners = new Map<string, Part>()
  for (const part of props.course.components) for (const key of part.parameters) {
    if (!owners.has(key)) owners.set(key, part)
  }
  const groups = props.course.components.map(part => ({
    part: part as Part | null, parameters: props.course.parameters.filter(p => owners.get(p.key) === part),
  })).filter(group => group.parameters.length)
  const unbound = props.course.parameters.filter(p => !owners.has(p.key))
  if (unbound.length) groups.push({part: null, parameters: unbound})
  return groups
})
const outputs = computed(() => props.course.components.filter(p => p.output))
const foilThickness = computed(() => props.particleFlow?.thickness_um)
function label(p: Part) { return p.illustration === 'foil' ? '箔架' : p.label }
function dualCounter(p: Part) {
  return p.illustration === 'counter' && (p.devices ?? [p.device]).length === 2 &&
    (p.devices ?? []).every(id => props.course.devices.find(d => d.id === id)?.kind === 'counter')
}
const connections = computed(() => props.course.connections.filter(edge => edge.kind !== 'particle').map(edge => {
  const output = props.course.components.find(p => p.id === edge.source)?.output
  return {...edge, active: edge.kind === 'particle' ? props.settings.source_present !== 0 : !output || props.outputEnabled[output]}
}))
const variants = computed(() => Object.fromEntries(props.course.components.flatMap(p => {
  if (p.illustration === 'source' && p.parameters.includes('source_present') && props.settings.source_present === 0) return [[p.id, 'source-empty']]
  if (p.illustration === 'foil' && p.parameters.includes('foil_count') && props.settings.foil_count === 0) return [[p.id, 'foil-empty']]
  if (dualCounter(p)) return [[p.id, 'counter-dual']]
  return []
})))
function status(p: Part) {
  if (p.output) return props.outputEnabled[p.output] ? '探测开启' : '探测关闭'
  if (p.kind === 'instrument' && p.device) return (p.devices ?? [p.device]).some(id => props.gates[id]) ? '采集中' : '待机'
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
const help = ref<HTMLDialogElement>()
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
  help.value?.close()
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
async function tabKey(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  panel.value = event.key === 'Home' ? 'operation' : event.key === 'End' ? 'introduction'
    : panel.value === 'operation' ? 'introduction' : 'operation'
  await nextTick()
  document.getElementById(panel.value + '-tab')?.focus()
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
    <div class="rig"><div class="apparatus-scene"><div class="section-title"><h2>装置示意</h2>
        <button v-if="overview || course.connections.length" id="show-connections" type="button" @click="help?.showModal()">装置与接线</button>
      </div>
      <div id="apparatus" ref="diagram" class="apparatus" @load.capture="paint">
        <canvas class="wiring" ref="wiring" aria-hidden="true"></canvas>
        <ParticleFlow v-if="course.components.some(p => p.illustration === 'source')" :source-present="settings.source_present !== 0" :spectrum="course.devices.some(d => d.kind === 'spectrum')" :foil-present="(settings.foil_count ?? 0) > 0" :enabled="animate"/>
        <div v-for="p in course.components" :key="p.id" class="apparatus-part">
          <button type="button" class="part-select" :data-part="p.id" :data-kind="p.kind" :aria-pressed="p.id === selection" @click="choose(p)">
            <ApparatusFigure :parts="[p]" :variants="variants"/><span class="part-caption">{{ label(p) }}<small>{{ status(p) }}</small></span>
          </button>
          <div class="part-entry">
            <button v-if="p.id === selection && p.kind === 'instrument' && p.device" id="open-instrument" type="button" @click="emit('device', p.device)">打开{{ label(p) }}</button>
          </div>
        </div>
      </div>
      <div class="flow-note"><label><input v-model="animate" type="checkbox">动画</label></div>
      </div>
      <aside id="component" class="setup-panel">
        <div class="setup-tabs" role="tablist" aria-label="装置工具">
          <button id="operation-tab" role="tab" :aria-selected="panel === 'operation'" :tabindex="panel === 'operation' ? 0 : -1" aria-controls="operation-panel" @click="panel = 'operation'" @keydown="tabKey">操作面板</button>
          <button id="introduction-tab" role="tab" :aria-selected="panel === 'introduction'" :tabindex="panel === 'introduction' ? 0 : -1" aria-controls="introduction-panel" @click="panel = 'introduction'" @keydown="tabKey">装置介绍</button>
        </div>
        <div v-show="panel === 'operation'" id="operation-panel" role="tabpanel" aria-labelledby="operation-tab">
        <form v-if="controls.length" @submit.prevent="apply">
          <fieldset v-for="group in controls" :key="group.part?.id ?? 'unbound'">
          <legend>{{ group.part ? label(group.part) : '实验参数' }}</legend>
          <label v-for="p in group.parameters" :key="p.key">{{ p.label }}{{ p.unit ? ' / ' + p.unit : '' }}
            <select v-if="p.options?.length" :name="p.key" :value="edits[p.key]?.value ?? settings[p.key]" @change="edit(p.key, $event)" :disabled="readonly">
              <option v-for="option in p.options" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <input v-else :name="p.key" :value="edits[p.key]?.value ?? settings[p.key]" @input="edit(p.key, $event)" type="number" :min="p.minimum" :max="p.maximum"
              :step="p.integer ? 1 : 'any'" required :disabled="readonly">
          </label>
          <dl v-if="group.part?.illustration === 'foil' && foilThickness != null" class="foil-summary">
            <div><dt>样品</dt><dd>{{ settings.foil_count === 0 ? '空箔架' : `铝箔（Al）· ${settings.foil_count} 片` }}</dd></div>
            <div><dt>总厚度</dt><dd>{{ foilThickness }} µm</dd></div>
            <div v-if="particleFlow?.areal_density_g_cm2 != null"><dt>面密度</dt><dd>{{ Number((particleFlow.areal_density_g_cm2 * 1000).toPrecision(5)) }} mg/cm²</dd></div>
          </dl>
          </fieldset>
          <button v-if="!readonly" :disabled="!!pending || !Object.keys(edits).length">应用参数</button>
        </form>
        <div class="output-controls"><label v-for="p in outputs" :key="p.id" class="output-switch"><input :id="'output-' + p.output" type="checkbox" role="switch" :checked="outputEnabled[p.output!]" :disabled="readonly" @change="switchOutput(p.output!, $event)"><span>{{ label(p) }}输出</span></label></div>
        </div>
        <div v-show="panel === 'introduction'" id="introduction-panel" role="tabpanel" aria-labelledby="introduction-tab">
          <template v-if="part"><h2>{{ label(part) }}</h2><p>{{ part.description }}</p><p class="part-status">{{ status(part) }}</p>
          </template>
          <p v-else>点击装置展示详情</p>
        </div>
        <p v-if="error" class="notice" role="alert">{{ error }}</p>
      </aside>
    </div>
    <dialog ref="help" id="connections" aria-labelledby="connections-title">
      <header class="connections-heading"><h2 id="connections-title">装置与接线</h2><button id="close-connections" type="button" @click="help?.close()">关闭</button></header>
      <MarkdownBody v-if="overview" :source="overview"/>
      <ul v-else><li v-for="edge in course.connections" :key="edge.source + '/' + edge.target + '/' + edge.label">
        {{ partLabel(edge.source) }} → {{ partLabel(edge.target) }} · {{ edge.label }}</li></ul>
    </dialog>
  </section>
</template>

<style scoped>
#setup .rig { grid-template-columns: minmax(0, 1fr) 300px; gap: 20px; align-items: stretch; min-height: calc(100dvh - 74px); }
.apparatus-scene { display: flex; flex-direction: column; min-height: 0; }
#setup .apparatus { flex: 1; height: auto; min-height: 320px; background-image: none; --rig-image-height: clamp(175px, 28vh, 270px); gap: 4px; padding: 12px 8px; }
.apparatus-part { flex: 1 1 0; min-width: 0; }
#setup .apparatus .part-select { width: 100%; display: grid; grid-template-rows: var(--rig-image-height) 52px; align-items: start; padding: 0; border: 1px solid transparent; border-bottom-width: 4px; border-radius: 3px; }
#setup .apparatus .part-select:hover { border-color: var(--line); background: var(--accent-soft); }
#setup .apparatus .part-select[aria-pressed=true] { border-color: #7396ca; border-bottom-color: var(--accent); background: #edf3fc; }
#setup .apparatus .part-select[aria-pressed=true] .part-caption { box-shadow: none; }
#setup .apparatus .part-select:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
#setup .apparatus .part-caption { padding: 6px 4px; font-size: 14px; line-height: 1.4; }
#setup .apparatus .part-caption small { font-size: 12px; }
.part-entry { height: 44px; display: flex; justify-content: center; align-items: end; }
#setup .apparatus .part-entry button { flex: none; width: auto; display: block; padding: 6px 10px; border: 1px solid var(--line); border-radius: 3px; background: #fff; font-size: 13px; }
#setup .apparatus .part-entry button:hover { border-color: var(--accent); background: var(--accent-soft); }
#setup #component { margin-top: 0; padding: 0 16px 18px; background: #f2f4f6; border: 1px solid #c6cdd5; border-radius: 3px; min-height: 0; align-self: stretch; }
.setup-tabs { display: flex; margin: 0 -16px 18px; border-bottom: 1px solid #c6cdd5; }
.setup-tabs button { flex: 1; border: 0; border-radius: 0; background: transparent; padding: 12px 6px; color: #394354; }
.setup-tabs button[aria-selected=true] { background: #fff; color: #3859d9; box-shadow: inset 0 -3px #3859d9; font-weight: 600; }
#setup #component form { display: grid; gap: 14px; margin: 0; }
#setup #component fieldset { min-width: 0; margin: 0; padding: 0; border: 0; display: grid; gap: 12px; }
#setup #component fieldset + fieldset { padding-top: 16px; border-top: 1px solid #c6cdd5; }
#setup #component legend { padding: 0; margin-bottom: 10px; font-size: 14px; font-weight: 600; }
#setup #component label { width: 100%; font-size: 14px; color: #283442; }
#component input, #component select { width: 100%; }
#component .output-controls { margin-top: 20px; padding-top: 16px; border-top: 1px solid #c6cdd5; display: grid; gap: 12px; }
#component .output-switch input { appearance: none; flex: 0 0 34px; width: 34px; height: 20px; margin: 0; padding: 0; border: 1px solid #7b8792; border-radius: 12px; background: #a6afb7; position: relative; cursor: pointer; }
#component .output-switch input::after { content: ''; position: absolute; width: 14px; height: 14px; top: 2px; left: 2px; background: #fff; border-radius: 50%; }
#component .output-switch input:checked { background: var(--accent); border-color: var(--accent); }
#component .output-switch input:checked::after { left: 16px; }
#component .output-switch input:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
#component .output-switch input:disabled { cursor: default; opacity: .55; }
#setup #component .foil-summary { display: grid; gap: 6px; margin: 0; padding-top: 4px; color: #394354; font-size: 13px; font-variant-numeric: tabular-nums; }
.foil-summary > div { display: flex; justify-content: space-between; gap: 12px; }
.foil-summary dd { margin: 0; text-align: right; }
#show-connections { font-size: 13px; }
#connections { width: min(720px, calc(100vw - 64px)); max-width: none; margin: auto; padding: 20px 24px; font-size: 15px; }
.connections-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.connections-heading h2 { margin: 0; }
#connections :deep(.markdown-body) { max-width: none; font-size: 15px; line-height: 1.75; }
.flow-note { display: flex; align-items: baseline; padding: 10px 0 0; color: #536170; font-size: 13px; }
.flow-note label { white-space: nowrap; }
</style>
