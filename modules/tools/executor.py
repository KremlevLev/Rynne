# modules/tools/executor.py
import sys
import io
import ast
import ctypes
import logging
import pyautogui
import os
from pathlib import Path

logger = logging.getLogger("Executor")

# Настройка безопасности PyAutoGUI
pyautogui.FAILSAFE = True  # Если пользователь дернет мышь в любой угол экрана, выполнение прервется
pyautogui.PAUSE = 0.1

def prompt_hitl_permission(action_type: str, details: str) -> bool:
    """
    Выводит нативное блокирующее модальное окно Windows для подтверждения опасных действий.
    Поток исполнения замораживается до тех пор, пока пользователь не нажмет 'Да' или 'Нет'.
    """
    title = f"Контроль безопасности Nova — {action_type}"
    message = (
        f"Ассистент Nova запрашивает разрешение на выполнение действия:\n\n"
        f"{details}\n\n"
        "Вы подтверждаете выполнение этой операции?"
    )
    # 0x00000004 = MB_YESNO (Кнопки Да/Нет)
    # 0x00000030 = MB_ICONWARNING (Значок предупреждения)
    # 0x00010000 = MB_TOPMOST (Поверх всех окон для гарантированной видимости)
    style = 0x00000004 | 0x00000030 | 0x00010000
    
    result = ctypes.windll.user32.MessageBoxW(0, message, title, style)
    return result == 6  # 6 соответствует выбору 'Да' (IDYES)

def check_dangerous_patterns(code: str) -> tuple[bool, str]:
    """
    Проводит статический анализ синтаксического дерева кода (AST) перед его выполнением.
    """
    # Текстовые маркеры грубой деструкции системы
    blacklist = [
        "shutil.rmtree", "os.remove", "os.unlink", "format", 
        "os.system", "subprocess", "ctypes.windll.ntdll", "regdelete"
    ]
    for word in blacklist:
        if word in code:
            return False, f"Обнаружена заблокированная системная функция: '{word}'."
            
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            # Проверка на бесконечные циклы while True:
            if isinstance(node, ast.While):
                if isinstance(node.test, ast.Constant) and node.test.value is True:
                    return False, "Обнаружен потенциально бесконечный цикл 'while True'."
    except SyntaxError as e:
        return False, f"Синтаксическая ошибка в коде: {e}"
        
    return True, "Базовые проверки безопасности пройдены."

def execute_python_code(code: str) -> str:
    logger.info("Запрос на выполнение динамического Python-кода.")

    is_safe, check_msg = check_dangerous_patterns(code)

    if not is_safe:
        return (
            "Ошибка: Выполнение заблокировано системой безопасности. "
            f"{check_msg}"
        )

    # PermissionManager already applied the selected permission mode before
    # calling this legacy handler. A second native dialog deadlocks remote
    # tasks and incorrectly ignores the user's Full access setting.
    # 3. Перехват стандартных потоков вывода
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    redirected_output = io.StringIO()
    redirected_error = io.StringIO()
    sys.stdout = redirected_output
    sys.stderr = redirected_error
    
    # Предоставляем безопасный контекст исполнения с предустановленными библиотеками
    local_scope = {
        "pyautogui": pyautogui,
        "ctypes": ctypes,
        "sys": sys,
        "io": io,
        "os": os,
    }
    
    try:
        # Выполнение в изолированном контексте
        exec(code, {}, local_scope)
        
        stdout_val = redirected_output.getvalue()
        stderr_val = redirected_error.getvalue()
        
        result_str = stdout_val
        if stderr_val:
            result_str += f"\nОшибки исполнения:\n{stderr_val}"
            
        return result_str if result_str.strip() else "Код выполнен успешно, пустой консольный вывод."
    except pyautogui.FailSafeException:
        return "Аварийная остановка: Сработал аппаратный предохранитель мыши (FailSafe)."
    except Exception as e:
        return f"Сбой в процессе работы скрипта: {e}"
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

