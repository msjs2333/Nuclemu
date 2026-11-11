<script setup lang="ts">
import {nextTick, onBeforeUnmount, onMounted, ref, watch} from 'vue'

type Command = 'file' | 'acquisition' | 'analysis' | 'display'
const commands: {id: Command; label: string}[] = [
  {id: 'file', label: '文件'}, {id: 'acquisition', label: '采集'},
  {id: 'analysis', label: '分析'}, {id: 'display', label: '显示'},
]
const props = defineProps<{analysis: boolean; display: boolean}>()
const opened = ref<Command | null>(null)
const root = ref<HTMLElement>()
function unavailable(id: Command) {
  return id === 'analysis' && !props.analysis || id === 'display' && !props.display
}
function close(returnFocus = false) {
  const id = opened.value
  opened.value = null
  if (id && returnFocus) root.value?.querySelector<HTMLButtonElement>('#menu-' + id)?.focus()
}
function outside(e: Event) {
  // The spectrum and its ROI inspector share a channel axis during a drag.
  if (opened.value === 'analysis' && e.target instanceof Element && e.target.closest('#plot')) {
    if (e.type === 'pointerdown') e.preventDefault()
    return
  }
  if (opened.value && e.target instanceof Node && !root.value?.contains(e.target)) close()
}
async function first(id: Command) {
  opened.value = id
  await nextTick()
  root.value?.querySelector<HTMLElement>('#panel-' + id + ' :is(button, input, select, summary):not(:disabled)')?.focus()
}
function escape(e: KeyboardEvent) {
  if (e.key === 'Escape' && opened.value) { e.preventDefault(); close(true) }
}
watch(() => [props.analysis, props.display], () => { if (opened.value && unavailable(opened.value)) close() })
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  document.addEventListener('focusin', outside)
  document.addEventListener('keydown', escape)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('focusin', outside)
  document.removeEventListener('keydown', escape)
})
function open(id: Command) { opened.value = id }
defineExpose({close, open})
</script>

<template>
  <div ref="root" class="command-bar" role="group" aria-label="实验菜单">
    <div v-for="cmd in commands" :key="cmd.id" class="command-group">
      <button :id="'menu-' + cmd.id" type="button" class="command-trigger"
        :aria-controls="'panel-' + cmd.id" :aria-expanded="opened === cmd.id" :disabled="unavailable(cmd.id)"
        @click="opened = opened === cmd.id ? null : cmd.id" @keydown.down.prevent="first(cmd.id)">{{ cmd.label }}</button>
      <section :id="'panel-' + cmd.id" class="command-panel" :aria-labelledby="'menu-' + cmd.id" v-show="opened === cmd.id">
        <slot :name="cmd.id" />
      </section>
    </div>
  </div>
</template>
