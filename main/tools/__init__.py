from .read_document import execute_read_document
from .code_interpreter import execute_code_interpreter
from .document_generator import execute_document_generator
from main.feature_flags import (
    TELEGRAM_DISABLED_MESSAGE,
    TELEGRAM_INTEGRATION_ENABLED,
)


if TELEGRAM_INTEGRATION_ENABLED:
    from .telegram import execute_telegram_tool
else:
    def execute_telegram_tool(_args: dict) -> str:
        return TELEGRAM_DISABLED_MESSAGE

TOOLS = {
    "read_document": execute_read_document,
    "code_interpreter": execute_code_interpreter,
    "create_document": execute_document_generator,
}
if TELEGRAM_INTEGRATION_ENABLED:
    TOOLS["telegram"] = execute_telegram_tool

__all__ = ["TOOLS", "execute_read_document", "execute_code_interpreter", "execute_telegram_tool", "execute_document_generator"]
