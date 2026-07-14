import unittest
import threading
import time
from unittest.mock import patch

from web import web_utils


SAMPLE_HTML = """
<!doctype html>
<html>
  <head>
    <title>Vera release</title>
    <script>window.tracking = true;</script>
  </head>
  <body>
    <nav>Home Pricing Sign in</nav>
    <main>
      <article>
        <h1>Vera Desktop update</h1>
        <p>Vera now keeps every conversation in an isolated session.</p>
        <p>The assistant preserves only the five latest messages as model context.</p>
        <h2>Why it matters</h2>
        <p>This lowers prompt size while keeping recent requests understandable.</p>
        <p>Read the <a href="https://example.com/docs">technical notes</a> for implementation details.</p>
      </article>
    </main>
    <footer>Cookies Privacy Contact</footer>
  </body>
</html>
"""


class WebExtractionTests(unittest.TestCase):
    def test_trafilatura_returns_main_content_as_markdown(self):
        extracted = web_utils.extract_visible_text(SAMPLE_HTML)

        self.assertIn("Vera Desktop update", extracted)
        self.assertIn("five latest messages", extracted)
        self.assertIn("Why it matters", extracted)
        self.assertNotIn("window.tracking", extracted)
        self.assertNotIn("Cookies Privacy Contact", extracted)

    def test_fallback_excludes_navigation_and_scripts(self):
        with patch.object(web_utils, "trafilatura", None):
            extracted = web_utils.extract_visible_text(SAMPLE_HTML)

        self.assertIn("Vera now keeps every conversation", extracted)
        self.assertIn("technical notes", extracted)
        self.assertNotIn("Home Pricing Sign in", extracted)
        self.assertNotIn("window.tracking", extracted)

    def test_parallel_fetch_handles_empty_input(self):
        self.assertEqual(web_utils.fetch_urls_parallel([]), [])

    def test_parallel_fetch_forwards_logging_and_returns_without_waiting_for_slow_page(self):
        release_slow_page = threading.Event()

        def fake_fetch(url, timeout=5.0, max_bytes=70000, per_page_limit=1500, log_errors=False):
            self.assertTrue(log_errors)
            if url.endswith("slow"):
                release_slow_page.wait(timeout=1.0)
            return url, f"content from {url}"

        started = time.monotonic()
        try:
            with patch.object(web_utils, "_fetch_page", side_effect=fake_fetch):
                result = web_utils.fetch_urls_parallel(
                    ["https://example.com/slow", "https://example.com/fast"],
                    max_sources=1,
                    log_page_errors=True,
                )
            elapsed = time.monotonic() - started
        finally:
            release_slow_page.set()

        self.assertEqual(len(result), 1)
        self.assertLess(elapsed, 0.5)


if __name__ == "__main__":
    unittest.main()
