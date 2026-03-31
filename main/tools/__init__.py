from .read_document import execute_read_document
from .code_interpreter import execute_code_interpreter
from .telegram import execute_telegram_tool
from .document_generator import execute_document_generator

TOOLS = {
    "read_document": execute_read_document,
    "code_interpreter": execute_code_interpreter,
    "telegram": execute_telegram_tool,
    "create_document": execute_document_generator,
}

__all__ = ["TOOLS", "execute_read_document", "execute_code_interpreter", "execute_telegram_tool", "execute_document_generator"]
