import type { CapacitorConfig } from '@capacitor/cli'

/**
 * 「艾欧泽亚放置录」Android 客户端外壳配置。
 *
 *   npm run app:icons   # 从 assets/ 生成图标与启动图
 *   npm run app:sync    # 构建前端并同步进 android/
 *   npm run app:apk     # 产出已签名的 release APK
 *
 * 客户端直接加载线上地址（server.url），因此登录态 Cookie、WebSocket、
 * 本地存档与浏览器访问完全一致，服务端更新后无需重新发包。
 * 需要临时指向别的地址（例如局域网调试）时用环境变量覆盖：
 *
 *   EORZEA_APP_URL=http://192.168.1.10:19999 npm run app:sync
 */
const APP_URL = process.env.EORZEA_APP_URL || 'https://coldrain.cn:19999'

const config: CapacitorConfig = {
  appId: 'cn.coldrain.eorzea',
  appName: '艾欧泽亚放置录',
  webDir: 'frontend/dist',
  server: {
    url: APP_URL,
    androidScheme: 'https',
  },
  android: {
    // 站点是纯深色皮肤，与游戏底色一致，避免加载瞬间闪白。
    backgroundColor: '#0b0f18',
  },
  plugins: {
    // 本作只有深色皮肤，状态栏 / 手势条图标固定用浅色（默认识别系统夜间模式，
    // 白天会给出深色图标，压在深色页面上会看不见）。
    SystemBars: {
      style: 'DARK',
    },
  },
}

export default config
