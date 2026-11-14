export interface Parameter {
  key: string; label: string; unit: string; minimum: number; maximum: number; integer: boolean
  options?: {value: number; label: string}[]
}
export interface Device {
  id: string; label: string; kind: string; channels: number; calibration_parameters: string[]
  input?: string | null
  background_conditions?: Record<string, number>
}
export interface Part {
  id: string; label: string; kind: string; description: string; parameters: string[]; device: string | null
  illustration?: string | null
  output?: string | null
  devices?: string[]
}
export interface Edge { source: string; target: string; kind: string; label: string }
export interface Course {
  short_code?: string | null
  id: string; title: string; question: string; description: string; guide: string[]
  course?: string
  parameters: Parameter[]; devices: Device[]; components: Part[]; connections: Edge[]
  outputs?: {id: string; label: string}[]
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
  device: string; selected: number | null; record_id: string | null; settings: Record<string, number>
}
export interface SavedObservation {
  id: string; device: string; title: string; counts: number[]; exposure_s: number; segments: Segment[]; calibration_id: string | null
}
export interface State {
  records: {id: string; kind: string; title: string; device: string; exposure_s: number | null; group?: {items: string[]; members: string[]}; measurements?: {id: string; device: string; exposure_s: number}[]}[]
  roi_context: {device: string; record_id: string | null; segment_index: number | null; acquisition: number | null} | null
  roi_result: {id: string; device: string; roi: [number, number]; counts: number[]; exposure_s: number; time_s: number; calibration: unknown; readout: NonNullable<State['readout']>} | null
  id: string; experiment: string; definition: Course; settings: Record<string, number>
  time_s: number; remaining_s: number | null; paused: boolean; running: boolean; frozen: boolean; speed: number
  dirty: boolean; readonly: boolean; recovered_s: number | null; device: string; selected: number | null
  product: { segments: Segment[] }; calibration: Calibration | null; reference_calibration: Calibration | null
  product_cursor: string
  window_cursor: string
  selected_item_id: string | null; reference_item_id: string | null
  selected_observation: SavedObservation | null; reference_observation: SavedObservation | null
  saved_measurements: {id: string; device: string; title: string; exposure_s: number; settings: Record<string, number>[]; calibration_id: string | null}[]
  measurement_end_s: number
  confirmation_id: number | null
  active_acquisition: number | null
  any_running: boolean; clock_running: boolean; exposure_s: number | null
  output_enabled: Record<string, boolean>
  gates: Record<string, boolean>
  instrument_groups: Record<string, {can_start: boolean; can_stop: boolean}>
  snapshots: {id: number; item_id?: string; calibration_id?: string | null; device: string; acquisition: number; time_s: number; exposure_s: number; counts: number; settings: Record<string, number>[]; background_eligible: boolean}[]
  imported_items: {id: string; device: string; title: string; acquisition: number; exposure_s: number; source: {package: string; item: string}}[]
  clear_confirmation: {device?: string; token: number | string; exposure_s?: number; component?: string; devices?: string[]; exposures?: Record<string, number>} | null
  readout_error: string | null
  portable_loaded: boolean
  portable_mode_notice: string
  portable_unresolved: Record<string, Record<string, unknown>>
  cached_calibrations: {id: string; device: string; title: string}[]
  counter_analysis: {index: number; net_rate?: number; uncertainty?: number; background_reference?: boolean; error?: string}[]
  instrument: {device: string; acquisition: number | null; cycle: number | null;
    counts: number[]; readable_exposure_s: number; stop_reason: string | null; clearing: boolean;
    duration_s: number | null; count_limit: number | null; window_s: number; next_window_s?: number | null} | null
  instruments: Record<string, NonNullable<State['instrument']> & {running: boolean; exposure_s: number; remaining_s: number | null}>
  counter_windows: Record<string, {number: number; start_exposure_s: number; end_exposure_s: number; counts: number[]; complete: boolean; parts: {start_s: number; end_s: number; settings: Record<string, number>}[]}[]>
  particle_flow: {thickness_um?: number; areal_density_g_cm2?: number} | null
  calibration_context: CalibrationContext
  calibrated_devices: string[]
  draft_error?: string
  spectrum_settings?: Record<string, number>
  unsaved: {
    measurements: {index: number; device: string; end_s: number}[]
    calibrations: string[]; analysis: boolean; settings: boolean; active_exposure: object | null
    cached_items?: number
  }
  analysis: { roi: [number, number]; reference: number | null; background: number | null; energy_axis: boolean; rate_axis: boolean }
  readout: {counts: number; exposure_s: number; roi_counts?: number; centroid?: number | null; energy_MeV?: number | null} | null
}
export type Page = 'setup' | 'instrument' | 'records' | 'materials'
export type Act = (name: string, fields?: Record<string, unknown>, session?: string) => Promise<void>
export type Open = {experiment: string} | {archive: string} | {draft: string}
export interface Series { label: string; counts: number[]; divisor: number; channelPosition?: (channel: number) => number }
