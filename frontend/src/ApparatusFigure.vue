<script lang="ts">
// Ports refer to the original transparent image, not its visible bounding box.
const ports = new Map(Object.entries({
  source:       {inX: .36, outX: .65, beamY: .255, outY: .255},
  foil:         {inX: .31, outX: .72, beamY: .48, outY: .48},
  silicon:      {inX: .085, outX: .945, beamY: .42, outY: .325},
  'beta-probe': {inX: .06, outX: .97, beamY: .45, outY: .35},
  mca:          {inX: .025, outX: .95, beamY: .60, outY: .52},
  counter:      {inX: .05, outX: .94, beamY: .53, outY: .53},
}))
// Visible image bounds measured at opacity > 180/255, excluding soft shadows.
const silhouettes: Record<string, number[]> = {
  source: [420,480,43,34,366,444], foil: [442,480,28,18,409,463],
  silicon: [496,430,22,55,469,388], 'beta-probe': [510,450,16,63,495,415],
  mca: [560,416,7,56,533,361], counter: [426,480,12,47,403,428],
}
// Setup has a figure per selectable part; the catalog has one for the whole rig.
// Coordinate once per root, with a single read phase followed by style writes.
const layouts = new WeakMap<HTMLElement, {observer: ResizeObserver; schedule: () => void; cancel: () => void; users: number}>()
function joinLayout(root: HTMLElement, figure: HTMLElement) {
  let shared = layouts.get(root)
  if (!shared) {
    let frame = 0
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(() => { frame = 0; layout(root) })
    }
    const observer = new ResizeObserver(schedule)
    observer.observe(root)
    shared = {observer, schedule, cancel: () => cancelAnimationFrame(frame), users: 0}
    layouts.set(root, shared)
  }
  shared.users++
  shared.observer.observe(figure)
  shared.schedule()
  return {schedule: shared.schedule, release: () => {
    shared.observer.unobserve(figure)
    if (--shared.users === 0) {
      shared.observer.disconnect()
      shared.cancel()
      layouts.delete(root)
    }
  }}
}
function layout(root: HTMLElement) {
  const images = Array.from(root.querySelectorAll<HTMLImageElement>('.rig-cell img'))
  const metrics = images.map(image => {
    const box = silhouettes[image.dataset.illustration!]
    const cell = image.parentElement!
    const [width,height,left,top,right,foot] = box
    const cellWidth = cell.clientWidth, cellHeight = cell.clientHeight
    const scale = Math.min(cellWidth * .90 / (right-left), cellHeight * .82 / (foot-top))
    return {image,cellWidth,cellHeight,width,height,left,right,foot,scale,
      beam: foot-height*Number(image.dataset.beamY),
      physical: ['source','foil','silicon','beta-probe'].includes(image.dataset.illustration!)}
  })
  const physical = metrics.filter(m => m.physical)
  const beamHeight = Math.min(...physical.map(m => m.beam*m.scale))
  const symbols = Array.from(root.querySelectorAll<HTMLElement>('.rig-symbol')).map(symbol => ({
    symbol, height: symbol.parentElement!.clientHeight,
  }))
  for (const m of metrics) {
    const scale = m.physical ? beamHeight/m.beam : m.scale
    // All physical feet sit on the same plane, including instruments whose
    // transparent canvases have very different bottom padding.
    Object.assign(m.image.style, {
      width: `${m.width*scale}px`, height: `${m.height*scale}px`,
      left: `${(m.cellWidth-(m.right+m.left)*scale)/2}px`,
      top: `${m.cellHeight*.90-m.foot*scale}px`,
    })
  }
  for (const {symbol, height} of symbols) {
    // An unknown part remains a named schematic node on the particle axis.
    symbol.style.top = `${physical.length ? height*.90-beamHeight : height*.5}px`
  }
  const outer = root.querySelector<HTMLCanvasElement>('canvas.wiring')
  if (outer) outer.dispatchEvent(new Event('rig-layout'))
  const inner = root.querySelector<HTMLCanvasElement>('canvas.rig-lines')
  if (inner) inner.dispatchEvent(new Event('rig-layout'))
}
</script>

<script setup lang="ts">
import {computed, onBeforeUnmount, onMounted, ref, watch} from 'vue'
import {drawConnections} from '/draw.js'
import type {Part, Edge} from './types'

const props = defineProps<{parts: Part[]; edges?: Edge[]; variants?: Record<string, string>}>()
const nodes = computed(() => props.parts.map(part => ({part, port: ports.get(part.illustration ?? '')})))
const figure = ref<HTMLElement>()
const wiring = ref<HTMLCanvasElement>()
let shared: ReturnType<typeof joinLayout> | undefined
function paint() { shared?.schedule() }
onMounted(() => {
  const root = figure.value!.closest<HTMLElement>('.apparatus') ?? figure.value!
  shared = joinLayout(root, figure.value!)
  if (wiring.value && props.edges) drawConnections(wiring.value, props.edges)
})
onBeforeUnmount(() => shared?.release())
watch(() => props.parts.map(p => `${p.id}:${p.illustration}`).join('|'), paint, {flush: 'post'})
watch(() => props.edges, edges => {
  if (wiring.value && edges) drawConnections(wiring.value, edges)
}, {flush: 'post'})
</script>

<template>
  <div ref="figure" class="rig-figure" aria-hidden="true" @load.capture="paint">
    <canvas v-if="edges?.length" ref="wiring" class="rig-lines"></canvas>
    <div v-for="{part, port} in nodes" :key="part.id" class="rig-cell">
      <img v-if="port" :data-node="part.id" :data-illustration="part.illustration" :data-in-x="port.inX" :data-out-x="port.outX"
        :data-beam-y="port.beamY" :data-out-y="port.outY"
        :src="'/rig-' + (variants?.[part.id] ?? part.illustration) + '.webp'" alt="" draggable="false">
      <div v-else class="rig-symbol" :data-node="part.id">{{ part.label }}</div>
    </div>
  </div>
</template>
