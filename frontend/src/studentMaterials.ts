import alpha from '../../docs/alpha.md?raw'
import beta from '../../docs/beta.md?raw'
import type {Course} from './types'

type StudentCourse = Pick<Course, 'id'> | string
const materials: Readonly<Record<string, string>> = {alpha, beta}
export function studentMarkdown(course: StudentCourse): string {
  return materials[typeof course === 'string' ? course : course.id] ?? ''
}
export function studentIntro(course: StudentCourse): string {
  const lines = studentMarkdown(course).split(/\r?\n/)
  const start = lines.findIndex(line => /^##\s+(?:实验)?简介与目的\s*$/.test(line))
  if (start < 0) return ''
  const end = lines.findIndex((line, index) => index > start && /^##\s/.test(line))
  return lines.slice(start + 1, end < 0 ? undefined : end).join('\n').trim()
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[`*]/g, '')
}
