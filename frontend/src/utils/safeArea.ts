/**
 * 全面屏（edge-to-edge）探测。
 *
 * Android 客户端（Capacitor，targetSdk 36 强制 edge-to-edge）下状态栏 / 手势条会压在页面上，
 * `env(safe-area-inset-*)` 不为 0；桌面浏览器与普通窗口该值恒为 0。
 *
 * 这里只在**存在安全区**时给 `<html>` 加上 `safe-top` / `safe-bottom` class，交由 `style.css`
 * 做设备级适配，因此桌面端外观完全不变（避免为移动端问题改动桌面视觉）。
 */

const TOP_CLASS = 'safe-top'
const BOTTOM_CLASS = 'safe-bottom'

/** 量测 `env(safe-area-inset-*)` 的实际像素值（用高度等于该值的隐藏探针）。 */
function probeInset(property: 'safe-area-inset-top' | 'safe-area-inset-bottom'): number {
  if (typeof document === 'undefined') return 0
  const probe = document.createElement('div')
  probe.style.cssText =
    `position:fixed;left:0;width:0;visibility:hidden;pointer-events:none;` +
    `height:env(${property}, 0px);${property === 'safe-area-inset-top' ? 'top:0' : 'bottom:0'}`
  document.body.appendChild(probe)
  const value = probe.getBoundingClientRect().height
  probe.remove()
  return value
}

/** 探测并同步 `<html>` 上的全面屏 class（旋转 / 尺寸变化后应重新调用）。 */
export function syncSafeAreaClasses(): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.toggle(TOP_CLASS, probeInset('safe-area-inset-top') > 0)
  root.classList.toggle(BOTTOM_CLASS, probeInset('safe-area-inset-bottom') > 0)
}
