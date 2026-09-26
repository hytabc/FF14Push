/**
 * 安全区（状态栏 / 手势条 / 刘海）读取与同步。
 *
 * 取值优先级：
 *   1. Capacitor `SystemBars` 注入的 `--safe-area-inset-*`（Android 上唯一可靠的来源 ——
 *      Android WebView < 140 存在 Chromium 已知 bug，`env(safe-area-inset-*)` 取不到真值）；
 *   2. `env(safe-area-inset-*)` 探针（iOS 与桌面浏览器，桌面恒为 0）。
 *
 * 注入是**异步**的（原生在 WindowInsets 回调里 evaluateJavascript 写内联 style），
 * 所以除了 resize / 旋转，还要观察 `<html>` 的 style 变化才能及时重算。
 */

export interface SafeArea {
  top: number
  bottom: number
  left: number
  right: number
}

type InsetProperty =
  | 'safe-area-inset-top'
  | 'safe-area-inset-bottom'
  | 'safe-area-inset-left'
  | 'safe-area-inset-right'

const TOP_CLASS = 'safe-top'
const BOTTOM_CLASS = 'safe-bottom'
const MARGIN = 8

/** 用「尺寸 = env(...)」的隐藏探针量测 env 值（不支持时恒为 0）。 */
function probeEnv(property: InsetProperty): number {
  if (typeof document === 'undefined') return 0
  const vertical = property.endsWith('top') || property.endsWith('bottom')
  const anchor = property.replace('safe-area-inset-', '')
  const probe = document.createElement('div')
  probe.style.cssText = [
    'position:fixed',
    'visibility:hidden',
    'pointer-events:none',
    `${anchor}:0`,
    vertical ? `height:env(${property}, 0px);width:0` : `width:env(${property}, 0px);height:0`,
  ].join(';')
  document.body.appendChild(probe)
  const rect = probe.getBoundingClientRect()
  probe.remove()
  return vertical ? rect.height : rect.width
}

/** 读 `<html>` 上已解析的 `--app-safe-*`（注入变量与 env 兜底合并后的最终结果，单位 px）。 */
function readCssVar(name: string): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name)
  const parsed = Number.parseFloat(raw)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0
}

/** 当前安全区（px）。优先取 CSS 变量，全都取不到时退回 env 探针。 */
export function readSafeArea(): SafeArea {
  if (typeof document === 'undefined') return { top: 0, bottom: 0, left: 0, right: 0 }
  const fromVars: SafeArea = {
    top: readCssVar('--app-safe-top'),
    bottom: readCssVar('--app-safe-bottom'),
    left: readCssVar('--app-safe-left'),
    right: readCssVar('--app-safe-right'),
  }
  if (fromVars.top || fromVars.bottom || fromVars.left || fromVars.right) return fromVars
  return {
    top: probeEnv('safe-area-inset-top'),
    bottom: probeEnv('safe-area-inset-bottom'),
    left: probeEnv('safe-area-inset-left'),
    right: probeEnv('safe-area-inset-right'),
  }
}

/**
 * 把 fixed 定位的浮层收进安全区：给定期望位置与浮层尺寸，返回夹取后的 left / top。
 * 浮层默认贴着触发元素，可能落到刘海或手势条下面（或屏幕外），统一过一遍这个函数。
 */
export function clampToViewport(
  desired: { left: number; top: number },
  size: { width: number; height: number },
  margin = MARGIN,
): { left: number; top: number } {
  const area = readSafeArea()
  const minLeft = area.left + margin
  const minTop = area.top + margin
  const maxLeft = Math.max(minLeft, window.innerWidth - area.right - size.width - margin)
  const maxTop = Math.max(minTop, window.innerHeight - area.bottom - size.height - margin)
  return {
    left: Math.min(Math.max(minLeft, desired.left), maxLeft),
    top: Math.min(Math.max(minTop, desired.top), maxTop),
  }
}

/**
 * 是否处于全面屏（有安全区）状态，并把结果同步到 `<html>` 的 `safe-top` / `safe-bottom`
 * class 上（`style.css` 据此把页头改为实色、页脚多让出手势条）。
 * 桌面端两个值都是 0，不会加任何 class，外观与之前完全一致。
 */
export function syncSafeAreaClasses(): void {
  if (typeof document === 'undefined') return
  const area = readSafeArea()
  const root = document.documentElement
  root.classList.toggle(TOP_CLASS, area.top > 0)
  root.classList.toggle(BOTTOM_CLASS, area.bottom > 0)
}

/**
 * 安装安全区同步：立刻执行一次，并在可能变化时（窗口尺寸 / 旋转 / 原生异步注入）重算。
 * 返回清理函数。
 */
export function installSafeAreaSync(): () => void {
  if (typeof document === 'undefined') return () => {}
  const run = () => syncSafeAreaClasses()
  run()
  window.addEventListener('resize', run)
  window.addEventListener('orientationchange', run)
  // Capacitor 在 WindowInsets 回调里异步写 <html> 的内联 style，用 observer 精准捕获。
  const observer = new MutationObserver(run)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['style'] })
  return () => {
    window.removeEventListener('resize', run)
    window.removeEventListener('orientationchange', run)
    observer.disconnect()
  }
}
