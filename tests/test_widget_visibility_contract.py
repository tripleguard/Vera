from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_widget_visibility_is_persisted_and_applied_before_window_creation():
    main_js = (ROOT / "ui" / "main.js").read_text(encoding="utf-8")

    assert "widget-preferences.json" in main_js
    assert "widgetVisible = preferences.widgetVisible !== false" in main_js
    assert "show: widgetVisible" in main_js
    assert main_js.index("loadUiPreferences();") < main_js.index("createWindows();")
    assert main_js.index("registerWidgetIpcHandlers();") < main_js.index("createWindows();")


def test_widget_visibility_uses_one_ipc_contract_for_settings_and_hover_button():
    main_js = (ROOT / "ui" / "main.js").read_text(encoding="utf-8")
    preload_js = (ROOT / "ui" / "preload.js").read_text(encoding="utf-8")
    app_tsx = (ROOT / "ui" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert "ipcMain.handle('get-widget-visibility'" in main_js
    assert "ipcMain.handle('set-widget-visibility'" in main_js
    assert "'get-widget-visibility'" in preload_js
    assert "'set-widget-visibility'" in preload_js
    assert "label=\"Показывать плавающий виджет\"" in app_tsx
    assert "aria-label=\"Скрыть плавающий виджет\"" in app_tsx
    assert app_tsx.count("'set-widget-visibility'") == 2


def test_tray_can_restore_widget_without_creating_electron_notifications():
    main_js = (ROOT / "ui" / "main.js").read_text(encoding="utf-8")
    preload_js = (ROOT / "ui" / "preload.js").read_text(encoding="utf-8")
    app_tsx = (ROOT / "ui" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert "label: 'Показывать плавающий виджет'" in main_js
    assert "type: 'checkbox'" in main_js
    assert "widgetWindow.showInactive();" in main_js
    assert "widgetWindow.hide();" in main_js
    assert "Notification" not in main_js
    assert "show-system-notification" not in main_js
    assert "show-system-notification" not in preload_js
    assert "system_notification" not in app_tsx
    assert "setAppUserModelId" not in main_js
