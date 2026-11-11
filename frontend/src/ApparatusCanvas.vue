<script setup lang="ts">
import {onMounted, onBeforeUnmount, ref, watch} from 'vue'
import {drawApparatus} from '/draw.js'
import type {Part, Device, Edge} from './types'

const props = defineProps<{parts: Part[]; devices: Device[]; edges?: Edge[]}>()
const canvas = ref<HTMLCanvasElement>()
let observer: ResizeObserver
function paint() {
  if (canvas.value?.clientWidth) drawApparatus(canvas.value, props.parts, props.devices, props.edges)
}
onMounted(() => {
  observer = new ResizeObserver(paint)
  observer.observe(canvas.value!)
  paint()
})
watch(() => [props.parts, props.devices, props.edges], paint, {flush: 'post'})
onBeforeUnmount(() => observer.disconnect())
</script>

<template><canvas ref="canvas" aria-hidden="true"></canvas></template>
