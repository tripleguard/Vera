import unittest

from main.audio_devices import (
    AudioDeviceError,
    choose_input_samplerate,
    choose_output_parameters,
    list_audio_devices,
    preferred_audio_devices,
    resolve_audio_device,
)


class _Defaults:
    device = [1, 2]


class _FakeWasapiSettings:
    def __init__(self, exclusive=False, auto_convert=False):
        self.exclusive = exclusive
        self.auto_convert = auto_convert


class FakeSoundDevice:
    WasapiSettings = _FakeWasapiSettings

    def __init__(self, devices=None):
        self.default = _Defaults()
        self.devices = devices or [
            {
                "name": "Jabra Hands-Free",
                "hostapi": 0,
                "max_input_channels": 1,
                "max_output_channels": 0,
                "default_samplerate": 16000,
            },
            {
                "name": "USB Microphone",
                "hostapi": 1,
                "max_input_channels": 1,
                "max_output_channels": 0,
                "default_samplerate": 48000,
            },
            {
                "name": "Jabra Hands-Free",
                "hostapi": 0,
                "max_input_channels": 0,
                "max_output_channels": 1,
                "default_samplerate": 16000,
            },
            {
                "name": "Jabra Stereo",
                "hostapi": 1,
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": 48000,
            },
        ]
        self.input_rates = {16000, 48000}
        self.output_rates = {16000, 48000}

    def query_devices(self):
        return self.devices

    def query_hostapis(self):
        return [{"name": "Windows WASAPI"}, {"name": "MME"}]

    def check_input_settings(self, **kwargs):
        if kwargs["samplerate"] not in self.input_rates:
            raise RuntimeError("unsupported input rate")

    def check_output_settings(self, **kwargs):
        if kwargs["samplerate"] not in self.output_rates:
            raise RuntimeError("unsupported output rate")


class AudioDeviceTests(unittest.TestCase):
    def test_lists_directions_defaults_and_host_apis(self):
        payload = list_audio_devices(FakeSoundDevice())

        self.assertEqual(len(payload["inputs"]), 2)
        self.assertEqual(len(payload["outputs"]), 2)
        self.assertEqual(payload["inputs"][0]["name"], "USB Microphone")
        self.assertTrue(payload["inputs"][0]["is_default"])
        self.assertEqual(payload["outputs"][0]["host_api"], "Windows WASAPI")
        self.assertTrue(payload["outputs"][0]["is_default"])

    def test_saved_selector_survives_runtime_index_changes(self):
        fake = FakeSoundDevice()
        fake.devices[0], fake.devices[1] = fake.devices[1], fake.devices[0]
        fake.default.device = [0, 2]

        selected = resolve_audio_device(
            "input",
            {"name": "Jabra Hands-Free", "host_api": "Windows WASAPI"},
            fake,
        )

        self.assertEqual(selected["index"], 1)
        self.assertIsNone(selected["fallback_reason"])

    def test_missing_saved_device_falls_back_with_concrete_reason(self):
        fake = FakeSoundDevice()
        device_lists = list_audio_devices(fake)
        fake.devices = []
        selected = resolve_audio_device(
            "input",
            {"name": "Disconnected Headset", "host_api": "Windows WASAPI"},
            fake,
            available_devices=device_lists,
        )

        self.assertEqual(selected["name"], "USB Microphone")
        self.assertIn("Disconnected Headset", selected["fallback_reason"])

    def test_no_input_device_raises_clear_error(self):
        fake = FakeSoundDevice(devices=[{
            "name": "Speakers",
            "hostapi": 0,
            "max_input_channels": 0,
            "max_output_channels": 2,
            "default_samplerate": 48000,
        }])

        with self.assertRaisesRegex(AudioDeviceError, "устройства ввода"):
            resolve_audio_device("input", None, fake)

    def test_input_rate_falls_back_to_device_native_rate(self):
        fake = FakeSoundDevice()
        fake.input_rates = {48000}
        device = {"index": 1, "name": "USB Microphone", "default_samplerate": 48000}

        self.assertEqual(choose_input_samplerate(device, 16000, fake), 48000)

    def test_wasapi_output_uses_shared_auto_conversion(self):
        fake = FakeSoundDevice()
        device = {
            "index": 2,
            "name": "Jabra Hands-Free",
            "host_api": "Windows WASAPI",
            "default_samplerate": 16000,
        }

        result = choose_output_parameters(device, 48000, fake)

        self.assertEqual(result["samplerate"], 48000)
        self.assertFalse(result["extra_settings"].exclusive)
        self.assertTrue(result["extra_settings"].auto_convert)

    def test_non_wasapi_output_falls_back_to_native_rate(self):
        fake = FakeSoundDevice()
        fake.output_rates = {48000}
        device = {
            "index": 3,
            "name": "Jabra Stereo",
            "host_api": "MME",
            "default_samplerate": 48000,
        }

        result = choose_output_parameters(device, 24000, fake)

        self.assertEqual(result["samplerate"], 48000)
        self.assertIsNone(result["extra_settings"])

    def test_windows_lists_only_wasapi_when_available(self):
        payload = list_audio_devices(FakeSoundDevice())

        preferred = preferred_audio_devices(payload)

        self.assertEqual(
            [(device["name"], device["host_api"]) for device in preferred["inputs"]],
            [("Jabra Hands-Free", "Windows WASAPI")],
        )
        self.assertEqual(
            [(device["name"], device["host_api"]) for device in preferred["outputs"]],
            [("Jabra Hands-Free", "Windows WASAPI")],
        )

    def test_non_windows_device_lists_are_not_filtered(self):
        payload = {
            "inputs": [{"name": "Built-in", "host_api": "Core Audio"}],
            "outputs": [{"name": "Built-in", "host_api": "Core Audio"}],
        }

        self.assertEqual(preferred_audio_devices(payload), payload)


if __name__ == "__main__":
    unittest.main()
