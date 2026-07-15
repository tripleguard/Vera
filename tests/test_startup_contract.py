from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ipc_token_handler_is_registered_before_windows_are_created():
    main_js = (ROOT / "ui" / "main.js").read_text(encoding="utf-8")

    handler = main_js.index("ipcMain.on('get-api-token-sync'")
    when_ready = main_js.index("app.whenReady().then")
    create_call = main_js.index("createWindows();", when_ready)

    assert handler < create_call


def test_packaged_backend_disables_implicit_tts_downloads():
    main_js = (ROOT / "ui" / "main.js").read_text(encoding="utf-8")

    assert "VERA_TTS_AUTO_DOWNLOAD: app.isPackaged ? '0' : '1'" in main_js
    assert "SUPERTONIC_CACHE_DIR" in main_js
    assert "models', 'supertonic3'" in main_js


def test_supertonic_is_a_separate_installer_component():
    installer = (ROOT / "vera.iss").read_text(encoding="utf-8")
    build_script = (ROOT / "build.bat").read_text(encoding="utf-8")

    assert 'Name: "tts"' in installer
    assert 'Source: "build\\supertonic3\\*"' in installer
    assert "Components: tts" in installer
    assert "SUPERTONIC_STAGING" in build_script
    assert "%USERPROFILE%\\.cache\\supertonic3" in build_script


def test_text_readiness_is_not_guarded_by_tts_or_microphone():
    agent = (ROOT / "main" / "agent.py").read_text(encoding="utf-8")
    run_loop = agent[agent.index("def run_main_loop():"):]

    text_ready = run_loop.index("_runtime_status.set_text_ready()")
    microphone = run_loop.index("sd.RawInputStream")

    assert text_ready < microphone
    assert "_tts_ready_event.wait" not in run_loop


def test_audio_device_settings_are_wired_end_to_end():
    agent = (ROOT / "main" / "agent.py").read_text(encoding="utf-8")
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    ui = (ROOT / "ui" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert 'cfg.get("audio", {}).get("input_device")' in agent
    assert 'cfg.get("audio", {}).get("output_device")' in agent
    assert 'device=input_device["index"]' in agent
    assert 'device=output_device["index"]' in agent
    assert '@app.get("/api/audio/devices")' in server
    assert '@app.post("/api/audio/device")' in server
    assert '@app.post("/api/audio/test-input")' in server
    assert '@app.post("/api/audio/test-output")' in server
    assert "Системный микрофон" in ui
    assert "Системный выход" in ui
    assert "Проверить микрофон" in ui
    assert "Проверить звук" in ui
    assert "Устройство переключается сразу" in ui
    assert "request_audio_input_switch" in agent
    assert "reconfigure_audio_output" in agent


def test_voice_only_response_mode_is_the_ui_and_config_default():
    config = (ROOT / "data" / "config.json").read_text(encoding="utf-8")
    ui = (ROOT / "ui" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert '"speak_responses": "voice_only"' in config
    assert "value={config.tts?.speak_responses || 'voice_only'}" in ui
    assert "{ value: 'voice_only', label: 'Только на голосовые запросы'" in ui
    assert "cfgData?.tts?.speak_responses || 'voice_only'" in ui


def test_audio_switching_is_live_and_does_not_restart_the_agent():
    agent = (ROOT / "main" / "agent.py").read_text(encoding="utf-8")
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    ui = (ROOT / "ui" / "src" / "App.tsx").read_text(encoding="utf-8")

    voice_loop = agent[agent.index("def _run_voice_input_loop"):agent.index("def run_main_loop")]
    assert "_audio_input_restart_event.is_set()" in voice_loop
    assert "q.get(timeout=0.2)" in voice_loop
    assert "await asyncio.to_thread(wait_audio_input_switch" in server
    assert 'config.set("audio", "input_device", value=previous_selector)' in server
    assert "applyAudioDevice('input', selector)" in ui
    assert "applyAudioDevice('output', selector)" in ui
    assert "restart-app" not in ui[ui.index("const applyAudioDevice"):ui.index("const runAudioTest")]
