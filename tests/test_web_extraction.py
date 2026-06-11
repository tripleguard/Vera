import unittest
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


if __name__ == "__main__":
    unittest.main()
