import type {Course, Parameter, Segment} from './types'

const formatter = new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 3})
export function fmt(value: number) { return formatter.format(value) }
export function exposure(s: Segment) { return s.end_s - s.start_s }
export function segmentName(s: Segment, i: number) { return '测量 ' + s.acquisition + ' · 段 ' + (i + 1) }
export function parameterText(p: Parameter, value: number) {
  const option = p.options?.find(o => o.value === value)
  if (option) return option.label
  return fmt(value) + (p.unit ? ' ' + p.unit : '')
}
export function describe(course: Course, settings: Record<string, number>) {
  return course.parameters.map(p => p.label + ' ' + parameterText(p, settings[p.key])).join(' · ')
}
export function inputValue(e: Event) { return (e.target as HTMLInputElement).value }
export function indexValue(e: Event) { const value = inputValue(e); return value === '' ? null : Number(value) }
