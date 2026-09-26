package cn.coldrain.eorzea;

import android.graphics.Color;
import android.os.Bundle;

import androidx.activity.EdgeToEdge;
import androidx.activity.SystemBarStyle;

import com.getcapacitor.BridgeActivity;

/**
 * Capacitor 8 的外壳入口。
 *
 * `EdgeToEdge.enable(...)` 用于对齐「全面屏（edge-to-edge）」表现：Android 15+（targetSdk 36）
 * 系统已强制 edge-to-edge，但 Android 14 及以下默认仍是「系统栏占位」的旧布局；显式开启后
 * 各版本表现一致 —— 内容铺满整屏，由页面按安全区自行避让状态栏与手势条。
 *
 * Capacitor 9 才会默认替应用调用它（见 @capacitor/core 的 system-bars 文档），故这里手动调用。
 * `SystemBarStyle.dark(...)` 表示「深色底 + 浅色图标」，与纯深色皮肤
 * （capacitor.config.ts 的 SystemBars.style = 'DARK'）保持一致。
 */
public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        EdgeToEdge.enable(
            this,
            SystemBarStyle.dark(Color.TRANSPARENT),
            SystemBarStyle.dark(Color.TRANSPARENT)
        );
        super.onCreate(savedInstanceState);
    }
}
