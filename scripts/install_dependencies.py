# scripts/install_dependencies.py
"""
Проверка и установка зависимостей Nova.

Использование:
    python scripts/install_dependencies.py
"""

import os
import sys
import subprocess
import urllib.request
import zipfile

REQUIREMENTS = [
    "openai",
    "packaging",
    "python-dotenv",
    "requests",
    "beautifulsoup4",
    "sounddevice",
    "numpy",
    "psutil",
    "pyautogui",
    "pyperclip",
    "keyboard",
    "pillow",
    "playwright",
    "PySide6",
]

OPTIONAL_REQUIREMENTS = {
    "torch": (
        "torch",
        [
            "--index-url",
            "https://download.pytorch.org/whl/cpu",
        ],
    ),
    "winrt": ("winrt", []),
    "uiautomation": ("uiautomation", []),
}


def install(
    package: str,
    *,
    extra_args: list[str] | None = None,
) -> bool:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        package,
    ]

    if extra_args:
        command.extend(extra_args)

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(
            f"  Ошибка установки {package}: "
            f"{result.stderr.strip()}"
        )
        return False

    print(f"  {package} установлен.")
    return True


# ==============================================================================
# Silero TTS Model Installation
# ==============================================================================

SILERO_MODEL_PATH = "data/v5_ru.pt"


def install_silero_model() -> None:
    """Download and install Silero TTS Russian voice model."""
    print("\n=== Установка голосового движка Silero TTS ===")
    
    # Check if torch is available
    try:
        import torch
    except ImportError:
        print("  Ошибка: Библиотека 'torch' не найдена. Сначала выполните: pip install -r requirements.txt")
        return
    
    os.makedirs(os.path.dirname(SILERO_MODEL_PATH), exist_ok=True)
    
    if not os.path.exists(SILERO_MODEL_PATH):
        print(f"  Файл {SILERO_MODEL_PATH} не найден. Начинаю скачивание модели Silero v5_ru...")
        try:
            torch.hub.download_url_to_file(
                'https://models.silero.ai/models/tts/ru/v5_ru.pt',
                SILERO_MODEL_PATH
            )
            print("  Загрузка успешно завершена.")
        except Exception as e:
            print(f"  Критическая ошибка при скачивании модели: {e}")
            return
    else:
        print("  Модель Silero v5 уже присутствует в локальной папке.")
    
    print("\n  Выполняю первый тестовый прогрев модели...")
    try:
        torch.set_num_threads(4)
        model = torch.package.PackageImporter(SILERO_MODEL_PATH).load_pickle("tts_models", "model")
        model.to(torch.device('cpu'))
        print("  Проверка инициализации пройдена! Голосовой движок готов к работе.")
    except Exception as e:
        print(f"  Ошибка при инициализации модели: {e}")


# ==============================================================================
# Vosk STT Model Installation
# ==============================================================================

VOSK_MODEL_NAME = "vosk-model-small-ru-0.22"
VOSK_MODEL_URL = f"https://alphacephei.com/vosk/models/{VOSK_MODEL_NAME}.zip"
VOSK_MODEL_DIR = "data/vosk"


def progress_callback(block_num, block_size, total_size):
    """Отображает прогресс скачивания в консоли."""
    downloaded = block_num * block_size
    if total_size > 0:
        percent = min(100, downloaded * 100 / total_size)
        print(f"\r  Скачивание: {percent:.1f}% ({downloaded / (1024*1024):.2f} MB из {total_size / (1024*1024):.2f} MB)", end="")
    else:
        print(f"\r  Скачано: {downloaded / (1024*1024):.2f} MB", end="")


def install_vosk_model() -> None:
    """Download and install Vosk Russian speech recognition model."""
    print("\n=== Установка модели распознавания речи Vosk ===")
    
    # Get base directory (where this script is located)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up one level to project root
    project_root = os.path.dirname(base_dir)
    
    target_dir = os.path.join(project_root, VOSK_MODEL_DIR)
    zip_path = os.path.join(target_dir, f"{VOSK_MODEL_NAME}.zip")
    
    print(f"  Целевая папка на компьютере:\n  --> {os.path.abspath(target_dir)}\n")
    
    # Check if model already exists
    extracted_folder = os.path.join(target_dir, VOSK_MODEL_NAME)
    if os.path.exists(extracted_folder):
        print("  Модель Vosk уже присутствует в локальной папке.")
        return
    
    # Create directory structure
    os.makedirs(target_dir, exist_ok=True)
    
    # Download archive
    print(f"  Начало скачивания модели {VOSK_MODEL_NAME}...")
    try:
        urllib.request.urlretrieve(VOSK_MODEL_URL, zip_path, reporthook=progress_callback)
        print("\n  Скачивание завершено.")
    except Exception as e:
        print(f"\n  Не удалось скачать модель. Ошибка: {e}")
        return
    
    # Extract archive
    print("  Распаковка архива...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(target_dir)
        print("  Архив успешно распакован.")
    except Exception as e:
        print(f"  Не удалось распаковать архив. Ошибка: {e}")
        return
    finally:
        # Remove temporary zip file
        if os.path.exists(zip_path):
            os.remove(zip_path)
            print("  Временный zip-файл удален.")


def main() -> None:
    print("=== Установка зависимостей Nova ===\n")

    print("Основные зависимости:")
    for package in REQUIREMENTS:
        install(package)

    print("\nОпциональные зависимости:")
    for name, (
        package,
        extra_args,
    ) in OPTIONAL_REQUIREMENTS.items():
        print(f"  {name} ({package})...")
        install(
            package,
            extra_args=extra_args,
        )

    print("\nУстановка Playwright Chromium...")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "playwright",
            "install",
            "chromium",
        ],
    )

    # Install Silero TTS model
    install_silero_model()

    # Install Vosk STT model
    install_vosk_model()

    print("\n=== Установка завершена ===")


if __name__ == "__main__":
    main()
