<script setup lang="ts">
import {computed, onMounted, onBeforeUnmount, ref, watch} from 'vue'
import {drawConnections} from '/draw.js'
import ApparatusFigure from './ApparatusFigure.vue'
import {errorMessage} from './api'
import type {Act, Course, Part} from './types'

const props = defineProps<{course: Course; settings: Record<string, number>; readonly: boolean; act: Act}>()
const emit = defineEmits<{device: [id: string]; notice: [message: string]}>()
const selection = ref(props.course.components[0]?.id)
const part = computed(() => props.course.components.find(p => p.id === selection.value))
const params = computed(() => props.course.parameters.filter(p => part.value?.parameters.includes(p.key)))
const edits = ref<Record<string, number>>({})
const error = ref('')
const diagram = ref<HTMLElement>()
const wiring = ref<HTMLCanvasElement>()
let observer: ResizeObserver
function paint() {
  if (wiring.value?.clientWidth) drawConnections(wiring.value, props.course.connections)
}
onMounted(() => { observer = new ResizeObserver(paint); observer.observe(diagram.value!); paint() })
onBeforeUnmount(() => observer.disconnect())
watch([part, () => props.settings], () => {
  edits.value = Object.fromEntries(params.value.map(p => [p.key, props.settings[p.key]]))
  error.value = ''
}, {immediate: true})
function choose(p: Part) {
  selection.value = p.id
  if (p.kind === 'instrument' && p.device) emit('device', p.device)
}
function partLabel(id: string) { return props.course.components.find(p => p.id === id)?.label ?? id }
async function apply() {
  try {
    await props.act('configure', {values: {...edits.value}})
    emit('notice', '已更新装置工况。')
  } catch (e) { error.value = errorMessage(e) }
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
      <div id="connections" class="connections"><span v-for="edge in course.connections" :key="edge.source + '/' + edge.target + '/' + edge.label">
        {{ partLabel(edge.source) }} {{ edge.kind === 'particle' ? '⇢' : '─→' }} {{ partLabel(edge.target) }} · {{ edge.label }}
      </span></div></div>
      <aside id="component" v-if="part"><h2>{{ part.label }}</h2><p>{{ part.description }}</p>
        <form v-if="params.length" @submit.prevent="apply">
          <label v-for="p in params" :key="p.key">{{ p.label }}{{ p.unit ? ' / ' + p.unit : '' }}
            <select v-if="p.options?.length" :name="p.key" v-model.number="edits[p.key]" :disabled="readonly">
              <option v-for="option in p.options" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <input v-else :name="p.key" v-model.number="edits[p.key]" type="number" :min="p.minimum" :max="p.maximum"
              :step="p.integer ? 1 : 'any'" required :disabled="readonly">
          </label>
          <button v-if="!readonly">应用参数</button>
        </form>
        <p v-if="error" class="notice" role="alert">{{ error }}</p>
        <button v-if="part.device" @click="emit('device', part.device)">打开{{ course.devices.find(d => d.id === part?.device)?.label }}</button>
      </aside>
    </div>
  </section>
</template>
