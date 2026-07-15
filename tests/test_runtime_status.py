from main.runtime_status import RuntimeStatus


def test_initial_state_is_starting_and_not_text_ready():
    status = RuntimeStatus().snapshot()

    assert status["ready"] is False
    assert status["mode"] == "starting"
    assert set(status["components"]) == {"llm", "tts", "stt", "audio"}
    assert all(item["status"] == "starting" for item in status["components"].values())


def test_voice_failure_does_not_disable_text_mode_and_keeps_concrete_error():
    runtime = RuntimeStatus()
    runtime.update("llm", "ready")
    runtime.update("tts", "error", "Supertonic model files are missing")
    runtime.update("stt", "ready")
    runtime.update("audio", "ready")
    runtime.set_text_ready()

    status = runtime.snapshot()

    assert status["ready"] is True
    assert status["mode"] == "text_only"
    assert status["llm_ready"] is True
    assert status["tts_ready"] is False
    assert status["components"]["tts"] == {
        "status": "error",
        "error": "Supertonic model files are missing",
    }


def test_all_voice_components_enable_full_mode():
    runtime = RuntimeStatus()
    for component in ("llm", "tts", "stt", "audio"):
        runtime.update(component, "ready")
    runtime.set_text_ready()

    assert runtime.snapshot()["mode"] == "full"


def test_snapshot_cannot_mutate_internal_state():
    runtime = RuntimeStatus()
    snapshot = runtime.snapshot()
    snapshot["components"]["tts"]["status"] = "ready"

    assert runtime.snapshot()["components"]["tts"]["status"] == "starting"
