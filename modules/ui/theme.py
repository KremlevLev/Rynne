# modules/ui/theme.py
"""
Единый слой design tokens для Nova Desktop UI.

Централизует цвета, геометрию, типографику, переходы и тени.
Поддерживает тёмную и (позже) светлую тему через TOKEN_GROUPS.

Использование:
    from modules.ui.theme import Theme

    theme = Theme()
    bg = theme.color("bg.base")
    radius = theme.radius("lg")
    font = theme.font("body")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Цветовые токены
# ---------------------------------------------------------------------------

DARK_COLORS: dict[str, str] = {
    # Фон
    "bg.base": "#0B0D12",
    "bg.elevated": "#11141C",
    "bg.surface": "#171B25",
    "bg.surfaceHover": "#1D2330",
    "bg.overlay": "rgba(8, 10, 15, 0.72)",

    # Текст
    "text.primary": "#F5F7FB",
    "text.secondary": "#A7B0C0",
    "text.muted": "#6F7888",
    "text.disabled": "#4C5360",

    # Акценты
    "accent.primary": "#8B7CFF",
    "accent.secondary": "#4CC9F0",
    "accent.soft": "rgba(139, 124, 255, 0.14)",

    # Статусы
    "success": "#4ADE80",
    "warning": "#FBBF24",
    "danger": "#FB7185",
    "info": "#60A5FA",

    # Границы
    "border.subtle": "rgba(255, 255, 255, 0.07)",
    "border.active": "rgba(139, 124, 255, 0.55)",
}

# Светлая тема (заготовка — используется позже)
LIGHT_COLORS: dict[str, str] = {
    "bg.base": "#F8F9FC",
    "bg.elevated": "#FFFFFF",
    "bg.surface": "#F0F2F7",
    "bg.surfaceHover": "#E4E8F0",
    "bg.overlay": "rgba(255, 255, 255, 0.72)",

    "text.primary": "#1A1D24",
    "text.secondary": "#5A6474",
    "text.muted": "#8A94A6",
    "text.disabled": "#B8C1D4",

    "accent.primary": "#635BFF",
    "accent.secondary": "#2AA1D6",
    "accent.soft": "rgba(99, 91, 255, 0.12)",

    "success": "#22C55E",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "info": "#3B82F6",

    "border.subtle": "rgba(0, 0, 0, 0.08)",
    "border.active": "rgba(99, 91, 255, 0.55)",
}

TOKEN_GROUPS: dict[str, dict[str, str]] = {
    "dark": DARK_COLORS,
    "light": LIGHT_COLORS,
}


# ---------------------------------------------------------------------------
# Геометрия
# ---------------------------------------------------------------------------

RADIUS: dict[str, str] = {
    "sm": "8px",
    "md": "12px",
    "lg": "16px",
    "xl": "22px",
    "pill": "999px",
}

SPACING: dict[str, int] = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 20,
    "xl2": 24,
    "xl3": 32,
    "xl4": 40,
    "xl5": 48,
}


# ---------------------------------------------------------------------------
# Типографика
# ---------------------------------------------------------------------------

FONT_FAMILY_INTERFACE = "Inter, Geist, Manrope, 'Segoe UI', sans-serif"
FONT_FAMILY_MONO = "'JetBrains Mono', 'Geist Mono', 'Consolas', monospace"

FONT_SIZES: dict[str, int] = {
    "caption": 12,
    "secondary": 13,
    "bodySm": 14,
    "body": 15,
    "bodyLg": 16,
    "section": 18,
    "sectionLg": 20,
    "h1": 24,
    "h2": 32,
}

FONT_WEIGHTS: dict[str, int] = {
    "regular": 400,
    "medium": 500,
    "semibold": 600,
    "bold": 700,
}


# ---------------------------------------------------------------------------
# Переходы / анимация
# ---------------------------------------------------------------------------

# Длительности в миллисекундах
DURATIONS: dict[str, int] = {
    "micro": 140,
    "hover": 160,
    "panel": 240,
    "modal": 220,
    "page": 280,
    "orbLoop": 5000,
}

# Естественные easing curves
EASING = {
    "easeOut": "cubic-bezier(0.16, 1, 0.3, 1)",
    "easeInOut": "cubic-bezier(0.65, 0, 0.35, 1)",
}


# ---------------------------------------------------------------------------
# Тени
# ---------------------------------------------------------------------------

SHADOWS: dict[str, str] = {
    "sm": "0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.05)",
    "md": "0 4px 12px rgba(0, 0, 0, 0.10), 0 2px 4px rgba(0, 0, 0, 0.06)",
    "lg": "0 8px 24px rgba(0, 0, 0, 0.14), 0 4px 8px rgba(0, 0, 0, 0.08)",
    "accent": "0 0 16px rgba(139, 124, 255, 0.20)",
    "success": "0 0 16px rgba(74, 222, 128, 0.20)",
}


# ---------------------------------------------------------------------------
# Theme — фасад над токенами
# ---------------------------------------------------------------------------

@dataclass
class Theme:
    """
    Фасад над design tokens.

    Позволяет переключать тему и получать значения по ключу.
    """

    mode: str = "dark"
    _colors: dict[str, dict[str, str]] = field(
        default_factory=lambda: dict(TOKEN_GROUPS),
        repr=False,
    )
    _radius: dict[str, str] = field(
        default_factory=lambda: dict(RADIUS),
        repr=False,
    )
    _spacing: dict[str, int] = field(
        default_factory=lambda: dict(SPACING),
        repr=False,
    )
    _font_sizes: dict[str, int] = field(
        default_factory=lambda: dict(FONT_SIZES),
        repr=False,
    )
    _font_weights: dict[str, int] = field(
        default_factory=lambda: dict(FONT_WEIGHTS),
        repr=False,
    )
    _durations: dict[str, int] = field(
        default_factory=lambda: dict(DURATIONS),
        repr=False,
    )
    _shadows: dict[str, str] = field(
        default_factory=lambda: dict(SHADOWS),
        repr=False,
    )

    # --- цвета ----------------------------------------------------------

    def color(self, key: str, fallback: str = "") -> str:
        """Возвращает цвет по ключу, например 'bg.base'."""
        group = self._colors.get(self.mode, DARK_COLORS)
        return group.get(key, fallback)

    def colors(self) -> dict[str, str]:
        """Возвращает все цвета текущей темы."""
        return dict(self._colors.get(self.mode, DARK_COLORS))

    # --- геометрия ------------------------------------------------------

    def radius(self, key: str = "md") -> str:
        return self._radius.get(key, "12px")

    def spacing(self, key: str = "md") -> int:
        return self._spacing.get(key, 12)

    # --- типографика ----------------------------------------------------

    def font_size(self, key: str = "body") -> int:
        return self._font_sizes.get(key, 15)

    def font_weight(self, key: str = "regular") -> int:
        return self._font_weights.get(key, 400)

    def font_family(self, mono: bool = False) -> str:
        if mono:
            return FONT_FAMILY_MONO
        return FONT_FAMILY_INTERFACE

    # --- анимация -------------------------------------------------------

    def duration(self, key: str = "micro") -> int:
        return self._durations.get(key, 140)

    def easing(self, key: str = "easeOut") -> str:
        return EASING.get(key, EASING["easeOut"])

    # --- тени -----------------------------------------------------------

    def shadow(self, key: str = "md") -> str:
        return self._shadows.get(key, "")

    # --- управление темой ----------------------------------------------

    def set_mode(self, mode: str) -> None:
        if mode in self._colors:
            self.mode = mode

    def toggle_mode(self) -> str:
        self.mode = "light" if self.mode == "dark" else "dark"
        return self.mode

    # --- удобные группы -------------------------------------------------

    def background_css(self) -> str:
        """CSS-фрагмент для базового фона окна."""
        bg = self.color("bg.base")
        text = self.color("text.primary")
        return (
            f"background: {bg};\n"
            f"color: {text};\n"
            f"font-family: {self.font_family()};\n"
            f"font-size: {self.font_size('body')}px;\n"
            f"font-weight: {self.font_weight('regular')};\n"
        )


# ---------------------------------------------------------------------------
# Удобный глобальный экземпляр
# ---------------------------------------------------------------------------

theme = Theme()
