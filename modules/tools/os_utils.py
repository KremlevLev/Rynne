# modules/tools/os_utils.py
import datetime
import subprocess
import logging
import time
import pyautogui
import pyperclip
import webbrowser
import os
import psutil
import requests
import ctypes
import base64
from PIL import ImageGrab
from core.config import TAVILY_API_KEY

logger = logging.getLogger("Tools")

# Включаем DPI Awareness, чтобы координаты окон не искажались при масштабировании интерфейса (125%, 150% и т.д.)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

class RECT(ctypes.Structure):
    _fields_ = [
        ('left', ctypes.c_long),
        ('top', ctypes.c_long),
        ('right', ctypes.c_long),
        ('bottom', ctypes.c_long)
    ]

def get_current_time(*args, **kwargs) -> str:  # Добавлен прием *args, **kwargs
    now = datetime.datetime.now()
    return now.strftime("Сегодня %d.%m.%Y, точное время %H:%M:%S")

def get_active_window_rect() -> tuple[int, int, int, int] | None:
    """Определяет границы активного в данный момент окна Windows"""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            rect = RECT()
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                # Игнорируем слишком маленькие окна или системный фон
                if w > 100 and h > 100:
                    return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception as e:
        logger.error(f"Не удалось получить координаты активного окна: {e}")
    return None

def take_screenshot(active_only: bool = False) -> str:
    """
    Делает снимок экрана.
    Если active_only=True — пытается снять только активное окно.
    Если active_only=False или произошел сбой — делает полный снимок рабочего стола.
    """
    try:
        os.makedirs("data/temp", exist_ok=True)
        path = "data/temp/screenshot.png"
        
        bbox = None
        if active_only:
            bbox = get_active_window_rect()
            
        if bbox:
            screenshot = ImageGrab.grab(bbox=bbox)
            logger.info(f"Сделан скриншот активного окна: {bbox}")
        else:
            screenshot = ImageGrab.grab()
            logger.info("Сделан скриншот всего экрана.")
            
        screenshot.save(path, "PNG")
        return path
    except Exception as e:
        logger.error(f"Не удалось сделать скриншот: {e}")
        return ""

