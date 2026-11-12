<script setup lang="ts">
import {computed, ref} from 'vue'
import MarkdownBody from './MarkdownBody.vue'
import {studentMarkdown} from './studentMaterials'
import type {Course} from './types'

const props = defineProps<{course: Course; status?: string}>()
const emit = defineEmits<{back: []}>()
const body = ref<HTMLElement>()
const source = computed(() => studentMarkdown(props.course))
const sections = computed(() => {
  let index = 0
  return [...source.value.matchAll(/^(#{2,6})\s+(.+)$/gm)].flatMap(match => {
    const id = 'student-section-' + index++
    return match[1].length === 2 ? [{id, title: match[2]}] : []
  })
})
function jump(id: string) {
  const heading = body.value?.querySelector<HTMLElement>('#' + id)
  heading?.scrollIntoView({block: 'start'})
  if (heading) { heading.tabIndex = -1; heading.focus({preventScroll: true}) }
}
</script>

<template>
  <section id="student-page" class="page" aria-labelledby="student-page-title">
    <header class="section-title student-page-heading">
      <div><h2 id="student-page-title" tabindex="-1">实验资料</h2><p>{{ course.title }}</p></div>
      <button id="student-page-back" @click="emit('back')">返回实验</button>
    </header>
    <p v-if="status" id="student-page-status" role="status">{{ status }}</p>
    <div class="student-page-layout">
      <nav v-if="sections.length" aria-label="实验资料目录" class="student-page-contents">
        <button v-for="section in sections" :key="section.id" type="button" @click="jump(section.id)">{{ section.title }}</button>
      </nav>
      <article ref="body" id="student-page-body" class="student-page-body">
        <MarkdownBody v-if="source" :source="source"/>
        <p v-else>这门课程暂无学生资料。</p>
      </article>
    </div>
  </section>
</template>
