<script setup lang="ts">
import {computed, onBeforeUnmount, onMounted, ref, watch} from 'vue'
import {drawConnections} from '/draw.js'
import type {Part, Edge} from './types'

const props = defineProps<{parts: Part[]; edges?: Edge[]}>()
// Normalized positions on each illustration. The beam crosses all holders
// at the same height; the electrical output can sit above the detector window.
const ports = new Map(Object.entries({
  source:       {inX: .36, outX: .65, beamY: .255, outY: .255},
  foil:         {inX: .31, outX: .72, beamY: .48, outY: .48},
  silicon:      {inX: .085, outX: .945, beamY: .42, outY: .325},
  'beta-probe': {inX: .06, outX: .97, beamY: .45, outY: .35},
  mca:          {inX: .025, outX: .95, beamY: .60, outY: .52},
  counter:      {inX: .05, outX: .94, beamY: .53, outY: .53},
}))
const nodes = computed(() => props.parts.map(part => ({part, port: ports.get(part.illustration ?? '')})))
const figure = ref<HTMLElement>()
const wiring = ref<HTMLCanvasElement>()
let observer: ResizeObserver | undefined
function paint() {
  if (wiring.value && props.edges) drawConnections(wiring.value, props.edges)
}
onMounted(() => {
  if (!wiring.value) return
  observer = new ResizeObserver(paint)
  observer.observe(figure.value!)
  paint()
})
onBeforeUnmount(() => observer?.disconnect())
watch(() => [props.parts, props.edges], paint, {flush: 'post'})
</script>

<template>
  <div ref="figure" class="rig-figure" aria-hidden="true" @load.capture="paint">
    <canvas v-if="edges?.length" ref="wiring" class="rig-lines"></canvas>
    <div v-for="{part, port} in nodes" :key="part.id" class="rig-cell">
      <img v-if="port" :data-node="part.id" :data-in-x="port.inX" :data-out-x="port.outX"
        :data-beam-y="port.beamY" :data-out-y="port.outY" :style="{transform: 'translate(-50%, -' + port.beamY * 100 + '%)'}"
        :src="'/rig-' + part.illustration + '.webp'" alt="" draggable="false">
      <div v-else class="rig-symbol" :data-node="part.id">{{ part.label }}</div>
    </div>
  </div>
</template>