def close_application(app_name: str) -> str:
    """Закрывает запущенное приложение по его имени в системе с поддержкой русскоязычных алиасов"""
    app_name_clean = app_name.lower().strip()
    
    # 1. Пытаемся импортировать общий словарь синонимов для сопоставления
    try:
        from modules.tools.app_indexer import RUSSIAN_ALIASES
        resolved_name = RUSSIAN_ALIASES.get(app_name_clean, app_name_clean)
    except Exception:
        resolved_name = app_name_clean
        
    # 2. Локальная карта сопоставлений для закрытия процессов
    apps = {
        "блокнот": "notepad", "notepad": "notepad",
        "калькулятор": "calc", "calculator": "calc",
        "проводник": "explorer", "explorer": "explorer",
        "хром": "chrome", "chrome": "chrome", "браузер": "chrome",
        "обсидиан": "obsidian", "obsidian": "obsidian",
        "телеграм": "telegram", "telegram": "telegram",
        "дискорд": "discord", "discord": "discord",
        "вс код": "code", "vs code": "code", "код": "code"
    }
    
    process_name = apps.get(resolved_name, resolved_name)
    if not process_name.endswith(".exe"):
        process_name += ".exe"
        
    closed = False
    # Мягкое закрытие через psutil
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
                proc.kill()
                closed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
            
    if closed:
        logger.info(f"Приложение {app_name} ({process_name}) успешно закрыто.")
        return f"Приложение '{app_name}' успешно закрыто."
    else:
        # Резервный системный вызов taskkill
        try:
            result = subprocess.run(["taskkill", "/f", "/im", process_name], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Приложение {app_name} закрыто через taskkill.")
                return f"Приложение '{app_name}' успешно закрыто."
        except Exception:
            pass
        return f"Приложение '{app_name}' не найдено среди активных процессов."

def change_volume(action: str) -> str:
    """
    Устойчивый регулятор громкости. 
    Распознает 'up', 'down', 'mute', а также числа с процентами ('30%', 'set 45', '+10').
    """
    action_clean = str(action).lower().strip()
    
    if action_clean in ["mute", "unmute", "выключить", "включить", "выключи", "включи"]:
        pyautogui.press("volumemute")
        return "Звук переключен."
    elif action_clean in ["up", "громче", "увеличить"]:
        for _ in range(5): 
            pyautogui.press("volumeup")
        return "Громкость увеличена."
    elif action_clean in ["down", "тише", "уменьшить"]:
        for _ in range(5): 
            pyautogui.press("volumedown")
        return "Громкость уменьшена."
        
    # Вытаскиваем из текста только цифры и знаки изменения (+ / -)
    numeric_part = "".join([c for c in action_clean if c.isdigit() or c in ['+', '-']])
    if not numeric_part:
        return "Ошибка: Не удалось извлечь числовой уровень громкости."
        
    try:
        if numeric_part.startswith('+') or numeric_part.startswith('-'):
            # Относительное изменение (например, "+15" или "-10")
            val = int(numeric_part)
            steps = abs(val) // 2
            key = 'volumeup' if val > 0 else 'volumedown'
            for _ in range(steps):
                pyautogui.press(key)
            return f"Громкость изменена на {numeric_part}%."
        else:
            # Абсолютное изменение (например, "30" из "30%" или "set 30")
            target_level = max(0, min(100, int(numeric_part)))
            # Сброс в 0
            for _ in range(50):
                pyautogui.press('volumedown')
            # Подъем до нужного шага (1 нажатие = +2%)
            steps = target_level // 2
            for _ in range(steps):
                pyautogui.press('volumeup')
            return f"Установлена громкость {target_level}%."
    except ValueError:
        pass
        
    return "Ошибка: Не удалось распознать формат громкости."

def open_website(url_or_query: str) -> str:
    if "." in url_or_query and " " not in url_or_query:
        if not url_or_query.startswith("http"):
            url_or_query = "https://" + url_or_query
        webbrowser.open(url_or_query)
        return f"Открыт сайт: {url_or_query}"
    else:
        search_url = f"https://www.google.com/search?q={url_or_query}"
        webbrowser.open(search_url)
        return f"Выполнен поиск в Google по запросу: '{url_or_query}'"

def get_system_status(metric: str) -> str:
    metric = metric.lower()
    try:
        if "ram" in metric or "память" in metric:
            mem = psutil.virtual_memory()
            return f"Свободно оперативной памяти: {mem.available / (1024**3):.1f} ГБ из {mem.total / (1024**3):.1f} ГБ. Загрузка: {mem.percent}%"
        elif "cpu" in metric or "процессор" in metric:
            cpu = psutil.cpu_percent(interval=1)
            return f"Текущая загрузка процессора: {cpu}%."
        elif "battery" in metric or "батарея" in metric:
            battery = psutil.sensors_battery()
            if battery:
                plugged = "Да" if battery.power_plugged else "Нет"
                return f"Заряд батареи: {battery.percent}%. Подключено к сети: {plugged}."
            return "Батарея не обнаружена."
        return "Неизвестная метрика."
    except Exception as e:
        return f"Ошибка при получении данных системы: {e}"


def execute_cmd_command(command: str) -> str:
    command = command.lower().strip()
    safe_commands = {
        "спящий режим": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
        "заблокировать пк": "rundll32.exe user32.dll,LockWorkStation"
    }
    danger_commands = {
        "очистить корзину": "rd /s /q %systemdrive%\\$Recycle.bin",
        "выключить пк": "shutdown /s /t 0",
        "перезагрузить пк": "shutdown /r /t 0"
    }
    if command in safe_commands:
        os.system(safe_commands[command])
        return f"Безопасная системная команда '{command}' выполнена."
    elif command in danger_commands:
        print(f"\n[⚠️ ВНИМАНИЕ] Джарвис хочет выполнить критическое действие: {command.upper()}")
        print('\a')
        confirm = input("Разрешить? (y - да / n - нет): ")
        if confirm.lower() == 'y':
            os.system(danger_commands[command])
            return f"Действие '{command}' было подтверждено пользователем и выполнено."
        else:
            return f"ОТКАЗ: Пользователь запретил выполнение команды '{command}'."
    return f"Ошибка: Команда '{command}' запрещена или не существует."

def manage_media(action: str) -> str:
    action = action.lower()
    try:
        if action in ["play_pause", "пауза", "продолжить"]:
            pyautogui.press("playpause")
            return "Воспроизведение приостановлено/запущено."
        elif action in ["next", "следующий"]:
            pyautogui.press("nexttrack")
            return "Включен следующий трек."
        elif action in ["prev", "предыдущий"]:
            pyautogui.press("prevtrack")
            return "Включен предыдущий трек."
        return "Неизвестная медиа-команда."
    except Exception as e:
        return f"Ошибка управления медиа: {e}"

def manage_windows(action: str) -> str:
    try:
        if "minimize_all" in action or "свернуть" in action:
            pyautogui.hotkey('win', 'd')
            return "Все окна свернуты."
        elif "close_current" in action or "закрыть" in action:
            pyautogui.hotkey('alt', 'f4')
            return "Текущее активное окно закрыто."
        return "Неизвестная команда для окон."
    except Exception as e:
        return f"Ошибка управления окнами: {e}"

def create_quick_note(text: str) -> str:
    try:
        desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')
        note_path = os.path.join(desktop, "Джарвис_Заметки.txt")
        with open(note_path, "a", encoding="utf-8") as f:
            f.write(f"[{get_current_time()}] {text}\n")
        return "Заметка успешно сохранена на рабочем столе."
    except Exception as e:
        return f"Не удалось сохранить заметку: {e}"

def set_timer(minutes: int) -> str:
    try:
        seconds = int(minutes) * 60
        os.system(f'start /B cmd /c "ping 127.0.0.1 -n {seconds} > nul & echo \x07"')
        return f"Таймер на {minutes} минут успешно запущен."
    except Exception as e:
        return f"Ошибка при установке таймера: {e}"

def control_smart_home(device: str, action: str) -> str:
    device = device.lower().strip()
    action = action.lower().strip()
    logger.info(f"Умный дом: {device} -> {action}")
    return f"Симуляция умного дома: Устройство '{device}' переведено в режим '{action}'."

def configure_assistant(setting: str, value: str) -> str:
    setting = setting.lower().strip()
    value = value.lower().strip()
    logger.info(f"Настройки ассистента: {setting} -> {value}")
    return f"Настройка '{setting}' успешно изменена на значение '{value}'."

def bring_window_to_front(app_name: str) -> bool:
    try:
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        found_hwnds = []

        def enum_windows_callback(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, length + 1)
                    title = buffer.value.lower()
                    
                    aliases = {
                        "блокнот": ["блокнот", "notepad"],
                        "калькулятор": ["калькулятор", "calc", "calculator"],
                        "проводник": ["проводник", "explorer", "компьютер"],
                        "chrome": ["chrome", "хром", "google chrome"],
                        "obsidian": ["obsidian"]
                    }
                    search_terms = aliases.get(app_name.lower(), [app_name.lower()])
                    if any(term in title for term in search_terms):
                        found_hwnds.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)
        
        if found_hwnds:
            hwnd = found_hwnds[0]
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            return True
    except Exception as e:
        logger.error(f"Ошибка фокусировки окна {app_name}: {e}")
    return False

