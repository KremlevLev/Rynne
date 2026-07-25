# tests/test_ui_theme.py
"""Тесты для design tokens и theme."""
from __future__ import annotations

import pytest

from modules.ui.theme import (
    Theme,
    theme,
    DARK_COLORS,
    LIGHT_COLORS,
    RADIUS,
    SPACING,
    FONT_SIZES,
    DURATIONS,
    EASING,
    SHADOWS,
)


class TestTheme:
    def test_default_mode_is_dark(self) -> None:
        t = Theme()
        assert t.mode == "dark"

    def test_color_returns_dark_color(self) -> None:
        t = Theme()
        assert t.color("bg.base") == DARK_COLORS["bg.base"]

    def test_color_fallback(self) -> None:
        t = Theme()
        assert t.color("nonexistent", "#FFF") == "#FFF"

    def test_colors_returns_all_dark_colors(self) -> None:
        t = Theme()
        colors = t.colors()
        assert colors["bg.base"] == DARK_COLORS["bg.base"]
        assert colors["text.primary"] == DARK_COLORS["text.primary"]

    def test_radius(self) -> None:
        t = Theme()
        assert t.radius("sm") == RADIUS["sm"]
        assert t.radius("lg") == RADIUS["lg"]
        assert t.radius("unknown") == "12px"

    def test_spacing(self) -> None:
        t = Theme()
        assert t.spacing("xs") == SPACING["xs"]
        assert t.spacing("xl5") == SPACING["xl5"]
        assert t.spacing("unknown") == 12

    def test_font_size(self) -> None:
        t = Theme()
        assert t.font_size("body") == FONT_SIZES["body"]
        assert t.font_size("h1") == FONT_SIZES["h1"]
        assert t.font_size("unknown") == 15

    def test_font_weight(self) -> None:
        t = Theme()
        assert t.font_weight("bold") == 700
        assert t.font_weight("regular") == 400

    def test_font_family(self) -> None:
        t = Theme()
        assert "Inter" in t.font_family()
        assert "JetBrains" in t.font_family(mono=True)

    def test_duration(self) -> None:
        t = Theme()
        assert t.duration("micro") == DURATIONS["micro"]
        assert t.duration("orbLoop") == DURATIONS["orbLoop"]

    def test_easing(self) -> None:
        t = Theme()
        assert t.easing("easeOut") == EASING["easeOut"]
        assert t.easing("easeInOut") == EASING["easeInOut"]

    def test_shadow(self) -> None:
        t = Theme()
        assert t.shadow("sm") == SHADOWS["sm"]
        assert t.shadow("lg") == SHADOWS["lg"]

    def test_set_mode(self) -> None:
        t = Theme()
        t.set_mode("light")
        assert t.mode == "light"
        assert t.color("bg.base") == LIGHT_COLORS["bg.base"]

    def test_set_mode_invalid(self) -> None:
        t = Theme()
        t.set_mode("invalid")
        assert t.mode == "dark"

    def test_toggle_mode(self) -> None:
        t = Theme()
        assert t.mode == "dark"
        result = t.toggle_mode()
        assert result == "light"
        assert t.mode == "light"
        result = t.toggle_mode()
        assert result == "dark"
        assert t.mode == "dark"

    def test_background_css(self) -> None:
        t = Theme()
        css = t.background_css()
        assert "background:" in css
        assert "color:" in css
        assert "font-family:" in css

    def test_global_theme_instance(self) -> None:
        assert isinstance(theme, Theme)
        assert theme.mode == "dark"

    def test_all_dark_colors_present(self) -> None:
        required_keys = [
            "bg.base", "bg.elevated", "bg.surface",
            "text.primary", "text.secondary", "text.muted",
            "accent.primary", "accent.secondary",
            "success", "warning", "danger", "info",
            "border.subtle", "border.active",
        ]
        for key in required_keys:
            assert key in DARK_COLORS, f"Missing color: {key}"

    def test_all_light_colors_present(self) -> None:
        for key in DARK_COLORS:
            assert key in LIGHT_COLORS, f"Missing light color: {key}"

    def test_radius_keys(self) -> None:
        assert "sm" in RADIUS
        assert "md" in RADIUS
        assert "lg" in RADIUS
        assert "xl" in RADIUS
        assert "pill" in RADIUS

    def test_duration_keys(self) -> None:
        assert "micro" in DURATIONS
        assert "hover" in DURATIONS
        assert "panel" in DURATIONS
        assert "orbLoop" in DURATIONS

    def test_easing_curves(self) -> None:
        assert "easeOut" in EASING
        assert "easeInOut" in EASING
        assert "cubic-bezier" in EASING["easeOut"]
