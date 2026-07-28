# modules/ui/theme.py
"""
Единый слой design tokens для Nova Desktop UI.

Централизует цвета, геометрию, типографику, переходы и тени.
Поддерживает тёмную и (позже) светлую тему через TOKEN_GROUPS.

Стиль: спокойный premium dark
  - глубокий сине-графитовый фон;
  - мягкие поверхности и тонкие границы;
  - холодный violet/cyan accent;
  - системный UI-шрифт с корректным fallback на Windows;
  - моноширинный шрифт только для кода и логов.

Использование:
    from modules.ui.theme import Theme

    theme = Theme()
    bg = theme.color("bg.base")
    radius = theme.radius("lg")
    font = theme.font("body")
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Цветовые токены (Nova Premium Dark)
# ---------------------------------------------------------------------------

DARK_COLORS: dict[str, str] = {
    # Фон
    "bg.base": "#0b0d12",
    "bg.elevated": "#10131a",
    "bg.surface": "#151923",
    "bg.surfaceHover": "#1c2230",
    "bg.input": "#0f1219",
    "bg.accent": "#17142a",
    "bg.overlay": "rgba(8, 10, 15, 0.72)",

    # Текст
    "text.primary": "#f5f7fb",
    "text.secondary": "#a7b0c0",
    "text.muted": "#6f7888",
    "text.disabled": "#4c5360",

    # Акценты
    "accent.primary": "#8b7cff",
    "accent.secondary": "#4cc9f0",
    "accent.soft": "#211e3a",

    # Статусы
    "success": "#4ade80",
    "warning": "#fbbf24",
    "danger": "#fb7185",
    "info": "#60a5fa",

    # Границы
    "border.subtle": "#252b38",
    "border.strong": "#343c4d",
    "border.active": "#7668ed",
}

# Светлая тема (заготовка — используется позже)
LIGHT_COLORS: dict[str, str] = {
    "bg.base": "#f8f9fa",
    "bg.elevated": "#ffffff",
    "bg.surface": "#f1f3f5",
    "bg.surfaceHover": "#e9ecef",
    "bg.input": "#ffffff",
    "bg.accent": "#efedff",
    "bg.overlay": "rgba(255, 255, 255, 0.72)",

    "text.primary": "#121212",
    "text.secondary": "#5a5a5a",
    "text.muted": "#8a8a8a",
    "text.disabled": "#b0b0b0",

    "accent.primary": "#8b7cff",
    "accent.secondary": "#4cc9f0",
    "accent.soft": "#efedff",

    "success": "#22c55e",
    "warning": "#f59e0b",
    "danger": "#ef4444",
    "info": "#3b82f6",

    "border.subtle": "rgba(0, 0, 0, 0.07)",
    "border.strong": "rgba(0, 0, 0, 0.14)",
    "border.active": "rgba(139, 124, 255, 0.55)",
}

TOKEN_GROUPS: dict[str, dict[str, str]] = {
    "dark": DARK_COLORS,
    "light": LIGHT_COLORS,
}


# ---------------------------------------------------------------------------
# Геометрия
# ---------------------------------------------------------------------------

RADIUS: dict[str, str] = {
    "sm": "7px",
    "md": "10px",
    "lg": "14px",
    "xl": "18px",
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

# Segoe UI гарантированно присутствует в поддерживаемых версиях Windows и
# корректно отображает кириллицу. Inter/Manrope используются, если установлены.
FONT_FAMILY_INTERFACE = "'Inter', 'Manrope', 'Segoe UI', sans-serif"
FONT_FAMILY_MONO = "'JetBrains Mono', 'Cascadia Code', Consolas, monospace"

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
# Тени используются точечно. QSS не поддерживает box-shadow, поэтому токены
# применяются виджетами через QGraphicsDropShadowEffect.
# ---------------------------------------------------------------------------

SHADOWS: dict[str, str] = {
    "sm": "",
    "md": "",
    "lg": "",
    "accent": "",
    "success": "",
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
        return self._radius.get(key, "0px")

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