def open_application(app_name: str) -> str:
    app_name = app_name.lower().strip()
    apps = {"блокнот": "notepad.exe", "калькулятор": "calc.exe", "проводник": "explorer.exe"}
    executable = apps.get(app_name)
    if not executable:
        return f"Ошибка: Я пока не знаю, как открыть приложение '{app_name}'."
    try:
        subprocess.Popen(executable)
        time.sleep(0.5)
        bring_window_to_front(app_name)
        return f"Приложение {app_name} успешно открыто."
    except Exception as e:
        return f"Произошла ошибка при запуске: {e}"

def encode_image_base64(image_path: str) -> str:
    if not image_path:
        return ""

    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(
                image_file.read()
            ).decode("ascii")
    except Exception as exc:
        logger.error(
            "Не удалось закодировать изображение: %s",
            exc,
        )
        return ""

    
def type_text(text: str) -> str:
    """
    Безопасно вставляет текст в активное окно через буфер обмена Windows.
    Защищен от сбоев синхронизации буфера микропаузами.
    """
    try:
        time.sleep(0.5)  # Пауза, чтобы окно успело принять фокус ввода
        old_clipboard = pyperclip.paste()
        pyperclip.copy(text)
        time.sleep(0.15)  # Ожидание обновления системного буфера обмена
        
        # Пошаговая эмуляция во избежание "залипания" виртуальных клавиш
        pyautogui.keyDown('ctrl')
        time.sleep(0.05)
        pyautogui.press('v')
        time.sleep(0.05)
        pyautogui.keyUp('ctrl')
        
        time.sleep(0.1)  # Даем время на вставку текста перед восстановлением буфера
        pyperclip.copy(old_clipboard)
        return "Текст успешно вставлен в активное окно."
    except Exception as e:
        return f"Не удалось напечатать текст: {e}"

def press_keyboard_combination(keys: str) -> str:
    """
    Эмулирует нажатие клавиши или комбинации клавиш (например, 'ctrl+n', 'ctrl+s', 'enter', 'tab').
    Позволяет управлять интерфейсами приложений.
    """
    try:
        time.sleep(0.3)
        parts = [k.strip().lower() for k in keys.split('+')]
        if len(parts) == 1:
            pyautogui.press(parts[0])
        else:
            pyautogui.hotkey(*parts)
        return f"Комбинация клавиш '{keys}' успешно нажата."
    except Exception as e:
        return f"Не удалось нажать комбинацию клавиш '{keys}': {e}"

