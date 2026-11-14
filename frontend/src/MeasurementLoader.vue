<script setup lang="ts">
import {computed, nextTick, ref} from 'vue'
import {api, errorMessage, filePayload} from './api'
import {fmt} from './display'
import type {Act, Course} from './types'
import {deviceName, instrumentBinding} from './instrumentBindings'
const props = defineProps<{session: string; course: Course; act: Act}>()
const emit = defineEmits<{task: [fn: () => Promise<void>]; notice: [message: string]}>()
const input = ref<HTMLInputElement>(), dialog = ref<HTMLDialogElement>()
type Preview = {token: string; device: string; items: {id: string; title: string; exposure_s?: number; devices?: string[]; exposures?: Record<string, number>; historical_single?: boolean; overwrite_required?: boolean}[]; overwrite_required: boolean; notice?: string}
function exposureLabel(item: Preview['items'][number]) {
  if (!item.devices) return item.exposure_s == null ? '' : fmt(item.exposure_s) + ' s'
  return item.devices.map(id => deviceName(props.course, id) + '：' + (item.exposures?.[id] == null ? '—' : fmt(item.exposures[id]) + ' s')).join('；')
}
const preview = ref<Preview | null>(null), selected = ref(''), busy = ref(false)
const loadError = ref('')
const chosen = computed(() => preview.value?.items.find(row => row.id === selected.value))
const overwriteRequired = computed(() => chosen.value?.overwrite_required ?? preview.value?.overwrite_required ?? false)
let component = '', session = ''
async function inspect(file?: File) {
  const result = await api<Preview>('inspect_measurement', {session, component, ...(file ? {file: await filePayload(file)} : {})})
  if (props.session !== session) throw Error('实验已改变，请重新选择测量数据。')
  preview.value = result; selected.value = result.items[0]?.id ?? ''
  loadError.value = ''
  await nextTick(); dialog.value?.showModal()
}
function open(target: string, source: 'cache' | 'file') {
  component = instrumentBinding(props.course, target).component?.id ?? ''; session = props.session
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
  const overwrite = overwriteRequired.value
  busy.value = true
  emit('task', async () => {
    try {
      await props.act('load_measurement', {token: target.token, item_id: identity, overwrite}, original)
      dialog.value?.close()
      emit('notice', target.notice || '测量数据已载入，可继续采集。')
    } catch (error) { loadError.value = errorMessage(error) }
    finally { busy.value = false }
  })
}
defineExpose({open})
</script>
<template>
  <input ref="input" id="measurement-file" type="file" accept=".nuclemu,.json,.csv" hidden @change="fileChanged">
  <dialog ref="dialog" id="measurement-load" aria-labelledby="measurement-load-title">
    <h2 id="measurement-load-title">载入测量数据</h2>
    <label>测量记录 <select id="measurement-choice" v-model="selected"><option v-for="item in preview?.items" :key="item.id" :value="item.id">{{ item.title }} · {{ exposureLabel(item) }}</option></select></label>
    <p v-if="overwriteRequired" id="measurement-overwrite">载入将覆盖当前测量数据</p>
    <p v-if="chosen?.historical_single">这是历史单窗读数，仅载入文件所记录的一窗，另一窗保持原样。</p>
    <p v-else>载入作用于整台仪器，已保存的记录保持不变。</p>
    <p v-if="preview?.notice" id="measurement-mode">{{ preview.notice }}</p>
    <p v-if="loadError" id="measurement-load-error" role="alert">{{ loadError }}</p>
    <div class="dialog-actions"><button id="measurement-cancel" :disabled="busy" autofocus @click="dialog?.close()">取消</button><button id="measurement-confirm" class="primary" :disabled="busy || !selected" @click="load">{{ overwriteRequired ? '确认覆盖并载入' : '载入' }}</button></div>
  </dialog>
</template>
