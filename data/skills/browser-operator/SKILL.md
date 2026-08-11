---
name: Browser Operator
description: Доводит браузерные задачи до проверенного результата
triggers: [браузер, сайт, страница, openrouter, личный кабинет, активность]
tools: [browser_start, browser_open_url, browser_get_page_text, browser_click, browser_fill, browser_screenshot, browser_status, open_url_in_browser, list_active_windows, focus_window, press_keyboard_combination, type_text, get_ui_tree, find_ui_element, ocr_screen, click_text]
---
Если задача включает вход, регистрацию, Google/Microsoft OAuth, личный кабинет или
данные уже авторизованного аккаунта, используй обычный Google Chrome пользователя:
`open_url_in_browser(app_name="google chrome", url=...)`. Не переходи после этого
в Playwright/browser_*: это другой профиль без пользовательской авторизации.
Продолжай в том же окне Chrome через UIA/OCR/клавиатуру и проверяй смену экрана.

CAPTCHA, anti-bot challenge, пароль, passkey и 2FA не обходи. Остановись на этом
экране, коротко попроси пользователя закончить приватный шаг и после подтверждения
продолжи исходную задачу с текущего места.

Сначала открой прямой официальный URL в постоянном профиле Rynne. После навигации
прочитай видимое содержимое страницы и сопоставь его со всей целью пользователя.
Запуск браузера сам по себе не является результатом. Если требуется авторизация,
попроси пользователя войти в открытом окне и затем продолжи. Для личных данных не
используй поисковую выдачу. Если пользователь просит показать или проверить итог,
прочитай страницу либо сделай screenshot и только после этого заверши задачу.
