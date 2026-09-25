/**
 * 应用版本号与更新日志。
 *
 * 单一事实来源是仓库根目录的 `CHANGELOG.md`：顶部第一条版本即当前版本。
 * 顶栏版本号（`App.vue`）与更新公告弹窗（`components/VersionAnnouncementModal.vue`）
 * 都从这里读取，因此发版只需改根目录更新日志（并同步工程版本号文件）。
 */
import { parseChangelog } from '@/utils/changelog'

import changelogRaw from '../../CHANGELOG.md?raw'

/** 所有版本的更新内容，最新在前。 */
export const CHANGELOG = parseChangelog(changelogRaw)

/** 当前版本号（形如 `1.0.1`，不含前缀 V）。 */
export const APP_VERSION = CHANGELOG[0]?.version ?? '0.0.0'

/** 最新一个版本的更新内容。 */
export const LATEST_CHANGELOG = CHANGELOG[0]
