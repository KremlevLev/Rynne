# tests/test_browser_manager.py
from __future__ import annotations

import asyncio

from modules.browser.manager import (
    BrowserManager,
    default_browser_profile_directory,
    validate_browser_url,
    validate_selector,
)


def test_public_https_url_is_allowed() -> None:
    valid, normalized, error = (
        validate_browser_url(
            "https://example.com"
        )
    )

    assert valid
    assert normalized == "https://example.com"
    assert error is None


def test_url_without_scheme_gets_https() -> None:
    valid, normalized, error = (
        validate_browser_url(
            "example.com"
        )
    )

    assert valid
    assert normalized == "https://example.com"


def test_localhost_is_blocked() -> None:
    valid, _, error = validate_browser_url(
        "http://localhost:8000"
    )

    assert not valid
    assert error is not None


def test_loopback_ip_is_blocked() -> None:
    valid, _, error = validate_browser_url(
        "http://127.0.0.1"
    )

    assert not valid
    assert error is not None


def test_private_ip_is_blocked() -> None:
    valid, _, error = validate_browser_url(
        "http://192.168.1.10"
    )

    assert not valid
    assert error is not None


def test_file_scheme_is_blocked() -> None:
    valid, _, error = validate_browser_url(
        "file:///C:/Windows/system.ini"
    )

    assert not valid
    assert error is not None


def test_javascript_scheme_is_blocked() -> None:
    valid, _, error = validate_browser_url(
        "javascript:alert(1)"
    )

    assert not valid
    assert error is not None

def test_data_scheme_is_blocked() -> None:
    valid, _, error = validate_browser_url(
        "data:text/html,<h1>test</h1>"
    )

    assert not valid
    assert error is not None


def test_file_scheme_is_blocked_without_slashes() -> None:
    valid, _, error = validate_browser_url(
        "file:C:/Windows/system.ini"
    )

    assert not valid
    assert error is not None


def test_ftp_scheme_is_blocked() -> None:
    valid, _, error = validate_browser_url(
        "ftp://example.com/file.txt"
    )

    assert not valid
    assert error is not None


def test_local_subdomain_is_blocked() -> None:
    valid, _, error = validate_browser_url(
        "http://service.local"
    )

    assert not valid
    assert error is not None


def test_url_credentials_are_blocked() -> None:
    valid, _, error = validate_browser_url(
        "https://user:password@example.com"
    )

    assert not valid
    assert error is not None


def test_protocol_relative_public_url_is_allowed() -> None:
    valid, normalized, error = (
        validate_browser_url(
            "//example.com/page"
        )
    )

    assert valid
    assert normalized == "https://example.com/page"
    assert error is None


def test_invalid_port_is_blocked() -> None:
    valid, _, error = validate_browser_url(
        "https://example.com:99999"
    )

    assert not valid
    assert error is not None


def test_valid_selector() -> None:
    valid, error = validate_selector(
        "button[type='submit']"
    )

    assert valid
    assert error is None


def test_empty_selector_is_rejected() -> None:
    valid, error = validate_selector("")

    assert not valid
    assert error is not None


def test_browser_status_before_start() -> None:
    async def scenario() -> None:
        manager = BrowserManager(
            headless=True
        )

        result = await manager.status()

        assert result.success
        assert result.data["started"] is False

        await manager.close()

    asyncio.run(scenario())


def test_browser_profile_directory_can_be_overridden(
    monkeypatch,
    tmp_path,
) -> None:
    profile = tmp_path / "browser-profile"
    monkeypatch.setenv(
        "NOVA_BROWSER_PROFILE_DIR",
        str(profile),
    )

    assert default_browser_profile_directory() == profile


def test_system_chrome_uses_persistent_profile(
    monkeypatch,
    tmp_path,
) -> None:
    import playwright.async_api

    calls: list[tuple[str, str]] = []

    class FakePage:
        url = "about:blank"

    class FakeContext:
        browser = None
        pages = [FakePage()]

        async def new_page(self):
            raise AssertionError("Existing page should be reused")

        async def close(self) -> None:
            calls.append(("close", "context"))

    class FakeChromium:
        async def launch_persistent_context(
            self,
            *,
            user_data_dir: str,
            channel: str,
            **_kwargs,
        ):
            calls.append((channel, user_data_dir))
            return FakeContext()

        async def launch(self, **_kwargs):
            raise AssertionError(
                "Bundled Chromium must not be used when Chrome is available"
            )

    class FakePlaywright:
        chromium = FakeChromium()

        async def stop(self) -> None:
            calls.append(("stop", "playwright"))

    class FakeStarter:
        async def start(self):
            return FakePlaywright()

    monkeypatch.setattr(
        playwright.async_api,
        "async_playwright",
        lambda: FakeStarter(),
    )

    async def scenario() -> None:
        manager = BrowserManager(
            headless=False,
            profile_directory=tmp_path,
        )
        result = await manager.start()

        assert result.success
        assert result.data["runtime"] == "chrome"
        assert result.data["persistent_profile"] is True
        assert manager.is_started
        assert calls[0] == ("chrome", str(tmp_path))

        await manager.close()

    asyncio.run(scenario())
