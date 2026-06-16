import unittest
from unittest.mock import patch

from web import weather


class WeatherTests(unittest.TestCase):
    def tearDown(self):
        weather.set_default_city_provider(None)

    def test_comfortable_temperature_has_advice(self):
        with patch("random.choice", side_effect=lambda values: values[0]):
            advice = weather._get_weather_advice(18, None, "облачно")

        self.assertIn("комфортно", advice)

    def test_temperature_and_rain_advice_are_both_returned(self):
        with patch("random.choice", side_effect=lambda values: values[0]):
            advice = weather._get_weather_advice(8, None, "небольшой дождь")

        self.assertIn("потеплее", advice)
        self.assertIn("зонт", advice)

    @patch("web.weather.fetch_url")
    @patch("web.weather.search_brave")
    def test_uses_city_from_memory_when_request_has_no_city(
        self,
        search_brave,
        fetch_url,
    ):
        weather.set_default_city_provider(lambda: "Нальчик")
        search_brave.return_value = ["https://example.test/weather"]
        fetch_url.return_value = ("title", "Сейчас 18° и облачно с прояснениями")

        with patch("random.choice", side_effect=lambda values: values[0]):
            response = weather.execute_weather_command("погода")

        search_brave.assert_called_once_with("погода Нальчик", max_results=5)
        self.assertIn("Погода в Нальчик:", response)
        self.assertIn("комфортно", response)

    def test_asks_for_city_when_memory_is_empty(self):
        weather.set_default_city_provider(lambda: None)

        response = weather.execute_weather_command("погода")

        self.assertIn("запомни мой город Москва", response)


if __name__ == "__main__":
    unittest.main()