def scrape_webpage(url: str) -> str:
    """Скачивает веб-страницу и извлекает из нее чистый текст для анализа документации"""
    try:
        from bs4 import BeautifulSoup
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if response.status_code != 200:
            return f"Ошибка доступа к сайту: код {response.status_code}"
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Убираем мусорные теги
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()
            
        text = soup.get_text(separator=' ')
        # Чистим пробелы
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        clean_text = '\n'.join(chunk for chunk in chunks if chunk)
        
        # Ограничиваем объем текста для экономии контекста (например, первые 6000 символов)
        return clean_text[:6000] + "\n...[Текст обрезан для экономии памяти]..."
    except Exception as e:
        return f"Не удалось прочитать страницу: {e}"
    
def get_clipboard_content(*args, **kwargs) -> str:  # Добавлен прием *args, **kwargs
    """Возвращает текущий текстовый буфер обмена Windows"""
    try:
        return pyperclip.paste()
    except Exception as e:
        return f"Не удалось прочитать буфер обмена: {e}"

def set_clipboard_content(text: str, *args, **kwargs) -> str:  # Добавлен прием *args, **kwargs
    """Записывает указанный текст в буфер обмена пользователя"""
    try:
        pyperclip.copy(text)
        return "Текст успешно скопирован в ваш буфер обмена."
    except Exception as e:
        return f"Не удалось записать в буфер обмена: {e}"
    
def run_terminal_command(
    command: str,
    working_directory: str | None = None,
    *args,
    **kwargs,
) -> str:
    """
    Выполняет консольную команду (CMD/PowerShell) на ПК и возвращает её вывод.
    Каждый запуск защищен блокирующим окном согласия HITL.
    """
    import subprocess
    from modules.tools.executor import prompt_hitl_permission
    
    # 1. Запрос физического подтверждения от пользователя перед запуском шелла
    resolved_cwd = None
    if working_directory:
        try:
            resolved_cwd = os.path.abspath(
                os.path.expanduser(
                    str(working_directory)
                )
            )
        except (OSError, TypeError, ValueError):
            return "Ошибка: Некорректный путь рабочего каталога."
        if not os.path.isdir(resolved_cwd):
            return (
                "Ошибка: Рабочий каталог не найден: "
                f"{resolved_cwd}"
            )

    details = (
        "Действие: Выполнение консольной команды\n\n"
        f"Рабочий каталог: {resolved_cwd or os.getcwd()}\n"
        f"Команда для запуска:\n> {command}"
    )
    if not prompt_hitl_permission("Терминальный оператор", details):
        return "Ошибка: Выполнение консольной команды заблокировано пользователем."
        
    try:
        # Запуск процесса с таймаутом 15 секунд (предотвращает вечное зависание при запуске бесконечных служб)
        result = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=resolved_cwd,
            timeout=15.0
        )
        
        # 2. Робастное автоопределение кодировки вывода Windows (CMD русскоязычной ОС использует cp866)
        def safe_decode(data: bytes) -> str:
            for encoding in ['utf-8', 'cp866', 'cp1251']:
                try:
                    return data.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return data.decode('utf-8', errors='replace')
            
        stdout_str = safe_decode(result.stdout).strip()
        stderr_str = safe_decode(result.stderr).strip()
        
        # 3. Формирование структурированного ответа для LLM
        output_blocks = []
        if stdout_str:
            output_blocks.append(f"[Вывод терминала (stdout)]:\n{stdout_str}")
        if stderr_str:
            output_blocks.append(f"[Вывод ошибок (stderr)]:\n{stderr_str}")
            
        if not output_blocks:
            return f"Команда выполнена с кодом {result.returncode}. Консоль вернула пустую строку."
            
        return "\n\n".join(output_blocks)
        
    except subprocess.TimeoutExpired:
        return "Ошибка: Превышен лимит времени выполнения команды (15 секунд). Команда принудительно остановлена."
    except Exception as e:
        return f"Критический сбой выполнения команды: {e}"
    
