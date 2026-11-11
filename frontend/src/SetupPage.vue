<script setup lang="ts">
import {computed, nextTick, onMounted, onBeforeUnmount, ref, watch} from 'vue'
import {drawConnections} from '/draw.js'
import ApparatusFigure from './ApparatusFigure.vue'
import {errorMessage} from './api'
import {counterMode} from './counterMode'
import type {Act, Course, Part} from './types'

const props = defineProps<{course: Course; settings: Record<string, number>; readonly: boolean; act: Act}>()
const emit = defineEmits<{device: [id: string]; notice: [message: string]}>()
const selection = ref(props.course.components[0]?.id)
const part = computed(() => props.course.components.find(p => p.id === selection.value))
const mode = computed(() => counterMode(props.course))
const modeSource = computed(() => mode.value?.source === part.value?.id ? mode.value : null)
const params = computed(() => props.course.parameters.filter(p => part.value?.parameters.includes(p.key) && p.key !== modeSource.value?.parameter.key))
type Edit = {base: number; value: number | string}
const edits = ref<Record<string, Edit>>({})
const pending = ref<Record<string, Edit> | null>(null)
const error = ref('')
const diagram = ref<HTMLElement>()
const wiring = ref<HTMLCanvasElement>()
let observer: ResizeObserver
function paint() {
  if (wiring.value?.clientWidth) drawConnections(wiring.value, props.course.connections)
}
onMounted(() => { observer = new ResizeObserver(paint); observer.observe(diagram.value!); paint() })
onBeforeUnmount(() => observer.disconnect())
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
  if (p.kind === 'instrument' && p.device) emit('device', p.device)
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
      <div id="apparatus" ref="diagram" class="apparatus" @load.capture="paint">
        <canvas class="wiring" ref="wiring" aria-hidden="true"></canvas>
        <button v-for="p in course.components" :key="p.id" :data-part="p.id" :data-kind="p.kind"
          :aria-pressed="p.id === selection" @click="choose(p)">
          <ApparatusFigure :parts="[p]"/><span>{{ p.label }}</span>
        </button>
      </div>
      </div>
      <aside id="component" v-if="part"><h2>{{ part.label }}</h2><p>{{ part.description }}</p>
        <button v-if="modeSource" @click="emit('device', modeSource.device)">在计数器选择{{ modeSource.parameter.label }}</button>
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
        <button v-if="part.device" @click="emit('device', part.device)">打开{{ course.devices.find(d => d.id === part?.device)?.label }}</button>
        <details v-if="course.connections.length" id="connections">
          <summary>装置接线</summary>
          <ul><li v-for="edge in course.connections" :key="edge.source + '/' + edge.target + '/' + edge.label">
            {{ partLabel(edge.source) }} → {{ partLabel(edge.target) }} · {{ edge.label }}
          </li></ul>
        </details>
      </aside>
    </div>
  </section>
</template>
