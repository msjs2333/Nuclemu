import {onBeforeUnmount, onMounted, ref, shallowRef} from 'vue'
import {api, ApiError, errorMessage} from './api'
import type {Act, Catalog, Open, Page, State, Segment} from './types'

type Snapshot = Omit<State, 'product'> & (
  {product: State['product']; product_delta?: never} |
  {product?: never; product_delta: {start: number; segments: Segment[]}}
)

function stable<T>(previous: T, next: T): T {
  return JSON.stringify(previous) === JSON.stringify(next) ? previous : next
}
function pageName(hash: string): Page {
  return hash === 'instrument' || hash === 'records' ? hash : 'setup'
}
export function useSession() {
  const state = shallowRef<State | null>(null)
  const catalog = shallowRef<Catalog>()
  const page = ref<Page>('setup'), confirming = ref(false), error = ref(''), message = ref('')
  const recovered = ref<number | null>(null)
  let tail: Promise<unknown> = Promise.resolve(), pending = 0, revision = 0, polling = false
  let interval: number

  function accept(next: Snapshot) {
    const prev = state.value?.id === next.id ? state.value : null
    let product = next.product
    if (!product) {
      if (!prev || !next.product_delta) throw Error('测量记录已变更，请刷新实验。')
      const {start, segments} = next.product_delta
      product = segments.length || start !== prev.product.segments.length
        ? {...prev.product, segments: prev.product.segments.slice(0, start).concat(segments)} : prev.product
    }
    if (prev) {
      next.definition = prev.definition
      next.settings = stable(prev.settings, next.settings)
      next.analysis = stable(prev.analysis, next.analysis)
      next.calibration = stable(prev.calibration, next.calibration)
      next.calibrated_devices = stable(prev.calibrated_devices, next.calibrated_devices)
      next.readout = stable(prev.readout, next.readout)
    }
    state.value = {...next, product}
    confirming.value = next.frozen
  }
  function serial<T>(fn: () => Promise<T>) {
    pending++
    revision++
    const job = tail.then(fn).finally(() => pending--)
    tail = job.catch(() => {})
    return job
  }
  async function report(fn: () => Promise<unknown>) {
    error.value = ''
    try { await fn() } catch (e) { error.value = errorMessage(e) }
  }
  async function action(name: string, fields: Record<string, unknown> = {}) {
    const s = state.value
    if (!s) throw Error('实验已结束。')
    const next = await api<Snapshot | null>('action', {session: s.id, product_cursor: s.product_cursor, action: name, ...fields})
    if (next) accept(next)
  }
  const act: Act = (name, fields) => serial(() => action(name, fields))
  function labUrl() { return '/lab/' + encodeURIComponent(state.value!.experiment) + '/#' + page.value }
  function setPage(tab: Page) {
    page.value = tab
    history.replaceState({id: state.value!.id, page: tab}, '', labUrl())
  }
  function enter(next: Snapshot, tab: Page) {
    accept(next)
    page.value = tab
    recovered.value = next.recovered_s
    error.value = message.value = ''
    document.title = next.definition.title + ' · Nuclemu'
  }
  async function loadCatalog() { catalog.value = await api<Catalog>('catalog') }
  function open(args: Open) {
    return serial(async () => {
      if (state.value) return
      const next = await api<Snapshot>('open', args)
      enter(next, 'archive' in args || 'draft' in args ? 'instrument' : 'setup')
      history.pushState({id: next.id, page: page.value}, '', labUrl())
    })
  }
  function askExit() {
    return serial(async () => {
      if (!state.value || confirming.value) return
      await action('freeze')
      confirming.value = true
    })
  }
  function cancelExit() {
    return serial(async () => { await action('continue'); confirming.value = false })
  }
  function finish(save: boolean) {
    return serial(async () => {
      if (!state.value || !confirming.value) return
      await action(save ? 'save' : 'discard', save ? {exit: true} : {})
      state.value = null
      confirming.value = false
      document.title = 'Nuclemu · 核物理实验台'
      history.replaceState(null, '', '/')
      await loadCatalog()
    })
  }
  async function boot() {
    const [menu, s] = await Promise.all([api<Catalog>('catalog'), api<Snapshot | null>('state')])
    if (s) {
      const tab = pageName(location.hash.slice(1))
      if (history.state?.id !== s.id) history.replaceState(null, '', '/')
      enter(s, tab)
      if (history.state?.id === s.id) setPage(tab)
      else history.pushState({id: s.id, page: tab}, '', labUrl())
    } else if (location.pathname !== '/') history.replaceState(null, '', '/')
    catalog.value = menu
  }
  function navigate() {
    if (!state.value) {
      if (location.pathname !== '/') history.replaceState(null, '', '/')
    } else if (location.pathname === '/lab/' + encodeURIComponent(state.value.experiment) + '/') {
      setPage(pageName(location.hash.slice(1)))
    } else {
      history.pushState({id: state.value.id, page: page.value}, '', labUrl())
      void report(askExit)
    }
  }
  function suspend() {
    if (state.value && !state.value.readonly) navigator.sendBeacon('/api/action',
      new Blob([JSON.stringify({action: 'suspend', session: state.value.id})], {type: 'application/json'}))
  }
  function resume(e: PageTransitionEvent) {
    if (e.persisted) void poll()
  }
  async function poll() {
    const current = state.value
    if (!current || pending || polling || document.hidden) return
    const tag = revision
    polling = true
    try {
      const query = new URLSearchParams({session: current.id, product_cursor: current.product_cursor})
      const result = await api<Snapshot>('state?' + query)
      if (revision === tag && state.value?.id === current.id) accept(result)
    } catch (e) {
      if (revision === tag) {
        error.value = errorMessage(e)
        if (e instanceof ApiError && e.status === 400) {
          // Another tab may have closed this session. Return to the catalogue
          // without applying its queued commands to a different session.
          const server = await api<{id: string} | null>('state').catch(() => undefined)
          if (server !== undefined && server?.id !== current.id && revision === tag) {
            state.value = null
            confirming.value = false
            document.title = 'Nuclemu · 核物理实验台'
            history.replaceState(null, '', '/')
            await report(loadCatalog)
            error.value = '此实验已在其他页面退出。'
          }
        }
      }
    } finally { polling = false }
  }
  onMounted(() => {
    void report(() => serial(boot))
    window.addEventListener('popstate', navigate)
    window.addEventListener('pageshow', resume)
    window.addEventListener('pagehide', suspend)
    interval = window.setInterval(poll, 450)
  })
  onBeforeUnmount(() => {
    window.clearInterval(interval)
    window.removeEventListener('pagehide', suspend)
    window.removeEventListener('pageshow', resume)
    window.removeEventListener('popstate', navigate)
  })
  return {state, catalog, page, confirming, recovered, message, error, act, report, open, askExit, cancelExit, finish, setPage}
}