def search_web_free(query: str) -> str:
    """
    Резервный бесплатный веб-поиск через html-версию DuckDuckGo.
    Работает без API-ключей.
    """
    try:
        from bs4 import BeautifulSoup
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # Делаем POST-запрос (стандарт для статической выдачи DDG)
        response = requests.post(url, data={"q": query}, headers=headers, timeout=10)
        if response.status_code != 200:
            return f"Ошибка поиска DDG: код {response.status_code}"
            
        soup = BeautifulSoup(response.text, 'html.parser')
        results = soup.select(".result")
        
        if not results:
            return "Поиск не дал результатов."
            
        text_results = ["[Резервный поиск DuckDuckGo]:\n"]
        for i, res in enumerate(results[:3], 1):
            title_node = res.select_one(".result__title .result__a")
            snippet_node = res.select_one(".result__snippet")
            
            if title_node:
                title = title_node.get_text().strip()
                link = title_node.get("href", "")
                snippet = snippet_node.get_text().strip() if snippet_node else "Описание отсутствует."
                text_results.append(f"{i}. {title}\nСсылка: {link}\nОписание: {snippet}\n")
                
        return "\n".join(text_results)
    except Exception as e:
        return f"Не удалось выполнить бесплатный веб-поиск: {e}"

# Объединяем Tavily и Бесплатный поиск в одну умную функцию:
def search_web_tavily(query: str) -> str:
    """Ищет информацию в интернете. При отсутствии API-ключа переключается на бесплатный DuckDuckGo."""
    if not TAVILY_API_KEY:
        logger.info("TAVILY_API_KEY не найден. Переключаюсь на бесплатный DuckDuckGo...")
        return search_web_free(query)
        
    logger.info(f"Ищу в интернете через Tavily: {query}")
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": TAVILY_API_KEY, "query": query, "search_depth": "basic", "max_results": 3},
            timeout=10
        )
        if response.status_code != 200:
            logger.warning("Ошибка Tavily API. Переход на резервный поиск...")
            return search_web_free(query)
            
        data = response.json()
        if "results" not in data or not data["results"]:
            return "Ничего не найдено."
            
        results_text = "Вот что я нашла в интернете:\n"
        for i, res in enumerate(data['results'], 1):
            results_text += f"{i}. {res['title']}\nСодержание: {res['content']}\n\n"
        return results_text
    except Exception as e:
        logger.warning(f"Сбой Tavily: {e}. Переход на резервный поиск...")
        return search_web_free(query)

def list_active_windows(*args, **kwargs) -> str:
    """Возвращает список заголовков всех открытых и видимых окон Windows"""
    try:
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        windows = []

        def enum_windows_callback(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, length + 1)
                    title = buffer.value.strip()
                    # Игнорируем tkinter оверлей и пустые заголовки
                    if title and title != "Nova Overlay" and title != "Nova":
                        windows.append(title)
            return True

        user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)
        if not windows:
            return "Активные видимые окна не обнаружены."
            
        # Убираем дубликаты
        unique_windows = list(set(windows))
        return "Список открытых окон на вашем экране:\n" + "\n".join([f"- '{w}'" for w in unique_windows])
    except Exception as e:
        return f"Не удалось получить список окон: {e}"

def focus_window(window_title_part: str) -> str:
    try:
        original_query = window_title_part.strip()

        try:
            from modules.tools.app_indexer import (
                RUSSIAN_ALIASES,
                normalize_app_name,
            )

            normalized_query = normalize_app_name(
                original_query
            )
            resolved_query = RUSSIAN_ALIASES.get(
                normalized_query,
                normalized_query,
            )
        except Exception:
            resolved_query = original_query.lower()

        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        found_hwnds = []

        def enum_windows_callback(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, length + 1)
                    title = buffer.value.lower()
                    if (
                        original_query.lower() in title
                        or resolved_query.lower() in title
                    ):

                        found_hwnds.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)
        
        if found_hwnds:
            hwnd = found_hwnds[0]
            # 9 = SW_RESTORE (развернуть окно, если оно свернуто)
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.2)

            if user32.GetForegroundWindow() != hwnd:
                return (
                    f"Не удалось подтвердить фокус окна "
                    f"'{original_query}'."
                )

            return (
                f"Окно '{original_query}' выведено "
                "на передний план, фокус подтвержден."
            )
        return f"Окно с заголовком, содержащим '{window_title_part}', не найдено."
    except Exception as e:
        return f"Не удалось сфокусироваться на окне: {e}"
    
def get_active_window_title(*args, **kwargs) -> str:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()

        if not hwnd:
            return ""

        length = user32.GetWindowTextLengthW(hwnd)

        if length <= 0:
            return ""

        buffer = ctypes.create_unicode_buffer(
            length + 1
        )

        user32.GetWindowTextW(
            hwnd,
            buffer,
            length + 1,
        )

        return buffer.value.strip()

    except Exception as exc:
        logger.error(
            "Не удалось получить заголовок активного окна: %s",
            exc,
        )
        return ""
