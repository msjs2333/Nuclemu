<script setup lang="ts">
import {nextTick, ref} from 'vue'
import {api, filePayload} from './api'
import {fmt} from './display'
import {counterWindowName, deviceName} from './instrumentBindings'
import type {Act, Course, State} from './types'
const props = defineProps<{session: string; course: Course; act: Act}>()
const emit = defineEmits<{task: [fn: () => Promise<void>]; notice: [message: string]}>()
type Choice = State['records'][number]
const fileInput = ref<HTMLInputElement>(), dialog = ref<HTMLDialogElement>()
const choices = ref<Choice[]>([]), selected = ref('')
let session = '', token = ''
function chooseFile() { session = props.session; fileInput.value?.click() }
function choiceLabel(choice: Choice) {
  const name = (device: string) => props.course.devices.some(item => item.id === device)
    ? deviceName(props.course, device) : '测量仪器'
  if (choice.kind === 'calibration') return `${choice.title} · ${name(choice.device)} · 能量刻度`
  if (choice.group) {
    const members = choice.group.members.map(device => {
      const measured = choice.measurements?.find(item => item.device === device)
      return `${name(device)} · ${measured ? fmt(measured.exposure_s) + ' s' : '无读数'}`
    })
    return `${choice.title} · ${members.join('；')}`
  }
  const single = counterWindowName(props.course, choice.device) ? ' · 单窗读数' : ''
  return `${choice.title} · ${name(choice.device)}${single} · ${fmt(choice.exposure_s ?? 0)} s`
}
function inspect(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0], target = session
  input.value = ''
  if (!file) return
  emit('task', async () => {
    const result = await api<{token: string; items: Choice[]}>('inspect_import', {session: target, file: await filePayload(file)})
    if (props.session !== target) throw Error('实验已变更，请重新选择文件。')
    session = target; token = result.token; choices.value = result.items; selected.value = result.items[0]?.id ?? ''
    await nextTick(); dialog.value?.showModal()
  })
}
function apply() {
  const target = session, round = token, identity = selected.value
  emit('task', async () => {
    await props.act('import_item', {token: round, item_id: identity}, target)
    dialog.value?.close()
    emit('notice', '已导入为独立记录，当前测量与原有缓存保留。')
  })
}
</script>
<template>
  <button id="choose-import" @click="chooseFile">导入记录</button>
  <input ref="fileInput" id="import-saved-file" type="file" accept=".nuclemu,.json,.csv" hidden @change="inspect">
  <dialog ref="dialog" id="import-choice" aria-labelledby="import-title">
    <h2 id="import-title">选择一份记录导入</h2>
    <label>记录 <select id="import-selection" v-model="selected"><option v-for="choice in choices" :key="choice.id" :value="choice.id">{{ choiceLabel(choice) }}</option></select></label>
    <p>导入只添加实验记录，不会替换仪器当前测量。</p>
    <div class="dialog-actions"><button id="cancel-import" @click="dialog?.close()">取消</button><button id="confirm-import" class="primary" :disabled="!selected" @click="apply">导入所选记录</button></div>
  </dialog>
</template>
