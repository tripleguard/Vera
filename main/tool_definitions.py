"""
Описания инструментов в формате OpenAI function calling.

Используется для передачи в параметр `tools` при запросе к llama-server.
Модель сама решает, какой инструмент вызвать, на основе этих описаний.
"""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Поиск информации в интернете. Используй для: актуальных данных, "
                "новостей, событий после 2024 года, дат выхода, расписаний, "
                "вопросов 'кто такой', 'что такое'. "
                "НЕ используй для: личных сообщений (это telegram), приветствий, болтовни."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": (
                "Поиск и чтение содержимого файла (txt, doc, docx, pdf). "
                "Используй для: 'о чём файл X', 'что написано в X', 'прочитай X'. "
                "НЕ используй для: 'открой файл X' (это команда открытия приложения)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Имя файла (с расширением или без)"
                    }
                },
                "required": ["filename"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "code_interpreter",
            "description": (
                "Выполнение Python кода и возврат результата. "
                "Используй для: сложных вычислений, уравнений, генерации паролей, "
                "конвертации единиц, работы с данными."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python код для выполнения"
                    }
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "telegram",
            "description": (
                "Работа с Telegram: отправка/чтение сообщений, авторизация. "
                "Используй ТОЛЬКО при ЯВНЫХ словах: 'напиши', 'отправь', 'телеграм', "
                "'сообщение', 'подключи телеграм', 'код ЦИФРЫ', 'кто писал', "
                "'что написал [Имя]', 'что ответил [Имя]'. "
                "НЕ используй для: приветствий, болтовни, общих вопросов."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "send_message", "send_batch", "check_auth",
                            "start_auth", "enter_code", "enter_password",
                            "read_chat", "check_who_wrote", "logout"
                        ],
                        "description": "Действие: send_message, read_chat, check_who_wrote, start_auth, enter_code, enter_password, logout"
                    },
                    "contact": {
                        "type": "string",
                        "description": "Имя контакта в именительном падеже, без склонения"
                    },
                    "message": {
                        "type": "string",
                        "description": "Текст сообщения для отправки"
                    },
                    "phone": {
                        "type": "string",
                        "description": "Номер телефона для авторизации (формат: +79991234567)"
                    },
                    "code": {
                        "type": "string",
                        "description": "Код подтверждения авторизации"
                    },
                    "password": {
                        "type": "string",
                        "description": "Пароль 2FA"
                    },
                    "recipients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "contact": {"type": "string"},
                                "message": {"type": "string"}
                            }
                        },
                        "description": "Массив получателей для массовой рассылки (action=send_batch)"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_document",
            "description": (
                "Создание документов: txt, md, docx, pptx, xlsx. "
                "Используй для: 'создай файл X', 'напиши заметку', 'сделай презентацию', "
                "'создай таблицу'. "
                "ВАЖНО: При создании текста для `content` (особенно для docx/md) пиши МАКСИМАЛЬНО подробно, "
                "развернуто, используй структуру, заголовки и все доступные знания/контекст. "
                "Документ должен быть полноценным отчетом или статьей, а не парой случайных абзацев."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create_txt", "create_md", "create_docx", "create_pptx", "create_xlsx"],
                        "description": "Тип документа: create_txt, create_md, create_docx, create_pptx, create_xlsx"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Имя файла без расширения"
                    },
                    "content": {
                        "type": "string",
                        "description": "Содержимое документа"
                    },
                    "title": {
                        "type": "string",
                        "description": "Заголовок документа"
                    },
                    "slides": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "content": {"type": "string"}
                            }
                        },
                        "description": "Слайды для презентации (action=create_pptx)"
                    },
                    "data": {
                        "type": "array",
                        "description": "Данные для таблицы (action=create_xlsx)"
                    },
                    "headers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Заголовки столбцов для таблицы"
                    }
                },
                "required": ["action", "filename"]
            }
        }
    },
]

TOOL_DEFINITIONS_BY_NAME = {
    item["function"]["name"]: item
    for item in TOOL_DEFINITIONS
}


def get_tool_definitions(names):
    return [
        TOOL_DEFINITIONS_BY_NAME[name]
        for name in names
        if name in TOOL_DEFINITIONS_BY_NAME
    ]
