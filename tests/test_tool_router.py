import unittest

from main.tool_router import route_intent, select_tool_names


class ToolRouterTests(unittest.TestCase):
    def test_small_talk_gets_no_tools(self):
        self.assertEqual(select_tool_names("Привет, как дела?"), [])

    def test_current_information_gets_web_search(self):
        self.assertEqual(
            select_tool_names("Найди последние новости о локальных моделях"),
            ["web_search"],
        )

    def test_definition_question_can_use_web_search(self):
        self.assertEqual(
            select_tool_names("Что такое WebGPU?"),
            ["web_search"],
        )

    def test_report_research_gets_document_and_search_only(self):
        self.assertEqual(
            select_tool_names("Найди актуальные данные и создай отчет в docx"),
            ["create_document", "web_search"],
        )

    def test_writing_text_is_not_telegram(self):
        self.assertEqual(select_tool_names("Напиши текст о космосе"), [])

    def test_explicit_recipient_can_use_telegram(self):
        self.assertEqual(
            select_tool_names("Напиши Маше что я скоро буду"),
            ["telegram"],
        )

    def test_telegram_history_does_not_trigger_web_search(self):
        self.assertEqual(
            select_tool_names("Найди что написал Андрей"),
            ["telegram"],
        )

    def test_research_report_prioritizes_search_with_two_tool_limit(self):
        self.assertEqual(
            select_tool_names(
                "Найди актуальные данные, рассчитай показатели и создай отчет"
            ),
            ["create_document", "web_search"],
        )

    def test_attached_file_does_not_trigger_read_document(self):
        self.assertEqual(
            select_tool_names(
                "Проанализируй прикрепленный документ",
                file_name="report.pdf",
            ),
            [],
        )

    def test_system_commands_do_not_select_llm_tools(self):
        cases = [
            "Вера, открой хром",
            "Вера, громкость 50",
            "Вера, сделай скриншот",
            "Вера, таймер стоп",
        ]
        for text in cases:
            with self.subTest(text=text):
                route = route_intent(text)
                self.assertEqual(route.skill, None)
                self.assertEqual(route.tools, ())
                self.assertFalse(route.direct_web)

    def test_requested_presentation_phrase_routes_to_skill(self):
        route = route_intent("Вера, сделай презентацию про ядро ОС")
        self.assertEqual(route.skill, "presentations")
        self.assertEqual(route.tools, ())

    def test_requested_document_phrase_routes_to_document_skill(self):
        route = route_intent("Вера, напиши реферат и сохрани в docx")
        self.assertEqual(route.skill, "documents")
        self.assertEqual(route.tools, ("create_document",))

    def test_requested_current_person_phrase_uses_web_search(self):
        self.assertEqual(
            select_tool_names("Кто такой Илон Маск сейчас"),
            ["web_search"],
        )

    def test_read_file_with_attached_context_does_not_repeat_read_document(self):
        self.assertEqual(
            select_tool_names("Прочитай файл", file_name="report.docx"),
            [],
        )

    def test_existing_named_document_can_be_read(self):
        self.assertEqual(
            select_tool_names("Прочитай документ report.pdf"),
            ["read_document"],
        )

    def test_math_uses_code_interpreter(self):
        self.assertEqual(
            select_tool_names("Посчитай сколько будет 1543 умножить на 91"),
            ["code_interpreter"],
        )

    def test_selection_respects_available_names_and_limit(self):
        selected = select_tool_names(
            "Найди данные и создай отчет",
            available_names={"web_search"},
            max_tools=1,
        )
        self.assertEqual(selected, ["web_search"])

    def test_routes_presentation_to_skill(self):
        route = route_intent("Создай презентацию про локальные модели")
        self.assertEqual(route.skill, "presentations")

    def test_routes_report_to_document_skill_and_keeps_research_tools(self):
        route = route_intent("Найди актуальные данные и создай отчет в docx")
        self.assertEqual(route.skill, "documents")
        self.assertEqual(route.tools, ("create_document", "web_search"))

    def test_plain_code_is_not_an_execution_request(self):
        route = route_intent("Напиши код на Python для сортировки списка")
        self.assertTrue(route.plain_code)
        self.assertEqual(route.tools, ())

    def test_explicit_code_execution_uses_interpreter(self):
        route = route_intent("Выполни Python код print(2 + 2)")
        self.assertFalse(route.plain_code)
        self.assertEqual(route.tools, ("code_interpreter",))

    def test_telegram_auth_arguments_are_parsed_once(self):
        phone_route = route_intent("Подключи телеграм по номеру +7 999 123-45-67")
        self.assertEqual(
            phone_route.telegram_action,
            {"action": "start_auth", "phone": "+7 999 123-45-67"},
        )
        code_route = route_intent("код для телеграма: 12345")
        self.assertEqual(
            code_route.telegram_action,
            {"action": "enter_code", "code": "12345"},
        )

    def test_web_only_route_can_use_direct_search(self):
        route = route_intent("Что такое WebGPU?")
        self.assertTrue(route.direct_web)


if __name__ == "__main__":
    unittest.main()
