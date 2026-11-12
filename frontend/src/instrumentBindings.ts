import type {Course, Device} from './types'

export function instrumentBinding(course: Course, device: string) {
  const component = course.components.find(part => part.kind === 'instrument' &&
    (part.devices?.includes(device) || part.device === device))
  const ids = component?.devices?.length ? component.devices : [component?.device ?? device]
  return {component, devices: ids.map(id => course.devices.find(item => item.id === id)!)}
}

export function instrumentDevices(course: Course): Device[] {
  const ids = new Set(course.components.filter(part => part.kind === 'instrument')
    .flatMap(part => part.devices?.length ? part.devices : part.device ? [part.device] : []))
  course.devices.forEach(device => ids.add(device.id))
  return [...ids].map(id => course.devices.find(device => device.id === id)!)
}

export function counterWindowName(course: Course, device: string) {
  const binding = instrumentBinding(course, device)
  if (binding.devices.length < 2) return null
  const index = binding.devices.findIndex(item => item.id === device)
  return `窗 ${index < 26 ? String.fromCharCode(65 + index) : index + 1}`
}

export function deviceName(course: Course, device: string) {
  const {component} = instrumentBinding(course, device)
  const definition = course.devices.find(item => item.id === device)!
  const label = component?.label ?? definition.label
  const duplicate = course.components.some(part => part.kind === 'instrument' && part !== component && part.label === label)
  const instrument = duplicate ? `${label}（${component?.id ?? device}）` : label
  const window = definition.kind === 'counter' ? counterWindowName(course, device) : null
  return window ? `${instrument} · ${window}` : instrument
}
