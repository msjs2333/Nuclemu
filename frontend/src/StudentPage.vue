<script setup lang="ts">
import {computed, nextTick, onBeforeUnmount, onMounted, ref, watch} from 'vue'
import MarkdownBody from './MarkdownBody.vue'
import {studentMarkdown} from './studentMaterials'
import gui from '../../docs/gui.md?raw'
import alpha from '../../docs/alpha.md?raw'
import beta from '../../docs/beta.md?raw'
import type {Course} from './types'

const props = defineProps<{course: Course; status?: string; active: boolean}>()
const emit = defineEmits<{back: []}>()
const body = ref<HTMLElement>()
const current = ref('student-section-0')
const documentPath = ref('')
const documents: Record<string, string> = {'gui.md': gui, 'alpha.md': alpha, 'beta.md': beta}
let lessonScroll = 0
function openDocument(path: string) {
  if (!documents[path]) return
  if (!documentPath.value) lessonScroll = window.scrollY
  documentPath.value = path
  window.scrollTo(0, 0)
}
async function returnToLesson() {
  documentPath.value = ''
  await nextTick()
  window.scrollTo(0, lessonScroll)
}
function updateCurrent() {
  if (!props.active) return
  const headings = [...(body.value?.querySelectorAll<HTMLElement>('h2') ?? [])]
  if (!headings.length) return
  const atBottom = window.scrollY > 0 && window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2
  current.value = (atBottom ? headings.at(-1) : headings.filter(h => h.getBoundingClientRect().top <= 130).at(-1) ?? headings[0])!.id
}
async function observeSections() {
  await nextTick()
  updateCurrent()
}
onMounted(() => { observeSections(); window.addEventListener('scroll', updateCurrent, {passive: true}); window.addEventListener('resize', updateCurrent) })
onBeforeUnmount(() => { window.removeEventListener('scroll', updateCurrent); window.removeEventListener('resize', updateCurrent) })
const source = computed(() => documents[documentPath.value] || studentMarkdown(props.course) ||
  [...new Set([props.course.description, ...props.course.guide].filter(Boolean))].join('\n\n'))
const documentTitle = computed(() => documentPath.value === 'gui.md' ? '图形操作说明'
  : documentPath.value && documentPath.value !== props.course.id + '.md'
    ? /^#\s+(.+)$/m.exec(source.value)?.[1] ?? '实验资料' : '实验资料')
watch(source, observeSections, {flush:'post'})
watch(() => props.active, active => { if (active) observeSections() }, {flush:'post'})
const sections = computed(() => {
  let index = 0
  return [...source.value.matchAll(/^(#{2,6})\s+(.+)$/gm)].flatMap(match => {
    const id = 'student-section-' + index++
    return match[1].length === 2 ? [{id, title: match[2]}] : []
  })
})
function jump(id: string) {
  current.value = id
  const heading = body.value?.querySelector<HTMLElement>('#' + id)
  heading?.scrollIntoView({block: 'start'})
  if (heading) { heading.tabIndex = -1; heading.focus({preventScroll: true}) }
}
</script>

<template>
  <section id="student-page" class="page" aria-labelledby="student-page-title">
    <header class="section-title student-page-heading">
      <h2 id="student-page-title" tabindex="-1">{{ documentTitle }}</h2>
      <span v-if="status" id="student-page-status">{{ status }}</span>
      <button v-if="documentPath" id="reader-back-to-lesson" @click="returnToLesson">返回实验资料</button>
      <button id="student-page-back" @click="emit('back')">返回实验</button>
    </header>
    <div class="student-page-layout">
      <nav v-if="sections.length" aria-label="实验资料目录" class="student-page-contents">
        <button v-for="section in sections" :key="section.id" :aria-current="current === section.id ? 'location' : undefined" type="button" @click="jump(section.id)">{{ section.title }}</button>
      </nav>
      <article ref="body" id="student-page-body" class="student-page-body">
        <MarkdownBody v-if="source" :source="source" @document="openDocument"/>
        <p v-else>这门课程暂无学生资料。</p>
      </article>
    </div>
  </section>
</template>
