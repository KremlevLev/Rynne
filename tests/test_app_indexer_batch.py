from __future__ import annotations

import modules.tools.app_indexer as app_indexer_module
from modules.tools.app_indexer import (
    AppMatch,
    WindowsAppIndexer,
)


def test_launch_batch_is_bounded_and_uses_distinct_apps() -> None:
    indexer = object.__new__(WindowsAppIndexer)
    launched: list[str] = []

    def find_app(app_name: str) -> AppMatch:
        return AppMatch(
            query=app_name,
            matched_name=app_name,
            path=f"{app_name}.exe",
            score=1.0,
            match_type="exact",
        )

    def launch_by_name(app_name: str):
        launched.append(app_name)
        return True, f"opened {app_name}"

    indexer.find_app = find_app
    indexer.launch_by_name = launch_by_name

    result = indexer.launch_batch(5)

    assert result.success
    assert result.data["requested_count"] == 5
    assert result.data["successful_count"] == 5
    assert len(launched) == 5
    assert len(set(launched)) == 5


def test_open_url_in_named_browser_uses_process_arguments(monkeypatch) -> None:
    indexer = object.__new__(WindowsAppIndexer)
    indexer.find_app = lambda app_name: AppMatch(
        query=app_name,
        matched_name="Google Chrome",
        path=r"C:\Chrome\chrome.exe",
        score=1.0,
        match_type="exact",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        app_indexer_module.subprocess,
        "Popen",
        lambda arguments: calls.append(arguments),
    )
    monkeypatch.setattr(
        app_indexer_module,
        "get_visible_window_titles",
        lambda: ["Telegram Web - Google Chrome"],
    )

    result = indexer.open_url_in_browser(
        "google chrome",
        "https://web.telegram.org/a/",
    )

    assert result.success
    assert result.verification.verified is True
    assert calls == [[r"C:\Chrome\chrome.exe", "https://web.telegram.org/a/"]]


def test_open_url_supports_windows_shortcut(monkeypatch) -> None:
    indexer = object.__new__(WindowsAppIndexer)
    indexer.find_app = lambda app_name: AppMatch(
        query=app_name,
        matched_name="Google Chrome",
        path=r"C:\Start Menu\Google Chrome.lnk",
        score=1.0,
        match_type="exact",
    )
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        app_indexer_module.os,
        "startfile",
        lambda path, operation, arguments: calls.append((path, operation, arguments)),
    )
    monkeypatch.setattr(
        app_indexer_module,
        "get_visible_window_titles",
        lambda: ["Telegram Web - Google Chrome"],
    )

    result = indexer.open_url_in_browser(
        "google chrome",
        "https://web.telegram.org/a/",
    )

    assert result.success
    assert calls == [(
        r"C:\Start Menu\Google Chrome.lnk",
        "open",
        "https://web.telegram.org/a/",
    )]
