from typing import List, TYPE_CHECKING


if TYPE_CHECKING:
    from .executor import ExecutionStep


def summarize_execution(steps: List["ExecutionStep"]) -> str:
    """
    Создаёт краткий отчёт о выполнении плана.
    
    Args:
        steps: Список выполненных шагов
    
    Returns:
        Текстовый отчёт для пользователя
    """
    if not steps:
        return "Нет данных о выполнении."
    
    total = len(steps)
    successful = sum(1 for s in steps if s.success)
    failed = total - successful
    
    # Собираем ключевые результаты
    key_results = []
    for step in steps:
        if step.success and step.result:
            # Берём первое предложение результата
            first_sentence = step.result.split('.')[0].strip()
            if first_sentence and len(first_sentence) > 5:
                key_results.append(first_sentence)
    
    # Формируем отчёт
    if failed == 0:
        status = "Все шаги выполнены успешно."
    elif successful == 0:
        status = "Не удалось выполнить задачу."
    else:
        status = f"Выполнено {successful} из {total} шагов."
    
    if key_results:
        # Ограничиваем количество результатов
        results_text = ". ".join(key_results[:3])
        return f"{status} {results_text}."
    
    return status






