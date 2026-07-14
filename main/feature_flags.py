"""Project-wide feature switches for integrations that must stay dormant."""


# Telegram is intentionally kept in the repository, but must not be exposed to
# routing, the LLM tool list, or any runtime entry point until explicitly
# reviewed and re-enabled in code.
TELEGRAM_INTEGRATION_ENABLED = False
TELEGRAM_DISABLED_MESSAGE = "Интеграция с Telegram отключена."