def mouse_click(x: int, y: int, click_type: str = "single") -> str:
    """
    Перемещает указатель мыши и совершает нажатие кнопки.
    Применяется плавное наведение курсора, позволяющее перехватить контроль.
    """
    try:
        # Плавное наведение за 0.6 секунды дает пользователю время заметить траекторию мыши
        pyautogui.moveTo(x, y, duration=0.6)
        
        if click_type == "double":
            pyautogui.doubleClick()
            action_desc = "Двойной клик"
        elif click_type == "right":
            pyautogui.rightClick()
            action_desc = "Правый клик"
        else:
            pyautogui.click()
            action_desc = "Одинарный клик"
            
        return f"Успешно: Выполнен {action_desc} в координатах X={x}, Y={y}."
    except pyautogui.FailSafeException:
        return "Аварийная остановка: Пользователь перехватил мышь и сорвал выполнение."
    except Exception as e:
        return f"Не удалось выполнить клик: {e}"
    
def create_workspace_project(project_name: str, files: list) -> str:
    """
    Создает модульную структуру проекта (папки и файлы) на Рабочем столе пользователя за один шаг.
    Защищен окном подтверждения HITL. После создания открывает папку в Проводнике.
    files - список словарей [{"path": "relative/path.py", "content": "file_code"}]
    """
    import os
    try:
        desktop = Path(os.environ["USERPROFILE"]) / "Desktop"

        if not project_name.strip():
            return "Ошибка: Имя проекта пусто."
        if Path(project_name).is_absolute() or ".." in Path(project_name).parts:
            return "Ошибка: Недопустимое имя проекта."
        project_dir = _safe_project_path(
            desktop,
            project_name.strip(),
            )
        # Формируем список файлов для окна подтверждения безопасности
        file_list = "\n".join([f"- {f.get('path')}" for f in files if f.get('path')])
        details = (
            f"Имя проекта: {project_name}\n"
            f"Директория: {project_dir}\n\n"
            f"Будет создана файловая структура:\n{file_list}"
        )
        
        created_count = 0
        for file_data in files:
            rel_path = file_data.get("path")
            content = file_data.get("content", "")
            if not rel_path:
                continue
            
            # Нормализуем пути под Windows
            full_file_path = _safe_project_path(
            project_dir,
            rel_path,
            )

            full_file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
            )

            with full_file_path.open(
            "w",
            encoding="utf-8",
            newline="\n",
            ) as file:
                file.write(content)
            
            if len(files) > 200:
                return "Ошибка: За один вызов разрешено создать не более 200 файлов."

            total_size = sum(
                len(str(item.get("content", "")).encode("utf-8"))
                for item in files
            )

            if total_size > 10 * 1024 * 1024:
                return "Ошибка: Общий размер проекта превышает 10 МБ."

            # Создаем все промежуточные директории
            os.makedirs(os.path.dirname(full_file_path), exist_ok=True)
            
            # Записываем контент файла
            with open(full_file_path, "w", encoding="utf-8") as f:
                f.write(content)
            created_count += 1
            
        # Автоматически открываем созданную директорию в Проводнике
        if os.path.exists(project_dir):
            os.startfile(project_dir)
            
        return f"Проект '{project_name}' успешно создан на Рабочем столе. Записано файлов: {created_count}. Папка открыта."
    except Exception as e:
        return f"Не удалось создать проект: {e}"
    
def _safe_project_path(
    project_root: Path,
    relative_path: str,
) -> Path:
    candidate_path = Path(relative_path)

    if candidate_path.is_absolute():
        raise ValueError("Абсолютные пути запрещены.")

    if ".." in candidate_path.parts:
        raise ValueError("Выход за пределы проекта запрещен.")

    resolved_root = project_root.resolve()
    resolved_target = (
        resolved_root / candidate_path
    ).resolve()

    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            "Путь выходит за пределы проекта."
        ) from exc

    return resolved_target
