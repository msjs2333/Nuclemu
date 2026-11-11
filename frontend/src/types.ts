export interface Parameter {
  key: string; label: string; unit: string; minimum: number; maximum: number; integer: boolean
  options?: {value: number; label: string}[]
}
export interface Device {
  id: string; label: string; kind: string; channels: number; calibration_parameters: string[]
  background_conditions?: Record<string, number>
}
export interface Part {
  id: string; label: string; kind: string; description: string; parameters: string[]; device: string | null
  illustration?: string | null
}
export interface Edge { source: string; target: string; kind: string; label: string }
export interface Course {
  id: string; title: string; question: string; description: string; guide: string[]
  course?: string
  parameters: Parameter[]; devices: Device[]; components: Part[]; connections: Edge[]
}
export interface Archive { id: string; title: string; time_s: number; updated: string }
export interface Catalog { experiments: Course[]; drafts: Archive[]; archives: Archive[] }
export interface Segment {
  acquisition: number; start_s: number; end_s: number; settings: Record<string, number>
  readings: Record<string, number[]>
}
export interface Calibration {
  channel1: number; channel2: number; energy1: number; energy2: number
  conditions: [string, number][]
}
export interface CalibrationContext {
  device: string; selected: number | null; settings: Record<string, number>
}
export interface State {
  id: string; experiment: string; definition: Course; settings: Record<string, number>
  time_s: number; remaining_s: number | null; paused: boolean; running: boolean; frozen: boolean; speed: number
  dirty: boolean; readonly: boolean; recovered_s: number | null; device: string; selected: number | null
  product: { segments: Segment[] }; calibration: Calibration | null
  product_cursor: string
  confirmation_id: number | null
  calibration_context: CalibrationContext
  calibrated_devices: string[]
  draft_error?: string
  spectrum_settings?: Record<string, number>
  unsaved: {
    measurements: {index: number; device: string; end_s: number}[]
    calibrations: string[]; analysis: boolean; settings: boolean; active_exposure: object | null
  }
  analysis: { roi: [number, number]; reference: number | null; background: number | null; energy_axis: boolean; rate_axis: boolean }
  readout: {centroid?: number | null; energy_MeV?: number | null} | null
}
export type Page = 'setup' | 'instrument' | 'records'
export type Act = (name: string, fields?: Record<string, unknown>) => Promise<void>
export type Open = {experiment: string} | {archive: string} | {draft: string}
export interface Series { label: string; counts: number[]; divisor: number }
