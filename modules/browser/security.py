# modules/browser/security.py
"""Browser security against prompt injection.

Защищает от prompt injection на веб-страницах:
- Разделение инструкции пользователя и содержимого сайта
- Запрет странице командовать агентом
- Allowlist доменов для опасных действий
- Санитизация HTML-контента
"""
from __future__ import annotations

import re
import logging
from typing import Any

logger = logging.getLogger("BrowserSecurity")


# Patterns that indicate prompt injection attempts
PROMPT_INJECTION_PATTERNS = [
    # Direct instruction patterns
    r"(?i)ignore\s+(?:all\s+)?(?:previous\s+)?instructions",
    r"(?i)disregard\s+(?:all\s+)?(?:previous\s+)?instructions",
    r"(?i)forget\s+(?:all\s+)?(?:previous\s+)?instructions",
    r"(?i)new\s+instructions",
    r"(?i)system\s+override",
    r"(?i)admin\s+mode",
    r"(?i)developer\s+mode",
    r"(?i)jailbreak",
    r"(?i)prompt\s+injection",
    r"(?i)act\s+as\s+(?:a\s+)?(?:different|new)",
    r"(?i)you\s+are\s+now",
    r"(?i)you\s+will\s+now",
    r"(?i)do\s+not\s+follow",
    r"(?i)instead\s+of",
    r"(?i)ignore\s+the\s+above",
    r"(?i)ignore\s+this\s+prompt",
    r"(?i)replace\s+the\s+above",
    r"(?i)override\s+the\s+above",
    r"(?i)forget\s+the\s+above",
    r"(?i)new\s+system\s+prompt",
    r"(?i)system\s+prompt",
    r"(?i)assistant\s*:",
    r"(?i)user\s*:",
    r"(?i)agent\s*:",
    r"(?i)ai\s*:",
    r"(?i)llm\s*:",
    r"(?i)instruction\s*:",
    r"(?i)command\s*:",
    r"(?i)execute\s*:",
    r"(?i)run\s*:",
    r"(?i)output\s*:",
    r"(?i)response\s*:",
    r"(?i)reply\s*:",
    r"(?i)answer\s*:",
    r"(?i)print\s*:",
    r"(?i)return\s*:",
    r"(?i)send\s*:",
    r"(?i)type\s*:",
    r"(?i)enter\s*:",
    r"(?i)click\s*:",
    r"(?i)press\s*:",
    r"(?i)open\s*:",
    r"(?i)go\s+to\s*:",
    r"(?i)navigate\s+to\s*:",
    r"(?i)visit\s*:",
    r"(?i)access\s*:",
    r"(?i)download\s*:",
    r"(?i)upload\s*:",
    r"(?i)delete\s*:",
    r"(?i)remove\s*:",
    r"(?i)install\s*:",
    r"(?i)run\s+this\s*:",
    r"(?i)run\s+the\s+following",
    r"(?i)execute\s+this\s*:",
    r"(?i)execute\s+the\s+following",
    r"(?i)run\s+command",
    r"(?i)execute\s+command",
    r"(?i)bash\s*:",
    r"(?i)powershell\s*:",
    r"(?i)cmd\s*:",
    r"(?i)terminal\s*:",
    r"(?i)shell\s*:",
    r"(?i)code\s*:",
    r"(?i)script\s*:",
    r"(?i)function\s*:",
    r"(?i)def\s+\w+\s*\(",
    r"(?i)import\s+\w+",
    r"(?i)from\s+\w+\s+import",
    r"(?i)pip\s+install",
    r"(?i)npm\s+install",
    r"(?i)curl\s+https?",
    r"(?i)wget\s+https?",
    r"(?i)http\.get",
    r"(?i)http\.post",
    r"(?i)fetch\s*\(",
    r"(?i)axios\.",
    r"(?i)requests\.",
    r"(?i)subprocess\.",
    r"(?i)os\.system",
    r"(?i)eval\s*\(",
    r"(?i)exec\s*\(",
    r"(?i)execfile",
    r"(?i)compile\s*\(",
    r"(?i)__import__\s*\(",
    r"(?i)open\s*\(",
    r"(?i)file\s*:",
    r"(?i)write\s*:",
    r"(?i)read\s*:",
    r"(?i)rm\s+-rf",
    r"(?i)del\s+/[qf]",
    r"(?i)format\s+[a-z]:",
    r"(?i)shutdown",
    r"(?i)reboot",
    r"(?i)restart",
    r"(?i)kill\s+process",
    r"(?i)taskkill",
    r"(?i)net\s+stop",
    r"(?i)sc\s+stop",
    r"(?i)reg\s+delete",
    r"(?i)reg\s+add",
    r"(?i)Set-ItemProperty",
    r"(?i)Remove-Item",
    r"(?i)New-Item",
    r"(?i)Get-ChildItem",
    r"(?i)Start-Process",
    r"(?i)Stop-Process",
]

# Dangerous HTML patterns
DANGEROUS_HTML_PATTERNS = [
    r"(?i)<script[^>]*>",
    r"(?i)</script>",
    r"(?i)javascript:",
    r"(?i)on\w+\s*=",
    r"(?i)<iframe[^>]*>",
    r"(?i)</iframe>",
    r"(?i)<object[^>]*>",
    r"(?i)</object>",
    r"(?i)<embed[^>]*>",
    r"(?i)</embed>",
    r"(?i)<form[^>]*>",
    r"(?i)</form>",
    r"(?i)<input[^>]*>",
    r"(?i)<button[^>]*>",
    r"(?i)<textarea[^>]*>",
    r"(?i)<select[^>]*>",
]

