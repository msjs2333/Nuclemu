import type {Course} from './types'

// Move a source editor only when the definition gives one unambiguous destination.
export function counterMode(course: Course) {
  const candidates = course.devices.filter(d => d.kind === 'counter').flatMap(device => {
    const conditions = Object.entries(device.background_conditions ?? {})
    if (conditions.length !== 1) return []
    const [key, background] = conditions[0]
    const parameter = course.parameters.find(p => p.key === key)
    if (parameter?.options?.length !== 2 || !parameter.options.some(o => o.value === background)) return []
    const sources = course.components.filter(p => p.parameters.includes(key))
    if (sources.length !== 1 || sources[0].kind !== 'source' || sources[0].parameters.length !== 1) return []
    return [{device: device.id, source: sources[0].id, parameter, background}]
  })
  return candidates.length === 1 ? candidates[0] : null
}
