from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict, Any
import time

from .result_patterns import is_successful_result as _is_successful_result


@dataclass
class ExecutionStep:
    """Результат выполнения одного шага плана."""
    step: str                          # Текст шага
    result: Optional[str] = None       # Результат выполнения
    success: bool = False              # Успешно ли выполнен
    attempts: int = 0                  # Количество попыток
    error: Optional[str] = None        # Сообщение об ошибке
    execution_time: float = 0.0        # Время выполнения (секунды)


@dataclass
class ExecutionResult:
    """Результат выполнения всего плана."""
    steps: List[ExecutionStep] = field(default_factory=list)
    total_time: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    context: Dict[str, Any] = field(default_factory=dict)  # Накопленный контекст
    
    @property
    def all_successful(self) -> bool:
        return self.failure_count == 0 and self.success_count > 0
    
    @property
    def partial_success(self) -> bool:
        return self.success_count > 0 and self.failure_count > 0
    
    def get_accumulated_results(self) -> str:
        """Возвращает все успешные результаты шагов как единый текст."""
        results = []
        for step in self.steps:
            if step.success and step.result:
                results.append(step.result)
        return "\n\n".join(results)


def _inject_context(step: str, context: Dict[str, Any]) -> str:
    if not context:
        return step
    
    # Получаем последний результат
    last_result = context.get("last_result", "")
    
    # Ключевые слова, указывающие на использование контекста
    context_keywords = [
        "из результатов", "из найденного", "на основе",
        "используя найденное", "из этого", "по этой информации",
        "с этими данными", "эту информацию"
    ]
    
    step_lower = step.lower()
    needs_context = any(kw in step_lower for kw in context_keywords)
    
    # Если шаг требует контекста и он есть — добавляем
    if needs_context and last_result:
        # Ограничиваем размер контекста (макс 1000 символов)
        truncated = last_result[:1000]
        if len(last_result) > 1000:
            truncated += "..."
        return f"{step}\n\nКонтекст из предыдущего шага:\n{truncated}"
    
    return step


def execute_step(
    step: str,
    route_func: Callable[[str], str],
    context: Dict[str, Any] = None,
    max_attempts: int = 2
) -> ExecutionStep:
    exec_step = ExecutionStep(step=step)
    context = context or {}
    
    # Внедряем контекст в шаг
    step_with_context = _inject_context(step, context)
    
    for attempt in range(1, max_attempts + 1):
        exec_step.attempts = attempt
        start_time = time.time()
        
        try:
            result = route_func(step_with_context)
            exec_step.execution_time = time.time() - start_time
            exec_step.result = result
            
            if _is_successful_result(result):
                exec_step.success = True
                print(f"[EXECUTOR] [OK] Шаг выполнен (попытка {attempt}): {step[:50]}...")
                break
            else:
                if attempt < max_attempts:
                    print(f"[EXECUTOR] ⟳ Повтор шага (попытка {attempt}): {step[:50]}...")
                    time.sleep(0.5)  # Небольшая пауза перед retry
                else:
                    exec_step.success = False
                    print(f"[EXECUTOR] [FAIL] Шаг не удался после {attempt} попыток: {step[:50]}...")
        
        except Exception as e:
            exec_step.execution_time = time.time() - start_time
            exec_step.error = str(e)
            exec_step.success = False
            print(f"[EXECUTOR] [FAIL] Ошибка на шаге: {e}")
            
            if attempt >= max_attempts:
                break
            time.sleep(0.5)
    
    return exec_step


def execute_plan(
    plan: List[str],
    route_func: Callable[[str], str],
    max_attempts_per_step: int = 2,
    stop_on_failure: bool = False,
    initial_context: Dict[str, Any] = None
) -> ExecutionResult:

    result = ExecutionResult()
    result.context = initial_context.copy() if initial_context else {}
    start_time = time.time()
    
    print(f"[EXECUTOR] Начинаю выполнение плана из {len(plan)} шагов")
    
    all_results = []
    
    for i, step in enumerate(plan, 1):
        print(f"[EXECUTOR] Шаг {i}/{len(plan)}: {step}")
        
        step_result = execute_step(step, route_func, result.context, max_attempts_per_step)
        result.steps.append(step_result)
        
        if step_result.success:
            result.success_count += 1
            
            # Обновляем контекст
            if step_result.result:
                result.context["last_result"] = step_result.result
                all_results.append(step_result.result)
                result.context["all_results"] = "\n\n".join(all_results[-3:])  # Последние 3 результата
                result.context["step_results"] = {
                    f"step_{j}": s.result for j, s in enumerate(result.steps, 1) if s.success
                }
        else:
            result.failure_count += 1
            if stop_on_failure:
                print(f"[EXECUTOR] Остановка из-за неудачи на шаге {i}")
                break
    
    result.total_time = time.time() - start_time
    print(f"[EXECUTOR] План выполнен за {result.total_time:.1f}с: "
          f"{result.success_count} успешно, {result.failure_count} неудач")
    
    return result

