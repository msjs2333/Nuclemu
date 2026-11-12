<script setup lang="ts">
import {nextTick, ref} from 'vue'
import {api, filePayload} from './api'
import type {Act} from './types'
const props = defineProps<{session: string; act: Act}>()
const emit = defineEmits<{task: [fn: () => Promise<void>]; notice: [message: string]}>()
const input = ref<HTMLInputElement>(), dialog = ref<HTMLDialogElement>()
type Preview = {token: string; device: string; items: {id: string; title: string; exposure_s: number}[]; overwrite_required: boolean; notice?: string}
const preview = ref<Preview | null>(null), selected = ref(''), busy = ref(false)
let device = '', session = ''
async function inspect(file?: File) {
  const result = await api<Preview>('inspect_measurement', {session, device, ...(file ? {file: await filePayload(file)} : {})})
  if (props.session !== session) throw Error('实验已改变，请重新选择测量数据。')
  preview.value = result; selected.value = result.items[0]?.id ?? ''
  await nextTick(); dialog.value?.showModal()
}
function open(target: string, source: 'cache' | 'file') {
  device = target; session = props.session
  if (source === 'file') input.value?.click()
  else emit('task', () => inspect())
}
function fileChanged(event: Event) {
  const field = event.target as HTMLInputElement, file = field.files?.[0]
  field.value = ''
  if (file) emit('task', () => inspect(file))
}
function load() {
  if (!preview.value || busy.value) return
  const target = preview.value, identity = selected.value, original = session
  busy.value = true
  emit('task', async () => {
    try {
      await props.act('load_measurement', {token: target.token, item_id: identity, overwrite: target.overwrite_required}, original)
      dialog.value?.close()
      emit('notice', target.notice || '测量数据已载入，可继续采集。')
    } finally { busy.value = false }
  })
}
defineExpose({open})
</script>
<template>
  <input ref="input" id="measurement-file" type="file" accept=".nuclemu,.json,.csv" hidden @change="fileChanged">
  <dialog ref="dialog" id="measurement-load" aria-labelledby="measurement-load-title">
    <h2 id="measurement-load-title">载入测量数据</h2>
    <label>测量记录 <select id="measurement-choice" v-model="selected"><option v-for="item in preview?.items" :key="item.id" :value="item.id">{{ item.title }} · {{ item.exposure_s }} s</option></select></label>
    <p v-if="preview?.overwrite_required" id="measurement-overwrite">载入将覆盖当前测量数据</p>
    <p>只替换所选仪器或窗，原记录和另一窗保持不变。</p>
    <p v-if="preview?.notice" id="measurement-mode">{{ preview.notice }}</p>
    <div class="dialog-actions"><button id="measurement-cancel" :disabled="busy" autofocus @click="dialog?.close()">取消</button><button id="measurement-confirm" class="primary" :disabled="busy || !selected" @click="load">{{ preview?.overwrite_required ? '确认覆盖并载入' : '载入' }}</button></div>
  </dialog>
</template>
