<script setup lang="ts">
import {computed, ref} from 'vue'
import ApparatusFigure from './ApparatusFigure.vue'
import type {Catalog, Course, Open} from './types'
import {studentIntro} from './studentMaterials'

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
const emit = defineEmits<{open: [args: Open]; load: []}>()
const entryButtons = ref<HTMLButtonElement[]>([])
const covers: Readonly<Record<string, {src: string; alt: string}>> = {
  alpha: {src: '/cover-alpha-energy-loss.webp', alt: 'α 粒子符号进入铝原子结构，跨尺度示意，非按比例。'},
  beta: {src: '/cover-beta-absorption.webp', alt: 'β 粒子穿过铝吸收片，跨尺度定性示意，非按比例，点数和路径不代表实测计数。'},
}
function focusExperiment(id: string) {
  const button = entryButtons.value.find(b => b.dataset.experiment === id) ?? entryButtons.value[0]
  button?.focus()
}
defineExpose({focusExperiment})
</script>

<template>
  <section id="catalog">
    <div class="heading"><h1>实验目录</h1><button id="catalog-load" @click="emit('load')">从文件加载实验</button></div>
    <p v-if="!catalog.experiments.length" class="catalog-empty">没有可用实验。</p>
    <div id="catalog-list"><section v-for="[group, courses] in groups" :key="group">
      <h2>{{ group }}</h2><div class="catalog-list">
      <article v-for="course in courses" :key="course.id" class="course">
        <div class="illustration"><img v-if="covers[course.id]" :src="covers[course.id].src" :alt="covers[course.id].alt"><ApparatusFigure v-else :parts="course.components" :edges="course.connections"/></div>
        <p v-if="covers[course.id]" class="course-caption">跨尺度定性示意，非按比例</p>
        <div class="course-body"><h3>{{ course.title }}</h3><p class="course-question course-intro">{{ studentIntro(course) || course.question }}</p></div>
        <div class="course-actions"><button ref="entryButtons" class="primary" :data-experiment="course.id" @click="emit('open', {experiment: course.id})">进入实验</button></div>
      </article>
    </div></section></div>

  </section>
</template>
