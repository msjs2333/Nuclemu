<script setup lang="ts">
import {computed, nextTick, ref} from 'vue'
import MarkdownBody from './MarkdownBody.vue'
import {studentMarkdown} from './studentMaterials'
import type {Course} from './types'

const props = defineProps<{course: Course; status?: string}>()
const dialog = ref<HTMLDialogElement>()
const closeButton = ref<HTMLButtonElement>()
let returnFocus: HTMLElement | null = null
const source = computed(() => studentMarkdown(props.course))
const sections = computed(() => {
  let index = 0
  return [...source.value.matchAll(/^(#{2,6})\s+(.+)$/gm)].flatMap(match => {
    const id = 'student-section-' + index++
    return match[1].length === 2 ? [{id, title: match[2]}] : []
  })
})
async function open() {
  if (dialog.value?.open) return
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  dialog.value?.showModal()
  await nextTick()
  closeButton.value?.focus()
}
function close() { dialog.value?.close() }
function restoreFocus() { if (returnFocus?.isConnected) returnFocus.focus() }
function jump(id: string) {
  dialog.value?.querySelector<HTMLElement>('#' + id)?.scrollIntoView({block: 'start'})
}
defineExpose({open, close})
</script>

<template>
  <dialog id="student-reader" ref="dialog" aria-labelledby="student-reader-title" @cancel.prevent="close" @close="restoreFocus">
    <header class="reader-heading">
      <div><h2 id="student-reader-title">{{ course.title }}</h2><p v-if="status" id="student-reader-status">{{ status }}</p></div>
      <button id="student-reader-close" ref="closeButton" type="button" aria-label="关闭学生资料" @click="close">关闭</button>
    </header>
    <div class="reader-layout">
      <nav v-if="sections.length" aria-label="学生资料目录" class="reader-contents">
        <button v-for="section in sections" :key="section.id" type="button" @click="jump(section.id)">{{ section.title }}</button>
      </nav>
      <article id="student-reader-body" class="reader-body">
        <MarkdownBody v-if="source" :source="source"/>
        <p v-else>这门课程暂无学生资料。</p>
      </article>
    </div>
  </dialog>
</template>

<style scoped>
#student-reader { width: min(1080px, calc(100vw - 96px)); max-width: none; max-height: 88dvh; padding: 0; color: var(--ink, #000); }
.reader-heading { display: flex; align-items: start; justify-content: space-between; gap: 24px; padding: 20px 26px; border-bottom: 1px solid var(--line, #d2d9de); }
.reader-heading h2 { margin: 0 0 6px; font-size: 21px; }
.reader-heading p { color: var(--muted, #48566a); font-size: 13px; }
.reader-heading button { flex: none; }
.reader-layout { display: grid; grid-template-columns: 190px minmax(0, 1fr); max-height: calc(88dvh - 104px); overflow: auto; }
.reader-contents { position: sticky; top: 0; align-self: start; display: grid; gap: 4px; padding: 24px 16px; }
.reader-contents button { padding: 7px 10px; border-color: transparent; text-align: left; font-size: 13px; font-weight: 500; line-height: 1.5; }
.reader-contents button:hover, .reader-contents button:focus-visible { color: var(--accent, #3859d9); background: #f2f5ff; }
.reader-body { min-width: 0; max-width: 78ch; padding: 24px 30px 40px 18px; font-size: 15px; }
</style>
