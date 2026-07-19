import unittest
from unittest.mock import patch

from main.commands import app_control


class AppControlTests(unittest.TestCase):
    def test_app_index_is_loaded_lazily_and_cached(self):
        indexed_app = {
            "display_name": "Calculator",
            "exe_name": "calc.exe",
            "lnk_path": "",
        }

        with (
            patch.object(app_control, "APP_INDEX", None),
            patch.object(app_control, "load_app_index", return_value=[indexed_app]) as load,
        ):
            self.assertEqual(app_control._best_app_match("calculator"), indexed_app)
            self.assertEqual(app_control._best_app_match("calculator"), indexed_app)

        load.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
