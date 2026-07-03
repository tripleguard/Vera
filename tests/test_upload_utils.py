import unittest

from main.upload_utils import safe_upload_name


class UploadUtilsTests(unittest.TestCase):
    def test_safe_upload_name_strips_path_segments(self):
        name = safe_upload_name(r"..\..\secret report.PDF")
        self.assertTrue(name.endswith(".pdf"))
        self.assertNotIn("..", name)
        self.assertNotIn("\\", name)
        self.assertNotIn("/", name)

    def test_safe_upload_name_is_unique_and_has_fallback(self):
        first = safe_upload_name("")
        second = safe_upload_name("")
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("upload_"))


if __name__ == "__main__":
    unittest.main()
