# modules/browser/manager.py
from __future__ import annotations
import re
import asyncio
import ipaddress
import logging
import os
import socket
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from modules.domain.results import (
    ToolResult,
    VerificationResult,
)


logger = logging.getLogger("BrowserManager")


SCREENSHOTS_DIRECTORY = Path(
    "data/artifacts/browser"
)

MAX_EXTRACTED_TEXT_LENGTH = 50_000
MAX_SELECTOR_LENGTH = 500
MAX_INPUT_TEXT_LENGTH = 100_000
SYSTEM_BROWSER_CHANNELS = ("chrome", "msedge")


def default_browser_profile_directory() -> Path:
    """Return a Nova-owned browser profile that survives Core restarts."""
    configured = os.getenv("NOVA_BROWSER_PROFILE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()

    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / "Nova" / "browser-profile"

    cache_home = os.getenv("XDG_CACHE_HOME", "").strip()
    if cache_home:
        return Path(cache_home) / "nova" / "browser-profile"

    return Path.home() / ".nova" / "browser-profile"


def validate_browser_url(
    url: str,
) -> tuple[bool, str | None, str | None]:
    """
    Проверяет URL до передачи браузеру.

    Разрешает только публичные HTTP/HTTPS-адреса.
    Блокирует опасные схемы, локальные имена и прямые
    приватные или служебные IP-адреса.
    """
    clean_url = str(url).strip()

    if not clean_url:
        return False, None, "Адрес страницы пуст."

    # Схема может существовать без последовательности ://:
    # javascript:alert(1), data:text/html,..., file:C:\\...
    explicit_scheme_match = re.match(
        r"^([A-Za-z][A-Za-z0-9+.-]*):",
        clean_url,
    )

    if explicit_scheme_match:
        explicit_scheme = (
            explicit_scheme_match.group(1).lower()
        )

        if explicit_scheme not in {
            "http",
            "https",
        }:
            return (
                False,
                None,
                (
                    "Разрешены только HTTP и HTTPS. "
                    f"Получена запрещённая схема: "
                    f"{explicit_scheme}."
                ),
            )

    elif clean_url.startswith("//"):
        # Protocol-relative URL.
        clean_url = "https:" + clean_url

    else:
        clean_url = "https://" + clean_url

    try:
        parsed = urlparse(clean_url)
    except ValueError as exc:
        return (
            False,
            None,
            f"Некорректный URL: {exc}",
        )

    scheme = parsed.scheme.lower()

    if scheme not in {
        "http",
        "https",
    }:
        return (
            False,
            None,
            (
                "Разрешены только HTTP и HTTPS. "
                f"Получена схема: "
                f"{scheme or 'не указана'}."
            ),
        )

    # Не разрешаем credentials внутри URL:
    # https://user:password@example.com
    if parsed.username is not None:
        return (
            False,
            None,
            (
                "Адреса со встроенными учётными "
                "данными запрещены."
            ),
        )

    hostname = (
        parsed.hostname.lower().rstrip(".")
        if parsed.hostname
        else ""
    )

    if not hostname:
        return (
            False,
            None,
            "URL не содержит имя хоста.",
        )

    blocked_hostnames = {
        "localhost",
        "localhost.localdomain",
        "host.docker.internal",
        "gateway.docker.internal",
        "metadata.google.internal",
    }

    if (
        hostname in blocked_hostnames
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
    ):
        return (
            False,
            None,
            (
                "Доступ к локальному или служебному "
                "адресу запрещён."
            ),
        )

    # Обращение к parsed.port может выбросить ValueError,
    # например при порте больше 65535.
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        return (
            False,
            None,
            f"Некорректный порт: {exc}",
        )

    if parsed_port is not None and not (
        1 <= parsed_port <= 65535
    ):
        return (
            False,
            None,
            "Порт должен находиться в диапазоне 1–65535.",
        )

    try:
        direct_ip = ipaddress.ip_address(hostname)
    except ValueError:
        direct_ip = None

    if (
        direct_ip is not None
        and _is_blocked_ip(direct_ip)
    ):
        return (
            False,
            None,
            (
                "Доступ к локальному или служебному "
                f"IP-адресу {direct_ip} запрещён."
            ),
        )

    return True, clean_url, None



def _is_blocked_ip(
    address: ipaddress.IPv4Address
    | ipaddress.IPv6Address,
) -> bool:
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


async def validate_resolved_host(
    url: str,
) -> tuple[bool, str | None]:
    """
    Проверяет IP после DNS-resolve.

    Это второй слой SSRF-защиты: публичный домен не должен
    разрешаться в локальный адрес.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname

    if not hostname:
        return False, "URL не содержит имя хоста."

    port = parsed.port

    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    loop = asyncio.get_running_loop()

    try:
        address_info = await loop.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        return (
            False,
            f"Не удалось разрешить домен {hostname}: {exc}",
        )

    for entry in address_info:
        raw_ip = entry[4][0]

        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue

        if _is_blocked_ip(address):
            return (
                False,
                (
                    f"Домен {hostname} разрешился в "
                    f"запрещённый адрес {address}."
                ),
            )

    return True, None


def validate_selector(
    selector: str,
) -> tuple[bool, str | None]:
    clean_selector = str(selector).strip()

    if not clean_selector:
        return False, "Селектор элемента пуст."

    if len(clean_selector) > MAX_SELECTOR_LENGTH:
        return (
            False,
            (
                f"Селектор превышает лимит "
                f"{MAX_SELECTOR_LENGTH} символов."
            ),
        )

    return True, None


class BrowserManager:
    """
    Browser Agent на Playwright с отдельным профилем Nova.

    Браузер загружается лениво при первом использовании.
    Сначала используется системный Chrome или Edge, поэтому installer не обязан
    поставлять тяжёлый Chromium. Cookies сохраняются только в профиле Nova, а не
    читаются из личного профиля браузера пользователя.
    """

    def __init__(
        self,
        *,
        headless: bool = False,
        profile_directory: str | Path | None = None,
    ) -> None:
        self.headless = headless
        self.profile_directory = (
            Path(profile_directory).expanduser()
            if profile_directory is not None
            else default_browser_profile_directory()
        )

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._runtime: str | None = None
        self._persistent_context = False

        self._lock = asyncio.Lock()

    @property
    def is_started(self) -> bool:
        return (
            self._context is not None
            and self._page is not None
        )

    async def start(self) -> ToolResult:
        async with self._lock:
            if self.is_started:
                return ToolResult.ok(
                    "Браузерный агент уже запущен.",
                    data={
                        "already_running": True,
                    },
                )

            try:
                from playwright.async_api import (
                    async_playwright,
                )
            except ImportError:
                return ToolResult.failure(
                    "PLAYWRIGHT_NOT_INSTALLED",
                    (
                        "Playwright не установлен. Выполните: "
                        "py -m pip install playwright"
                    ),
                )

            try:
                self._playwright = (
                    await async_playwright().start()
                )
                self.profile_directory.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                launch_errors: dict[str, str] = {}
                for channel in SYSTEM_BROWSER_CHANNELS:
                    try:
                        self._context = await (
                            self._playwright.chromium
                            .launch_persistent_context(
                                user_data_dir=str(
                                    self.profile_directory
                                ),
                                channel=channel,
                                headless=self.headless,
                                accept_downloads=True,
                                viewport={
                                    "width": 1440,
                                    "height": 900,
                                },
                            )
                        )
                        self._browser = self._context.browser
                        self._runtime = channel
                        self._persistent_context = True
                        break
                    except Exception as channel_error:
                        launch_errors[channel] = str(
                            channel_error
                        ).splitlines()[0]

                if self._context is None:
                    try:
                        self._browser = await (
                            self._playwright.chromium.launch(
                                headless=self.headless,
                            )
                        )
                        self._context = (
                            await self._browser.new_context(
                                accept_downloads=True,
                                viewport={
                                    "width": 1440,
                                    "height": 900,
                                },
                            )
                        )
                        self._runtime = "playwright-chromium"
                        self._persistent_context = False
                    except Exception as bundled_error:
                        launch_errors["playwright-chromium"] = str(
                            bundled_error
                        ).splitlines()[0]
                        raise RuntimeError(
                            "Chrome, Edge и встроенный Chromium "
                            "недоступны."
                        ) from bundled_error

                pages = list(self._context.pages)
                self._page = (
                    pages[0]
                    if pages
                    else await self._context.new_page()
                )

                logger.info(
                    "Playwright browser запущен. runtime=%s headless=%s",
                    self._runtime,
                    self.headless,
                )

                return ToolResult.ok(
                    "Браузер Nova запущен. Авторизация сайтов "
                    "сохраняется в отдельном профиле Nova.",
                    data={
                        "headless": self.headless,
                        "runtime": self._runtime,
                        "persistent_profile": (
                            self._persistent_context
                        ),
                        "profile_directory": str(
                            self.profile_directory
                        ),
                    },
                    verification=VerificationResult(
                        verified=True,
                        method="browser_process_started",
                        confidence=1.0,
                    ),
                )

            except Exception as exc:
                logger.exception(
                    "Не удалось запустить браузер."
                )

                await self._close_without_lock()

                return ToolResult.failure(
                    "BROWSER_START_FAILED",
                    (
                        "Не удалось запустить браузер Nova. "
                        "Установите Google Chrome или Microsoft Edge "
                        "и повторите команду."
                    ),
                    data={
                        "technical_error": str(exc).splitlines()[0],
                        "attempts": locals().get(
                            "launch_errors",
                            {},
                        ),
                    },
                )

    async def _ensure_started(self) -> ToolResult | None:
        if self.is_started:
            return None

        start_result = await self.start()

        if not start_result.success:
            return start_result

        return None

    async def open_url(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 30_000,
    ) -> ToolResult:
        valid, normalized_url, error = (
            validate_browser_url(url)
        )

        if not valid or normalized_url is None:
            return ToolResult.failure(
                "URL_BLOCKED",
                error or "Адрес заблокирован.",
            )

        dns_valid, dns_error = (
            await validate_resolved_host(
                normalized_url
            )
        )

        if not dns_valid:
            return ToolResult.failure(
                "URL_BLOCKED_AFTER_DNS",
                dns_error or "Адрес заблокирован.",
            )

        start_error = await self._ensure_started()

        if start_error is not None:
            return start_error

        assert self._page is not None

        try:
            response = await self._page.goto(
                normalized_url,
                wait_until=wait_until,
                timeout=max(
                    1_000,
                    min(timeout_ms, 120_000),
                ),
            )

            final_url = self._page.url

            final_valid, _, final_error = (
                validate_browser_url(final_url)
            )

            if not final_valid:
                await self._page.goto("about:blank")

                return ToolResult.failure(
                    "UNSAFE_REDIRECT",
                    (
                        "Страница перенаправила браузер "
                        "на запрещённый адрес. "
                        f"Причина: {final_error}"
                    ),
                )

            title = await self._page.title()
            status_code = (
                response.status
                if response is not None
                else None
            )

            return ToolResult.ok(
                f"Открыта страница '{title or final_url}'.",
                data={
                    "requested_url": normalized_url,
                    "final_url": final_url,
                    "title": title,
                    "status_code": status_code,
                },
                verification=VerificationResult(
                    verified=True,
                    method="browser_navigation",
                    confidence=1.0,
                    details=(
                        f"Финальный URL: {final_url}"
                    ),
                ),
            )

        except Exception as exc:
            logger.exception(
                "Ошибка перехода браузера."
            )

            return ToolResult.failure(
                "BROWSER_NAVIGATION_FAILED",
                (
                    f"Не удалось открыть "
                    f"'{normalized_url}': {exc}"
                ),
                retryable=True,
            )

    async def get_page_text(
        self,
        selector: str = "body",
        *,
        max_characters: int = 20_000,
    ) -> ToolResult:
        selector_valid, selector_error = (
            validate_selector(selector)
        )

        if not selector_valid:
            return ToolResult.failure(
                "INVALID_SELECTOR",
                selector_error
                or "Селектор некорректен.",
            )

        start_error = await self._ensure_started()

        if start_error is not None:
            return start_error

        assert self._page is not None

        safe_limit = max(
            1,
            min(
                max_characters,
                MAX_EXTRACTED_TEXT_LENGTH,
            ),
        )

        try:
            locator = self._page.locator(
                selector
            ).first

            count = await self._page.locator(
                selector
            ).count()

            if count <= 0:
                return ToolResult.failure(
                    "BROWSER_ELEMENT_NOT_FOUND",
                    (
                        "Элемент не найден по селектору "
                        f"'{selector}'."
                    ),
                )

            text = await locator.inner_text(
                timeout=15_000
            )

            was_truncated = len(text) > safe_limit
            returned_text = text[:safe_limit]

            return ToolResult.ok(
                (
                    f"Текст страницы прочитан: "
                    f"{len(returned_text)} символов."
                ),
                data={
                    "url": self._page.url,
                    "selector": selector,
                    "text": returned_text,
                    "original_length": len(text),
                    "returned_length": len(
                        returned_text
                    ),
                    "truncated": was_truncated,
                },
                verification=VerificationResult(
                    verified=True,
                    method="dom_inner_text",
                    confidence=1.0,
                ),
            )

        except Exception as exc:
            return ToolResult.failure(
                "BROWSER_TEXT_READ_FAILED",
                f"Не удалось прочитать страницу: {exc}",
            )

    async def click(
        self,
        selector: str,
        *,
        timeout_ms: int = 15_000,
    ) -> ToolResult:
        selector_valid, selector_error = (
            validate_selector(selector)
        )

        if not selector_valid:
            return ToolResult.failure(
                "INVALID_SELECTOR",
                selector_error
                or "Селектор некорректен.",
            )

        start_error = await self._ensure_started()

        if start_error is not None:
            return start_error

        assert self._page is not None

        try:
            locator = self._page.locator(
                selector
            ).first

            await locator.wait_for(
                state="visible",
                timeout=timeout_ms,
            )

            element_text = ""

            try:
                element_text = (
                    await locator.inner_text(
                        timeout=2_000
                    )
                )
            except Exception:
                pass

            await locator.click(
                timeout=timeout_ms,
            )

            return ToolResult.ok(
                (
                    "Клик по элементу браузера выполнен."
                ),
                data={
                    "selector": selector,
                    "element_text": element_text,
                    "url_after_click": self._page.url,
                },
                verification=VerificationResult(
                    verified=True,
                    method="playwright_click_completed",
                    confidence=0.9,
                ),
            )

        except Exception as exc:
            return ToolResult.failure(
                "BROWSER_CLICK_FAILED",
                (
                    f"Не удалось кликнуть по "
                    f"'{selector}': {exc}"
                ),
            )

    async def fill(
        self,
        selector: str,
        text: str,
        *,
        clear_first: bool = True,
    ) -> ToolResult:
        selector_valid, selector_error = (
            validate_selector(selector)
        )

        if not selector_valid:
            return ToolResult.failure(
                "INVALID_SELECTOR",
                selector_error
                or "Селектор некорректен.",
            )

        if len(text) > MAX_INPUT_TEXT_LENGTH:
            return ToolResult.failure(
                "BROWSER_INPUT_TOO_LARGE",
                (
                    f"Текст превышает лимит "
                    f"{MAX_INPUT_TEXT_LENGTH} символов."
                ),
            )

        start_error = await self._ensure_started()

        if start_error is not None:
            return start_error

        assert self._page is not None

        try:
            locator = self._page.locator(
                selector
            ).first

            await locator.wait_for(
                state="visible",
                timeout=15_000,
            )

            if clear_first:
                await locator.fill(text)
            else:
                await locator.press_sequentially(
                    text
                )

            current_value = await locator.input_value()

            verified = current_value == text

            return ToolResult.ok(
                "Текст введён в поле браузера.",
                data={
                    "selector": selector,
                    "characters_written": len(text),
                    "value_length": len(
                        current_value
                    ),
                },
                verification=VerificationResult(
                    verified=verified,
                    method="browser_input_readback",
                    confidence=1.0
                    if verified
                    else 0.5,
                    details=(
                        "Значение поля совпадает."
                        if verified
                        else
                        "Значение поля не совпало полностью."
                    ),
                ),
            )

        except Exception as exc:
            return ToolResult.failure(
                "BROWSER_FILL_FAILED",
                (
                    f"Не удалось заполнить "
                    f"'{selector}': {exc}"
                ),
            )

    async def screenshot(
        self,
        *,
        full_page: bool = False,
    ) -> ToolResult:
        start_error = await self._ensure_started()

        if start_error is not None:
            return start_error

        assert self._page is not None

        SCREENSHOTS_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        screenshot_id = (
            f"browser_{uuid.uuid4().hex}"
        )
        screenshot_path = (
            SCREENSHOTS_DIRECTORY
            / f"{screenshot_id}.png"
        )

        try:
            await self._page.screenshot(
                path=str(screenshot_path),
                full_page=full_page,
            )

            return ToolResult.ok(
                "Снимок браузера сохранён.",
                data={
                    "path": str(
                        screenshot_path.resolve()
                    ),
                    "url": self._page.url,
                    "full_page": full_page,
                },
                artifacts=[
                    str(screenshot_path.resolve())
                ],
                verification=VerificationResult(
                    verified=(
                        screenshot_path.exists()
                    ),
                    method="filesystem_exists",
                    confidence=1.0,
                ),
            )

        except Exception as exc:
            return ToolResult.failure(
                "BROWSER_SCREENSHOT_FAILED",
                (
                    "Не удалось сделать снимок "
                    f"браузера: {exc}"
                ),
            )

    async def status(self) -> ToolResult:
        return ToolResult.ok(
            (
                "Браузерный агент работает."
                if self.is_started
                else
                "Браузерный агент не запущен."
            ),
            data={
                "started": self.is_started,
                "runtime": self._runtime,
                "persistent_profile": (
                    self._persistent_context
                ),
                "url": (
                    self._page.url
                    if self._page is not None
                    else None
                ),
            },
        )

    async def close(self) -> ToolResult:
        async with self._lock:
            await self._close_without_lock()

        return ToolResult.ok(
            "Браузерный агент остановлен."
        )

    async def _close_without_lock(self) -> None:
        persistent_context = self._persistent_context

        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                logger.exception(
                    "Ошибка закрытия browser context."
                )

        if (
            self._browser is not None
            and not persistent_context
        ):
            try:
                await self._browser.close()
            except Exception:
                logger.exception(
                    "Ошибка закрытия Chromium."
                )

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                logger.exception(
                    "Ошибка остановки Playwright."
                )

        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._runtime = None
        self._persistent_context = False
