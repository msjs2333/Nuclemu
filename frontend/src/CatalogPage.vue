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
function instruments(course: Course) {
  const counts = new Map<string, number>()
  for (const device of course.devices) counts.set(device.label, (counts.get(device.label) ?? 0) + 1)
  return [...counts].map(([name, count]) => count === 1 ? name : name + '（' + count + ' 台）').join('、')
}
const stamp = new Intl.DateTimeFormat('zh-CN', {dateStyle: 'medium', timeStyle: 'medium'})
const archives = computed(() => [
  ...props.catalog.drafts.map(row => ({...row, draft: true})),
  ...props.catalog.archives.map(row => ({...row, draft: false})),
])
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
    <p v-if="!catalog.experiments.length" class="catalog-empty">没有可用实验。</p>
    <div id="catalog-list"><section v-for="[group, courses] in groups" :key="group">
      <h2>{{ group }}</h2><div class="catalog-list">
      <article v-for="course in courses" :key="course.id" class="course">
        <div class="illustration"><ApparatusFigure :parts="course.components" :edges="course.connections"/></div>
        <div class="course-body"><h3>{{ course.title }}</h3><p class="course-question">{{ course.question }}</p>
          <p class="course-instruments">{{ instruments(course) }}</p>
          <div class="course-actions"><button ref="entryButtons" class="primary" :data-experiment="course.id" @click="emit('open', {experiment: course.id})">进入实验</button>
            <button @click="showGuide(course)">查看资料</button></div>
        </div>
      </article>
    </div></section></div>
    <section id="archives">
      <h2>本机实验记录</h2>
      <table v-if="archives.length" class="archive-table" aria-label="本机实验记录">
        <thead><tr><th scope="col">实验</th><th scope="col">仿真时刻</th><th scope="col">保存时间</th><th scope="col">操作</th></tr></thead>
        <tbody><tr v-for="row in archives" :key="row.id" class="archive-row">
          <th scope="row">{{ row.title }}</th><td class="archive-duration" data-label="仿真时刻">{{ fmt(row.time_s) }} s</td>
          <td class="archive-date" data-label="保存时间"><time :datetime="row.updated">{{ stamp.format(new Date(row.updated)) }}</time></td>
          <td><button @click="emit('open', row.draft ? {draft: row.id} : {archive: row.id})">{{ row.draft ? '打开草稿' : '查看实验' }}</button></td>
        </tr></tbody>
      </table>
      <p v-else class="archive-empty">还没有本机实验记录。</p>
    </section>
    <dialog id="guide" ref="guide" aria-labelledby="guide-title">
      <h2 id="guide-title">{{ selected?.title }}</h2>
      <div class="guide-text"><p>{{ selected?.description }}</p><p v-for="line in selected?.guide" :key="line">{{ line }}</p></div>
      <form method="dialog"><button>关闭资料</button></form>
    </dialog>
  </section>
</template>
