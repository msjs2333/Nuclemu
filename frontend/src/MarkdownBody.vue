<script lang="ts">
import {computed, defineComponent, h} from 'vue'
import type {VNodeChild} from 'vue'

type Block = {kind: 'heading'; level: number; text: string; id: string}
  | {kind: 'paragraph' | 'code'; text: string}
  | {kind: 'list'; ordered: boolean; items: string[]}
  | {kind: 'table'; rows: string[][]}
function blocks(source: string): Block[] {
  const lines = source.split(/\r?\n/), result: Block[] = []
  let i = 0, heading = 0
  const cells = (line: string) => line.trim().replace(/^\||\|$/g, '').split('|').map(cell => cell.trim())
  const startsBlock = (line: string) => /^(#{1,6}\s|```|\s*(?:[-*] |\d+\. )|\|)/.test(line)
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) { i++; continue }
    const title = /^(#{1,6})\s+(.+)$/.exec(line)
    if (title) {
      if (title[1].length > 1) result.push({kind: 'heading', level: title[1].length,
        text: title[2], id: 'student-section-' + heading++})
      i++; continue
    }
    if (line.startsWith('```')) {
      const text: string[] = []; i++
      while (i < lines.length && !lines[i].startsWith('```')) text.push(lines[i++])
      if (i < lines.length) i++
      result.push({kind: 'code', text: text.join('\n')}); continue
    }
    if (line.trim().startsWith('|') && i + 1 < lines.length && cells(lines[i + 1]).every(cell => /^:?-+:?$/.test(cell))) {
      const rows = [cells(line)]; i += 2
      while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(cells(lines[i++]))
      result.push({kind: 'table', rows}); continue
    }
    const list = /^\s*(?:(\d+)\. |[-*] )(.+)$/.exec(line)
    if (list) {
      const ordered = !!list[1], items: string[] = []
      while (i < lines.length) {
        const item = /^\s*(?:(\d+)\. |[-*] )(.+)$/.exec(lines[i])
        if (!item || !!item[1] !== ordered) break
        items.push(item[2]); i++
      }
      result.push({kind: 'list', ordered, items}); continue
    }
    const paragraph = [line]; i++
    while (i < lines.length && lines[i].trim() && !startsBlock(lines[i])) paragraph.push(lines[i++])
    result.push({kind: 'paragraph', text: paragraph.join(' ')})
  }
  return result
}
function inline(text: string): VNodeChild[] {
  const parts: VNodeChild[] = [], token = /(`[^`]+`|\*\*[^*]+\*\*|\[([^\]]+)\]\(([^)]+)\))/g
  let from = 0
  for (const match of text.matchAll(token)) {
    parts.push(text.slice(from, match.index))
    if (match[0].startsWith('`')) parts.push(h('code', match[0].slice(1, -1)))
    else if (match[0].startsWith('**')) parts.push(h('strong', match[0].slice(2, -2)))
    else if (/^https?:\/\//i.test(match[3])) parts.push(h('a', {href: match[3], target: '_blank', rel: 'noopener noreferrer'}, match[2]))
    else parts.push(match[2])
    from = match.index! + match[0].length
  }
  parts.push(text.slice(from))
  return parts
}
export default defineComponent({
  props: {source: {type: String, required: true}},
  setup(props) {
    const content = computed(() => blocks(props.source))
    return () => h('div', {class: 'markdown-body'}, content.value.map(block => {
      if (block.kind === 'heading') return h('h' + block.level, {id: block.id}, inline(block.text))
      if (block.kind === 'paragraph') return h('p', inline(block.text))
      if (block.kind === 'code') return h('pre', [h('code', block.text)])
      if (block.kind === 'list') return h(block.ordered ? 'ol' : 'ul', block.items.map(item => h('li', inline(item))))
      if (block.kind === 'table') return h('div', {class: 'reader-table', tabindex: 0, role: 'region', 'aria-label': '学生记录表，可横向滚动'},
        [h('table', [h('thead', [h('tr', block.rows[0].map(cell => h('th', {scope: 'col'}, inline(cell))))]),
          h('tbody', block.rows.slice(1).map(row => h('tr', row.map(cell => h('td', inline(cell))))))])])
    }))
  },
})
</script>

<style scoped>
.markdown-body { color: var(--ink, #000); line-height: 1.85; overflow-wrap: anywhere; }
.markdown-body :deep(h2) { margin: 30px 0 12px; font-size: 20px; }
.markdown-body :deep(h2:first-child) { margin-top: 0; }
.markdown-body :deep(h3) { margin: 24px 0 8px; font-size: 17px; }
.markdown-body :deep(p), .markdown-body :deep(ul), .markdown-body :deep(ol) { margin: 0 0 15px; }
.markdown-body :deep(li) { padding-left: 4px; margin-bottom: 10px; }
.markdown-body :deep(pre) { margin: 16px 0; padding: 14px 16px; background: #f7f9fa; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.65; }
.markdown-body :deep(code) { font-size: .9em; }
.markdown-body :deep(a) { color: var(--accent, #3859d9); text-underline-offset: 3px; }
.markdown-body :deep(.reader-table) { max-width: 100%; margin: 18px 0; overflow: auto; }
.markdown-body :deep(table) { min-width: max-content; font-size: 14px; }
.markdown-body :deep(td), .markdown-body :deep(th) { padding: 9px 12px; }
</style>
