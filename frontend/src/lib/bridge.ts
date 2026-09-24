type Api = Record<string, (...args: unknown[]) => Promise<unknown>>
export const errorMessage = (error: unknown) => error instanceof Error ? error.message : String(error)
declare global { interface Window { pywebview?: { api: Api } } }
export const desktopReady = () => Boolean(window.pywebview?.api)
let ready: Promise<void> | undefined
export function waitForDesktop(): Promise<void> {
 if (desktopReady()) return Promise.resolve()
 if (!ready) ready = new Promise<void>((resolve, reject) => {
   const onReady = () => { cleanup(); resolve() }
   const timeout = window.setTimeout(() => { cleanup(); ready = undefined; reject(new Error('桌面接口尚未连接，请在桌面应用中打开，或重试连接。')) }, 10000)
   const cleanup = () => { clearTimeout(timeout); window.removeEventListener('pywebviewready', onReady) }
   window.addEventListener('pywebviewready', onReady, { once: true })
   if (desktopReady()) onReady()
 })
 return ready
}
export async function call<T>(method: string, ...args: unknown[]): Promise<T> {
 await waitForDesktop()
 const fn = window.pywebview?.api[method]
 if (!fn) throw new Error('当前桌面版本不支持此操作，请重新打开新版应用。')
 const result = await fn(...args) as { ok: boolean; data: T; error?: string }
 if (!result || result.ok !== true) throw new Error(result?.error || '请求失败，请重试')
 return result.data
}
