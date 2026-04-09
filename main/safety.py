import dataclasses
import re
from enum import IntEnum
from typing import Any, Dict, Optional


class RiskTier(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @classmethod
    def from_label(cls, value: str) -> "RiskTier":
        label = (value or "").strip().lower()
        mapping = {
            "low": cls.LOW,
            "medium": cls.MEDIUM,
            "high": cls.HIGH,
            "critical": cls.CRITICAL,
        }
        return mapping.get(label, cls.HIGH)

    def label(self) -> str:
        return {
            RiskTier.LOW: "low",
            RiskTier.MEDIUM: "medium",
            RiskTier.HIGH: "high",
            RiskTier.CRITICAL: "critical",
        }[self]


@dataclasses.dataclass
class ActionDecision:
    allowed: bool
    risk: RiskTier
    require_confirm: bool = False
    denied_reason: str = ""
    explain: str = ""
    action_key: str = ""


class ActionPolicyEngine:
    """Central policy engine for commands, tools, background tasks and plugins."""

    def __init__(
        self,
        default_mode: str = "guarded",
        confirm_threshold: RiskTier = RiskTier.HIGH,
        background_policy: str = "deny-high",
        confirm_enabled: bool = False,
    ):
        self.default_mode = (default_mode or "guarded").strip().lower()
        self.confirm_threshold = confirm_threshold
        self.background_policy = (background_policy or "deny-high").strip().lower()
        self.confirm_enabled = bool(confirm_enabled)

        self._critical_patterns = [
            (re.compile(r"\bвыключ(?:и|ить)\s+комп(?:ьютер|)\b", re.IGNORECASE), "power.shutdown"),
            (re.compile(r"\bперезагруз(?:и|ить)\s+комп(?:ьютер|)\b", re.IGNORECASE), "power.restart"),
            (re.compile(r"\bshutdown\s+/[sr]\s+/t\s*0", re.IGNORECASE), "power.system_command"),
        ]
        self._high_patterns = [
            (re.compile(r"\bочист(?:и|ить)\s+корзин", re.IGNORECASE), "recyclebin.empty"),
            (re.compile(r"\bудали\s+все\s+напомин", re.IGNORECASE), "reminder.delete_all"),
            (re.compile(r"\btaskkill\b", re.IGNORECASE), "process.kill"),
        ]

        self._tool_risks = {
            "code_interpreter": RiskTier.HIGH,
            "telegram": RiskTier.HIGH,
            "read_document": RiskTier.MEDIUM,
            "create_document": RiskTier.LOW,
            "web_search": RiskTier.LOW,
        }

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "ActionPolicyEngine":
        safety = (cfg or {}).get("safety", {}) or {}
        return cls(
            default_mode=safety.get("default_mode", "guarded"),
            confirm_threshold=RiskTier.from_label(safety.get("confirm_threshold", "high")),
            background_policy=safety.get("background_policy", "deny-high"),
            confirm_enabled=bool(safety.get("confirm_enabled", False)),
        )

    def evaluate_command(self, text: str, source: str = "chat", is_background: bool = False) -> ActionDecision:
        text = text or ""

        for pattern, key in self._critical_patterns:
            if pattern.search(text):
                return self._build_decision(
                    risk=RiskTier.CRITICAL,
                    action_key=key,
                    explain="Команда может привести к немедленному системному воздействию.",
                    source=source,
                    is_background=is_background,
                )

        for pattern, key in self._high_patterns:
            if pattern.search(text):
                return self._build_decision(
                    risk=RiskTier.HIGH,
                    action_key=key,
                    explain="Команда затрагивает потенциально необратимые пользовательские данные или процессы.",
                    source=source,
                    is_background=is_background,
                )

        return ActionDecision(
            allowed=True,
            risk=RiskTier.LOW,
            require_confirm=False,
            explain="Команда соответствует безопасному профилю.",
            action_key="command.safe",
        )

    def evaluate_tool(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        source: str = "chat",
        is_background: bool = False,
    ) -> ActionDecision:
        args = args or {}
        risk = self._tool_risks.get(tool_name, RiskTier.HIGH if tool_name.startswith("plugin__") else RiskTier.MEDIUM)
        explain = f"Инструмент '{tool_name}' выполняет действие с уровнем риска {risk.label()}."

        # Escalate code execution when shell-like payloads are present.
        if tool_name == "code_interpreter":
            payload = str(args.get("code") or "")
            if re.search(r"\b(os\.system|subprocess|shutil|Remove-Item|taskkill)\b", payload, re.IGNORECASE):
                risk = RiskTier.CRITICAL
                explain = "Инструмент запускает потенциально опасный код с системными эффектами."

        return self._build_decision(
            risk=risk,
            action_key=f"tool.{tool_name}",
            explain=explain,
            source=source,
            is_background=is_background,
        )

    def _build_decision(
        self,
        risk: RiskTier,
        action_key: str,
        explain: str,
        source: str,
        is_background: bool,
    ) -> ActionDecision:
        if is_background and self.background_policy == "deny-high" and risk >= RiskTier.HIGH:
            return ActionDecision(
                allowed=False,
                risk=risk,
                require_confirm=False,
                denied_reason="Фоновый режим блокирует high/critical действия.",
                explain=explain,
                action_key=action_key,
            )

        if self.default_mode == "strict" and risk >= RiskTier.MEDIUM:
            return ActionDecision(
                allowed=False,
                risk=risk,
                require_confirm=False,
                denied_reason="Политика strict блокирует medium/high/critical действия.",
                explain=explain,
                action_key=action_key,
            )

        requires_confirm = self.confirm_enabled and risk >= self.confirm_threshold
        return ActionDecision(
            allowed=True,
            risk=risk,
            require_confirm=requires_confirm,
            denied_reason="",
            explain=explain,
            action_key=action_key,
        )
