import unittest

from main.tool_definitions import get_tool_definitions


class ToolDefinitionTests(unittest.TestCase):
    def test_returns_requested_definitions_in_order(self):
        definitions = get_tool_definitions(["code_interpreter", "web_search"])
        self.assertEqual(
            [item["function"]["name"] for item in definitions],
            ["code_interpreter", "web_search"],
        )

    def test_unknown_names_are_ignored(self):
        self.assertEqual(get_tool_definitions(["missing"]), [])


if __name__ == "__main__":
    unittest.main()
