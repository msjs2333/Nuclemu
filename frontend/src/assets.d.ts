declare module '*?raw' { const source: string; export default source }

declare module '*/draw.js' {
  import type {Edge, Series} from './types'
  export function drawConnections(canvas: HTMLCanvasElement, connections: Edge[]): void
  type ChannelRange = [number, number]
  export function spectrumExtent(series: Series[], channels: number): {range: ChannelRange; maximum: number}
  export function drawSpectrum(canvas: HTMLCanvasElement, series: Series[], channels: number, roi: number[], energy: ((channel: number) => number) | null, label: string, range: ChannelRange, maximum: number): void
  export function pointerChannels(canvas: HTMLCanvasElement, range: ChannelRange): (clientX: number) => number
}
