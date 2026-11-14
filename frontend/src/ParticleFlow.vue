<script setup lang="ts">
import {onBeforeUnmount, onMounted, ref, watch} from 'vue'
const props = defineProps<{sourcePresent: boolean; spectrum: boolean; foilPresent: boolean; enabled: boolean}>()
const canvas = ref<HTMLCanvasElement>()
let frame = 0
// A qualitative apparatus illustration, independent of measurement data and random streams.
type Point = {x: number; y: number}
let width = 0, height = 0, ratio = 1, visible = false
let source: Point | null = null, foilIn: Point | null = null, foilOut: Point | null = null, detector: Point | null = null
let resize: ResizeObserver, visibility: IntersectionObserver
function geometry() {
  const surface = canvas.value
  if (!surface) return
  const bounds = surface.getBoundingClientRect()
  width = bounds.width; height = bounds.height; ratio = window.devicePixelRatio || 1
  surface.width = Math.round(width * ratio); surface.height = Math.round(height * ratio)
  const root = surface.parentElement!
  const point = (illustration: string, output: boolean) => {
    const node = root.querySelector<HTMLElement>(`[data-illustration="${illustration}"]`)
    if (!node) return null
    const box = node.getBoundingClientRect()
    return {x: box.left - bounds.left + box.width * Number(output ? node.dataset.outX : node.dataset.inX),
      y: box.top - bounds.top + box.height * Number(node.dataset.beamY)}
  }
  source = point('source', true); foilIn = point('foil', false); foilOut = point('foil', true)
  detector = point('silicon', false) ?? point('beta-probe', false)
  restart()
}
function paint(now: number) {
  const g = canvas.value!.getContext('2d')!
  g.setTransform(ratio, 0, 0, ratio, 0, 0)
  g.clearRect(0, 0, width, height)
  if (source && detector) {
    const distance = detector.x - source.x
    const centre = Math.atan2(detector.y - source.y, distance)
    const spread = props.spectrum ? .16 : .34
    const phase = props.enabled ? now / 2300 : .38
    const top = Math.max(14, Math.min(source.y, detector.y) - 92)
    const bottom = Math.min(height - 58, Math.max(source.y, detector.y) + 92)
    g.save(); g.beginPath(); g.rect(source.x - 28, top, distance + 42, bottom - top); g.clip()
    // Low-contrast environmental motion remains when the source is absent.
    g.fillStyle = '#748b99'; g.strokeStyle = '#748b99'
    for (let i = 0; i < 13; i++) {
      const x = source.x - 22 + (((i * .618 + phase * .13) % 1) * (distance + 14))
      const y = top + 8 + ((i * .381 + phase * .07) % 1) * (bottom - top - 16)
      g.globalAlpha = .42; g.beginPath(); g.arc(x, y, 1.8, 0, Math.PI * 2); g.fill()
      g.globalAlpha = .28; g.beginPath(); g.moveTo(x - 3.5, y + 1); g.lineTo(x, y); g.stroke()
    }
    if (props.sourcePresent) {
      const rays = props.spectrum ? 7 : 11
      for (let ray = 0; ray < rays; ray++) {
        const angle = centre + (ray / (rays - 1) - .5) * spread * 2
        const reach = Math.abs(distance / Math.cos(angle))
        for (let i = 0; i < 4; i++) {
          const position = (phase * (.8 + ((ray * 5) % 7) * .07) + i / 4 + ray * ray * .173 + ray * .317) % 1
          const x = source.x + Math.cos(angle) * reach * position
          const y = source.y + Math.sin(angle) * reach * position
          g.fillStyle = props.foilPresent && foilOut && x > foilOut.x ? '#c88448' : '#bd642e'
          g.globalAlpha = .72; g.beginPath(); g.arc(x, y, 2, 0, Math.PI * 2); g.fill()
        }
      }
      // Qualitative particles moving away on both sides of the detector face.
      // Their placement and density do not represent a scattering distribution.
      for (const side of [-1, 1]) {
        for (let ray = 0; ray < 3; ray++) {
          const position = (phase * .7 + ray * .29) % 1
          const x = detector.x - 6 - position * (36 + ray * 12)
          const y = detector.y + side * (14 + position * (42 + ray * 10))
          g.fillStyle = '#bd642e'; g.globalAlpha = .6
          g.beginPath(); g.arc(x, y, 1.8, 0, Math.PI * 2); g.fill()
        }
      }
    }
    g.restore(); g.globalAlpha = 1
  }
  frame = 0
  if (props.enabled && visible && !document.hidden) frame = requestAnimationFrame(paint)
}
function restart() {
  cancelAnimationFrame(frame); frame = 0
  if (canvas.value) paint(performance.now())
}
watch(() => [props.enabled, props.sourcePresent, props.spectrum, props.foilPresent], restart)
onMounted(() => {
  resize = new ResizeObserver(geometry); resize.observe(canvas.value!)
  visibility = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; geometry() })
  visibility.observe(canvas.value!)
  canvas.value!.parentElement!.addEventListener('load', geometry, true)
  canvas.value!.parentElement!.addEventListener('apparatus-layout', geometry)
  document.addEventListener('visibilitychange', restart)
  geometry()
})
onBeforeUnmount(() => {
  cancelAnimationFrame(frame); resize.disconnect(); visibility.disconnect()
  canvas.value?.parentElement?.removeEventListener('load', geometry, true)
  canvas.value?.parentElement?.removeEventListener('apparatus-layout', geometry)
  document.removeEventListener('visibilitychange', restart)
})
</script>

<template><canvas ref="canvas" class="particle-flow" aria-hidden="true"></canvas></template>
<style scoped>
.particle-flow { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; z-index: 2; }
</style>
