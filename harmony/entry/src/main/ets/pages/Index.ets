import { hilog } from '@kit.PerformanceAnalysisKit';
import { webview } from '@kit.ArkWeb';

const DOMAIN = 0x0000;
const TAG = 'Eorzea';

/**
 * 线上站点地址：与 Android / iOS 外壳同源（见 capacitor.config.ts 的 server.url）。
 * 服务端发版后无需重出 HAP，重新打开即是最新内容。
 */
const APP_URL = 'https://coldrain.cn:19999';

/**
 * 唯一页面：整屏 ArkWeb 组件加载线上站点。
 *
 * 这里刻意**不**调用 expandSafeArea —— 按系统默认布局，内容自动让开顶部状态栏与底部
 * 手势条（小横条），即「全面屏避让」；网页内部另有一套安全区适配（style.css 的
 * --app-safe-*），两侧叠加后不会出现内容被系统栏遮住的情况。
 */
@Entry
@Component
struct Index {
  private controller: webview.WebviewController = new webview.WebviewController();

  build() {
    Column() {
      Web({ src: APP_URL, controller: this.controller })
        .javaScriptAccess(true)
        .domStorageAccess(true)
        .databaseAccess(true)
        .zoomAccess(false)
        .width('100%')
        .height('100%')
    }
    .width('100%')
    .height('100%')
    // 与游戏底色一致，避免加载瞬间闪白。
    .backgroundColor('#0b0f18')
  }

  /** 返回键优先在网页历史里后退；退无可退时交回系统（退出应用）。 */
  onBackPress(): boolean {
    try {
      if (this.controller.accessBackward()) {
        this.controller.backward();
        return true;
      }
    } catch (err) {
      // 控制器未就绪等异常不应阻断返回键，交给系统处理。
      hilog.warn(DOMAIN, TAG, 'backward failed: %{public}s', JSON.stringify(err));
    }
    return false;
  }
}
