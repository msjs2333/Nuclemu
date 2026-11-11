<script setup lang="ts">
import {computed, nextTick, ref} from 'vue'
import ApparatusFigure from './ApparatusFigure.vue'
import type {Catalog, Course, Open} from './types'
import {fmt} from './display'

const props = defineProps<{catalog: Catalog}>()
const groups = computed(() => {
  const grouped = new Map<string, Course[]>()
  for (const course of props.catalog.experiments) {
    const name = course.course || '核物理实验'
    if (!grouped.has(name)) grouped.set(name, [])
    grouped.get(name)!.push(course)
  }
  return grouped
})
const emit = defineEmits<{open: [args: Open]}>()
const entryButtons = ref<HTMLButtonElement[]>([])
function focusExperiment(id: string) {
  const button = entryButtons.value.find(b => b.dataset.experiment === id) ?? entryButtons.value[0]
  button?.focus()
}
defineExpose({focusExperiment})
const stamp = new Intl.DateTimeFormat('zh-CN', {dateStyle: 'medium', timeStyle: 'medium'})
const guide = ref<HTMLDialogElement>()
const selected = ref<Course>()
async function showGuide(course: Course) {
  selected.value = course
  await nextTick()
  guide.value?.showModal()
}
</script>

<template>
  <section id="catalog">
    <div class="heading"><h1>实验目录</h1></div>
    <div id="catalog-list"><section v-for="[group, courses] in groups" :key="group">
      <h2>{{ group }}</h2><div class="catalog-list">
      <article v-for="course in courses" :key="course.id" class="course">
        <div class="illustration"><ApparatusFigure :parts="course.components" :edges="course.connections"/></div>
        <div class="course-body"><h2>{{ course.title }}</h2><p>{{ course.question }}</p>
          <p class="subtle">{{ course.devices.map(d => d.label).join(' · ') }}</p>
          <div class="course-actions"><button ref="entryButtons" class="primary" :data-experiment="course.id" @click="emit('open', {experiment: course.id})">进入实验 →</button>
            <button @click="showGuide(course)">查看资料</button></div>
        </div>
      </article>
    </div></section></div>
    <section id="archives" v-if="catalog.drafts.length || catalog.archives.length">
      <h2>本机实验记录</h2>
      <div v-for="draft in catalog.drafts" :key="draft.id" class="archive-row">
        <span>{{ draft.title }} · 恢复至 {{ fmt(draft.time_s) }} s · {{ stamp.format(new Date(draft.updated)) }}</span><button @click="emit('open', {draft: draft.id})">打开草稿</button>
      </div>
      <div v-for="archive in catalog.archives" :key="archive.id" class="archive-row">
        <span>{{ archive.title }} · {{ fmt(archive.time_s) }} s · {{ stamp.format(new Date(archive.updated)) }}</span><button @click="emit('open', {archive: archive.id})">查看实验</button>
      </div>
    </section>
    <dialog id="guide" ref="guide" aria-labelledby="guide-title">
      <h2 id="guide-title">{{ selected?.title }}</h2>
      <div class="guide-text"><p>{{ selected?.description }}</p><p v-for="line in selected?.guide" :key="line">{{ line }}</p></div>
      <form method="dialog"><button>关闭资料</button></form>
    </dialog>
  </section>
</template>
