declare module '*/draw.js' {
  import type {Part, Edge, Device, Series} from './types'
  export function drawApparatus(canvas: HTMLCanvasElement, parts: Part[], devices: Device[], connections?: Edge[]): void
  export function drawConnections(canvas: HTMLCanvasElement, connections: Edge[]): void
  export function drawSpectrum(canvas: HTMLCanvasElement, series: Series[], channels: number, roi: number[], energy: ((channel: number) => number) | null, label: string): void
  export function channelAt(canvas: HTMLCanvasElement, event: PointerEvent, channels: number): number
}