# Default allowlist for dangerous actions
DEFAULT_DANGEROUS_ACTION_ALLOWLIST = {
    "api.github.com",
    "github.com",
    "www.github.com",
    "gitlab.com",
    "www.gitlab.com",
    "npmjs.com",
    "www.npmjs.com",
    "pypi.org",
    "www.pypi.org",
    "crates.io",
    "www.crates.io",
    "docs.python.org",
    "docs.microsoft.com",
    "developer.mozilla.org",
    "api.openai.com",
    "platform.openai.com",
    "anthropic.com",
    "console.anthropic.com",
    "huggingface.co",
    "huggingface.com",
    "googleapis.com",
    "google.com",
    "www.google.com",
    "microsoft.com",
    "www.microsoft.com",
    "amazon.com",
    "aws.amazon.com",
    "console.aws.amazon.com",
}


class BrowserSecurity:
    """
    Защита браузерного контента от prompt injection.
    
    Разделяет содержимое страницы и инструкции пользователя,
    удаляет потенциально опасные паттерны.
    """

    def __init__(
        self,
        allowlist: set[str] | None = None,
    ) -> None:
        self.allowlist = allowlist or DEFAULT_DANGEROUS_ACTION_ALLOWLIST.copy()
        self._compiled_patterns = [
            re.compile(p) for p in PROMPT_INJECTION_PATTERNS
        ]
        self._html_patterns = [
            re.compile(p) for p in DANGEROUS_HTML_PATTERNS
        ]

    def is_domain_allowed_for_dangerous_actions(
        self,
        url: str,
    ) -> bool:
        """
        Проверяет, разрешено ли выполнять опасные действия на домене.
        
        Args:
            url: URL для проверки
            
        Returns:
            True если домен в allowlist
        """
        from urllib.parse import urlparse
        
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            hostname = hostname.lower().rstrip(".")
            
            # Check exact match
            if hostname in self.allowlist:
                return True
            
            # Check subdomain match
            for allowed in self.allowlist:
                if hostname.endswith(f".{allowed}"):
                    return True
            
            return False
        except Exception:
            return False

    def sanitize_content(
        self,
        content: str,
        *,
        aggressive: bool = True,
    ) -> str:
        """
        Санитизует контент страницы от prompt injection.
        
        Args:
            content: Исходный текст страницы
            aggressive: Агрессивная фильтрация (удалять подозрительные блоки)
            
        Returns:
            Очищенный текст
        """
        if not content:
            return content

        sanitized = content

        # Remove prompt injection patterns
        for pattern in self._compiled_patterns:
            sanitized = pattern.sub("[REMOVED_SUSPICIOUS_CONTENT]", sanitized)

        if aggressive:
            # Remove dangerous HTML patterns
            for pattern in self._html_patterns:
                sanitized = pattern.sub("[REMOVED_HTML]", sanitized)

        return sanitized

    def detect_injection(
        self,
        content: str,
    ) -> list[str]:
        """
        Обнаруживает попытки prompt injection в контенте.
        
        Args:
            content: Текст для анализа
            
        Returns:
            Список найденных паттернов
        """
        if not content:
            return []

        found_patterns = []
        
        for pattern in self._compiled_patterns:
            matches = pattern.findall(content)
            if matches:
                found_patterns.extend(matches)

        return found_patterns

    def create_safe_context(
        self,
        page_content: str,
        user_instruction: str,
        url: str,
    ) -> dict[str, Any]:
        """
        Создаёт безопасный контекст для передачи модели.
        
        Разделяет содержимое страницы и инструкцию пользователя,
        добавляя маркеры границ.
        
        Args:
            page_content: Содержимое страницы
            user_instruction: Инструкция пользователя
            url: URL страницы
            
        Returns:
            Словарь с безопасным контекстом
        """
        sanitized_content = self.sanitize_content(page_content)
        detected = self.detect_injection(page_content)
        
        return {
            "url": url,
            "user_instruction": user_instruction,
            "page_content": sanitized_content,
            "injection_detected": len(detected) > 0,
            "injection_patterns": detected,
            "domain_allowed": self.is_domain_allowed_for_dangerous_actions(url),
        }

    def should_block_action(
        self,
        action: str,
        url: str,
    ) -> tuple[bool, str | None]:
        """
        Проверяет, нужно ли блокировать действие.
        
        Args:
            action: Тип действия (click, fill, download, etc.)
            url: URL страницы
            
        Returns:
            (нужно_ли_блокировать, причина)
        """
        dangerous_actions = {
            "download",
            "upload",
            "fill",
            "click",
            "press",
            "execute",
            "run",
            "submit",
        }
        
        if action.lower() in dangerous_actions:
            if not self.is_domain_allowed_for_dangerous_actions(url):
                return (
                    True,
                    f"Действие '{action}' заблокировано: домен не в allowlist"
                )
        
        return False, None


def create_browser_security(
    allowlist: set[str] | None = None,
) -> BrowserSecurity:
    """
    Создаёт экземпляр BrowserSecurity.
    
    Args:
        allowlist: Список разрешённых доменов
        
    Returns:
        Экземпляр BrowserSecurity
    """
    return BrowserSecurity(allowlist=allowlist)