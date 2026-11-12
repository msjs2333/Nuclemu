import source from '../../docs/apparatus-overview.md?raw'
import type {Course} from './types'

const titles: Readonly<Record<string, string>> = {alpha: 'α 能量损失', beta: 'β 吸收'}
const sections = Object.fromEntries(source.split(/^## /m).slice(1).map(section => {
  const newline = section.indexOf('\n')
  return [section.slice(0, newline).trim(), section.slice(newline + 1).trim()]
}))
export function apparatusOverview(course: Pick<Course, 'id'>): string {
  return sections[titles[course.id] ?? ''] ?? ''
}
