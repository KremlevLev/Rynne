# modules/tools/registry.py

open_app_tool = {"type": "function", "function": {"name": "open_application", "description": "Открывает программу (блокнот, калькулятор, проводник).", "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]}}}
open_app_batch_tool = {
    "type": "function",
    "function": {
        "name": "open_application_batch",
        "description": (
            "Открывает ограниченное количество разных обычных приложений. "
            "Используется для запросов вроде «запусти 5 приложений»."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 10,
                },
            },
            "required": ["count"],
        },
    },
}
close_app_tool = {"type": "function", "function": {"name": "close_application", "description": "Закрывает запущенную программу (блокнот, калькулятор, проводник, хром) по названию.", "parameters": {"type": "object", "properties": {"app_name": {"type": "string", "description": "Название закрываемого приложения (блокнот, калькулятор, проводник, хром)."}}, "required": ["app_name"]}}}
type_text_tool = {"type": "function", "function": {"name": "type_text", "description": "Печатает текст в активное окно.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}
get_time_tool = {"type": "function", "function": {"name": "get_current_time", "description": "Возвращает текущую дату и время.", "parameters": {"type": "object", "properties": {}}}}
change_volume_tool = {"type": "function", "function": {"name": "change_volume", "description": "Изменяет громкость системы.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "'up', 'down' или 'mute'"}}, "required": ["action"]}}}
open_website_tool = {"type": "function", "function": {"name": "open_website", "description": "Просто открывает веб-сайт в браузере.", "parameters": {"type": "object", "properties": {"url_or_query": {"type": "string"}}, "required": ["url_or_query"]}}}
get_system_status_tool = {"type": "function", "function": {"name": "get_system_status", "description": "Возвращает инфу о ПК: 'ram', 'cpu' или 'battery'.", "parameters": {"type": "object", "properties": {"metric": {"type": "string"}}, "required": ["metric"]}}}
search_web_tavily_tool = {"type": "function", "function": {"name": "search_web_tavily", "description": "Ищет информацию в интернете.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
execute_cmd_tool = {"type": "function", "function": {"name": "execute_cmd_command", "description": "Выполняет системные команды: 'очистить корзину', 'спящий режим', 'выключить пк'.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}

manage_media_tool = {"type": "function", "function": {"name": "manage_media", "description": "Управление музыкой и видео.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "'play_pause', 'next', 'prev'"}}, "required": ["action"]}}}
manage_windows_tool = {"type": "function", "function": {"name": "manage_windows", "description": "Управление окнами Windows.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "'minimize_all' или 'close_current'"}}, "required": ["action"]}}}
create_note_tool = {"type": "function", "function": {"name": "create_quick_note", "description": "Сохраняет текст/идею/напоминание в текстовый файл на рабочем столе.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}
set_timer_tool = {"type": "function", "function": {"name": "set_timer", "description": "Устанавливает таймер на заданное количество минут.", "parameters": {"type": "object", "minutes": {"type": "integer","minimum": 1,"maximum": 10080, "required": ["minutes"]}}}}

control_smart_home_tool = {
    "type": "function",
    "function": {
        "name": "control_smart_home",
        "description": "Управление устройствами умного дома (свет, кондиционер, чайник и др.).",
        "parameters": {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "Название устройства (например, свет, кондей, чайник)."},
                "action": {"type": "string", "description": "Действие (например, включить, выключить, 22 градуса, максимум)."}
            },
            "required": ["device", "action"]
        }
    }
}

configure_assistant_tool = {
    "type": "function",
    "function": {
        "name": "configure_assistant",
        "description": "Изменение конфигурации или голоса ассистента (язык, скорость, тон).",
        "parameters": {
            "type": "object",
            "properties": {
                "setting": {"type": "string", "description": "Название настройки (например, голос, язык, скорость)."},
                "value": {"type": "string", "description": "Новое значение (например, мужской, английский, помедленнее)."}
            },
            "required": ["setting", "value"]
        }
    }
}

save_memory_tool = {
    "type": "function",
    "function": {
        "name": "save_to_memory",
        "description": "Запоминает важную информацию о пользователе (имена, предпочтения, факты), чтобы использовать в будущем.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Факт или информация для сохранения (например: 'Пользователь любит синий цвет')."}
            },
            "required": ["text"]
        }
    }
}

search_memory_tool = {
    "type": "function",
    "function": {
        "name": "search_in_memory",
        "description": "Ищет в долговременной памяти Nova информацию о пользователе по запросу.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос для извлечения фактов."}
            },
            "required": ["query"]
        }
    }
}

add_reminder_tool = {
    "type": "function",
    "function": {
        "name": "set_reminder",
        "description": "Устанавливает напоминание или будильник на определенное время или интервал.",
        "parameters": {
            "type": "object",
            "properties": {
                "time_str": {"type": "string", "description": "Время в формате '+минуты' (например '+15' для 15 минут) или в формате 'ЧЧ:ММ' (например '18:00')."},
                "message": {"type": "string", "description": "Текст напоминания (например: 'купить хлеб')."}
            },
            "required": ["time_str", "message"]
        }
    }
}

list_reminders_tool = {
    "type": "function",
    "function": {
        "name": "get_active_reminders",
        "description": "Возвращает список всех активных на данный момент напоминаний.",
        "parameters": {"type": "object", "properties": {}}
    }
}

execute_python_tool = {
    "type": "function",
    "function": {
        "name": "execute_python_code",
        "description": "Запускает произвольный Python-код (REPL). Позволяет совершать сложные математические расчеты, работу с файлами, автоматизацию интерфейса через pyautogui и глубокое взаимодействие с ОС. Требует подтверждения пользователя.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Полный исполняемый код Python для запуска."}
            },
            "required": ["code"]
        }
    }
}

mouse_click_tool = {
    "type": "function",
    "function": {
        "name": "mouse_click",
        "description": "Перемещает курсор мыши на координаты X, Y и совершает клик. Используется для точного нажатия кнопок на экране.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "minimum": -20000,
                    "maximum": 20000
                },
                "y": {
                    "type": "integer",
                    "minimum": -20000,
                    "maximum": 20000
                },
                "click_type": {"type": "string", "enum": ["single", "double", "right"], "description": "Тип нажатия (single - обычный, double - двойной, right - правый)."}
            },
            "required": ["x", "y"]
        }
    }
}

press_hotkey_tool = {
    "type": "function",
    "function": {
        "name": "press_keyboard_combination",
        "description": "Нажимает заданную комбинацию клавиш (например, 'ctrl+n' для создания нового файла, 'ctrl+s' для сохранения, 'enter' для подтверждения, 'tab'). Используйте перед вводом текста в редакторы, чтобы создать документ.",
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {"type": "string", "description": "Комбинация клавиш в нижнем регистре через знак плюс, например: 'ctrl+n' или 'enter'"}
            },
            "required": ["keys"]
        }
    }
}

create_project_tool = {
    "type": "function",
    "function": {
        "name": "create_workspace_project",
        "description": "Создает полноценную модульную структуру проекта (папки и файлы) на Рабочем столе за один шаг. Используйте этот инструмент, когда пользователь просит написать сложную программу, модульный код, развернуть инфраструктуру или бэкенд.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100
                },
                "files": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 200,
                },
                "content": {
                    "type": "string",
                    "maxLength": 500000,
                }

            },
            "required": ["project_name", "files"]
        }
    }
}

write_in_application_tool = {
    "type": "function",
    "function": {
        "name": "write_in_application",
        "description": (
            "Открывает или активирует указанное приложение, "
            "при необходимости создает новый документ и вводит "
            "готовый текст. Используйте вместо ручной цепочки "
            "open_application, focus_window, ctrl+n и type_text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": (
                        "Название приложения, например Obsidian, "
                        "блокнот или Visual Studio Code."
                    ),
                },
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100000,
                    "description": (
                        "Полный текст, который нужно ввести."
                    ),
                },
                "create_new_document": {
                    "type": "boolean",
                    "description": (
                        "Создать новый документ сочетанием ctrl+n "
                        "перед вводом текста."
                    ),
                },
            },
            "required": [
                "app_name",
                "text",
            ],
            "additionalProperties": False,
        },
    },
}

scrape_webpage_tool = {
    "type": "function",
    "function": {
        "name": "scrape_webpage",
        "description": "Загружает веб-страницу по URL и извлекает из неё чистый текст. Используйте для подробного чтения статей, руководств и документации из интернета.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Полный адрес страницы, например: 'https://docs.pytest.org/'"}
            },
            "required": ["url"]
        }
    }
}

get_clipboard_tool = {
    "type": "function",
    "function": {
        "name": "get_clipboard_content",
        "description": "Возвращает текущий скопированный пользователем текст из буфера обмена Windows. Используйте, чтобы проанализировать логи ошибок или куски кода, скопированные пользователем.",
        "parameters": {"type": "object", "properties": {}}
    }
}

set_clipboard_tool = {
    "type": "function",
    "function": {
        "name": "set_clipboard_content",
        "description": "Копирует указанный текст в буфер обмена Windows пользователя.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Текст, который нужно положить в буфер обмена."}
            },
            "required": ["text"]
        }
    }
}

run_terminal_tool = {
    "type": "function",
    "function": {
        "name": "run_terminal_command",
        "description": "Выполняет консольную команду (CMD) в системе Windows в скрытом фоновом режиме и возвращает текстовый ответ. Позволяет проверять статус Git, запускать тесты, устанавливать библиотеки через pip. Требует подтверждения пользователя.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Полный текст консольной команды."},
                "working_directory": {
                    "type": "string",
                    "description": "Абсолютный путь проекта. Если не задан, Nova автоматически использует активный workspace."
                }
            },
                        },
            "required": ["command"]
        }
    }

scrape_webpage_tool = {
    "type": "function",
    "function": {
        "name": "scrape_webpage",
        "description": "Загружает веб-страницу по URL и извлекает из неё чистый текст. Используйте для подробного чтения статей, руководств и документации из интернета.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Полный адрес страницы, например: 'https://docs.pytest.org/'"}
            },
            "required": ["url"]
        }
    }
}

get_clipboard_tool = {
    "type": "function",
    "function": {
        "name": "get_clipboard_content",
        "description": "Возвращает текущий скопированный пользователем текст из буфера обмена Windows. Используйте, чтобы проанализировать логи ошибок или куски кода, скопированные пользователем.",
        "parameters": {"type": "object", "properties": {}}
    }
}

set_clipboard_tool = {
    "type": "function",
    "function": {
        "name": "set_clipboard_content",
        "description": "Копирует указанный текст в буфер обмена Windows пользователя.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Текст, который нужно положить в буфер обмена."}
            },
            "required": ["text"]
        }
    }
}

run_terminal_tool = {
    "type": "function",
    "function": {
        "name": "run_terminal_command",
        "description": "Выполняет консольную команду (CMD) в системе Windows в скрытом фоновом режиме и возвращает текстовый ответ. Позволяет проверять статус Git, запускать тесты, устанавливать библиотеки через pip. Требует подтверждения пользователя.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Полный текст консольной команды."},
                "working_directory": {
                    "type": "string",
                    "description": "Абсолютный путь проекта. Если не задан, Nova автоматически использует активный workspace."
                }
            },
            "required": ["command"]
        }
    }
}

list_windows_tool = {
    "type": "function",
    "function": {
        "name": "list_active_windows",
        "description": "Возвращает список заголовков всех открытых и видимых приложений (окон) на экране пользователя.",
        "parameters": {"type": "object", "properties": {}}
    }
}

focus_window_tool = {
    "type": "function",
    "function": {
        "name": "focus_window",
        "description": "Принудительно выводит окно указанной программы на передний план (наводит фокус). Используйте перед набором текста, чтобы убедиться, что текст запишется в правильное приложение.",
        "parameters": {
            "type": "object",
            "properties": {
                "window_title_part": {"type": "string", "description": "Часть заголовка или имя программы (например: 'discord', 'visual studio', 'telegram')."}
            },
            "required": ["window_title_part"]
        }
    }
}

# Единый плоский список всех инструментов для Nova
ALL_TOOLS = [
    open_app_tool,
    open_app_batch_tool,
    close_app_tool, 
    type_text_tool, 
    scrape_webpage_tool,
    get_clipboard_tool,
    set_clipboard_tool,
    run_terminal_tool,
    create_project_tool,
    get_time_tool, 
    change_volume_tool, 
    open_website_tool, 
    get_system_status_tool, 
    search_web_tavily_tool, 
    execute_cmd_tool, 
    manage_media_tool, 
    manage_windows_tool, 
    create_note_tool, 
    set_timer_tool, 
    control_smart_home_tool, 
    configure_assistant_tool, 
    save_memory_tool, 
    search_memory_tool, 
    add_reminder_tool, 
    list_reminders_tool, 
    execute_python_tool, 
    mouse_click_tool, 
    press_hotkey_tool,
    list_windows_tool,
    focus_window_tool,
    write_in_application_tool
]

for tool in ALL_TOOLS:
    parameters = tool["function"].setdefault(
        "parameters",
        {
            "type": "object",
            "properties": {},
        },
    )
    parameters.setdefault("additionalProperties", False)

process_manager_tools = [
    {
        "type": "function",
        "function": {
            "name": "start_process",
            "description": (
                "Запускает фоновый процесс "
                "(сервер, тесты, сборку) "
                "и возвращает его идентификатор."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": (
                            "Команда и аргументы, "
                            "например "
                            "['python', '-m', 'http.server']"
                        ),
                    },
                    "label": {
                        "type": "string",
                        "description": (
                            "Человекочитаемое имя процесса."
                        ),
                    },
                    "cwd": {
                        "type": "string",
                        "description": (
                            "Рабочий каталог."
                        ),
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_process_status",
            "description": (
                "Возвращает статус фонового процесса "
                "по его идентификатору."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "string",
                        "description": (
                            "Идентификатор процесса."
                        ),
                    },
                },
                "required": ["process_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_process_output",
            "description": (
                "Читает последние строки stdout "
                "или stderr фонового процесса."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "string",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": (
                            "Максимум строк для чтения."
                        ),
                    },
                    "stream": {
                        "type": "string",
                        "enum": [
                            "stdout",
                            "stderr",
                        ],
                        "description": (
                            "Какой поток читать."
                        ),
                    },
                },
                "required": ["process_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_process",
            "description": (
                "Останавливает фоновый процесс."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "string",
                    },
                    "force": {
                        "type": "boolean",
                        "description": (
                            "Принудительное завершение."
                        ),
                    },
                },
                "required": ["process_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_processes",
            "description": (
                "Возвращает список всех управляемых "
                "фоновых процессов."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]

ALL_TOOLS.extend(process_manager_tools)

filesystem_tools = [
    {
        "type": "function",
        "function": {
            "name": "read_text_file",
            "description": (
                "Читает содержимое текстового файла."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Путь к файлу."
                        ),
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_text_file",
            "description": (
                "Записывает текст в файл. "
                "Автоматически создаёт backup."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    },
                    "content": {
                        "type": "string",
                    },
                    "create_backup": {
                        "type": "boolean",
                    },
                },
                "required": [
                    "path",
                    "content",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_text_patch",
            "description": (
                "Применяет текстовый патч к файлу. "
                "Поддерживает + (добавить), "
                "- (удалить), = (заменить)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    },
                    "patch": {
                        "type": "string",
                        "description": (
                            "Строки патча, "
                            "например:\n"
                            "+ Новая строка\n"
                            "- Удалить эту\n"
                            "= Старое -> Новое"
                        ),
                    },
                },
                "required": [
                    "path",
                    "patch",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_diff",
            "description": (
                "Возвращает diff файла."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Ищет файлы по шаблону "
                "в указанном каталоге."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                    },
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Шаблон поиска, "
                            "например *.py"
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                    },
                    "recursive": {
                        "type": "boolean",
                    },
                },
                "required": [
                    "directory",
                    "pattern",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rollback_file",
            "description": (
                "Восстанавливает последний backup файла."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "undo_last_file_change",
            "description": (
                "Безопасно отменяет последнее изменение файла, "
                "которое Nova выполнила через write_text_file или "
                "apply_text_patch. Восстанавливает точный backup и "
                "отказывается перезаписывать более свежие ручные правки."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]

ALL_TOOLS.extend(filesystem_tools)

git_tools = [
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": (
                "Проверяет статус Git-репозитория."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                    },
                },
                "required": ["repo_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": (
                "Показывает изменения в Git-репозитории."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                    },
                    "staged": {
                        "type": "boolean",
                    },
                },
                "required": ["repo_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": (
                "Показывает историю коммитов."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                    },
                    "max_count": {
                        "type": "integer",
                    },
                },
                "required": ["repo_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": (
                "Создаёт коммит в Git-репозитории."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                    },
                    "message": {
                        "type": "string",
                    },
                    "add_all": {
                        "type": "boolean",
                    },
                },
                "required": [
                    "repo_path",
                    "message",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_branch",
            "description": (
                "Показывает список веток Git."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                    },
                },
                "required": ["repo_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_project",
            "description": (
                "Анализирует структуру проекта: "
                "определяет язык, фреймворки, "
                "наличие Docker, Git и CI."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                    },
                },
                "required": ["project_path"],
                "additionalProperties": False,
            },
        },
    },
]

ALL_TOOLS.extend(git_tools)

memory_store_tools = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": (
                "Сохраняет факт в долговременную память."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                    },
                    "value": {
                        "type": "string",
                    },
                    "category": {
                        "type": "string",
                    },
                },
                "required": [
                    "key",
                    "value",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "Ищет в долговременной памяти."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_memory",
            "description": (
                "Удаляет факт из памяти по ключу."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                    },
                },
                "required": ["key"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_all_memories",
            "description": (
                "Очищает всю долговременную память."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]

ALL_TOOLS.extend(memory_store_tools)

artifact_tools = [
    {
        "type": "function",
        "function": {
            "name": "store_artifact",
            "description": (
                "Сохраняет большой текст как артефакт "
                "и возвращает его идентификатор."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                    },
                    "artifact_type": {
                        "type": "string",
                    },
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_artifact",
            "description": (
                "Читает содержимое артефакта "
                "по его идентификатору."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "artifact_id": {
                        "type": "string",
                    },
                },
                "required": ["artifact_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_artifact",
            "description": (
                "Удаляет артефакт по идентификатору."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "artifact_id": {
                        "type": "string",
                    },
                },
                "required": ["artifact_id"],
                "additionalProperties": False,
            },
        },
    },
]

ALL_TOOLS.extend(artifact_tools)

browser_tools = [
    {
        "type": "function",
        "function": {
            "name": "browser_start",
            "description": (
                "Запускает изолированный браузер Nova."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_open_url",
            "description": (
                "Открывает безопасный публичный HTTP "
                "или HTTPS адрес в изолированном браузере."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2048,
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": [
                            "load",
                            "domcontentloaded",
                            "networkidle",
                            "commit",
                        ],
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "minimum": 1000,
                        "maximum": 120000,
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_page_text",
            "description": (
                "Извлекает текст из текущей страницы "
                "или указанного DOM-элемента."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "maxLength": 500,
                    },
                    "max_characters": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50000,
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": (
                "Нажимает первый видимый DOM-элемент "
                "по Playwright CSS-селектору."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "minimum": 1000,
                        "maximum": 120000,
                    },
                },
                "required": ["selector"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": (
                "Вводит текст в поле формы текущей страницы."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                    },
                    "text": {
                        "type": "string",
                        "maxLength": 100000,
                    },
                    "clear_first": {
                        "type": "boolean",
                    },
                },
                "required": [
                    "selector",
                    "text",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": (
                "Сохраняет снимок текущей страницы браузера."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "full_page": {
                        "type": "boolean",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_status",
            "description": (
                "Возвращает состояние изолированного браузера."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_close",
            "description": (
                "Закрывает изолированный браузер Nova."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]

ALL_TOOLS.extend(browser_tools)
subagent_tools = [
    {
        "type": "function",
        "function": {
            "name": "delegate_subagents",
            "description": (
                "Создаёт временную команду аналитических субагентов для сложной задачи. "
                "Nova автоматически ограничивает параллелизм числом доступных API-ключей, "
                "распределяет модели и возвращает reviewer-сводку. Используйте для независимых "
                "исследований, аудита, архитектуры и проверки перед реальными действиями."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "minLength": 1, "maxLength": 6000},
                    "subtasks": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string", "maxLength": 80},
                                "task": {"type": "string", "minLength": 1, "maxLength": 2000},
                            },
                            "required": ["task"],
                            "additionalProperties": False,
                        },
                    },
                    "context": {"type": "string", "maxLength": 6000},
                    "max_agents": {"type": "integer", "minimum": 1, "maximum": 6},
                },
                "required": ["goal"],
                "additionalProperties": False,
            },
        },
    },
]
ALL_TOOLS.extend(subagent_tools)
planning_tools = [
    {
        "type": "function",
        "function": {
            "name": "execute_plan",
            "description": (
                "Валидирует и выполняет многошаговый план. "
                "Используйте для сложных задач с зависимостями. "
                "Каждый шаг вызывает зарегистрированный инструмент."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2000,
                    },
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": {
                            "type": "object",
                            "properties": {
                                "step_id": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 100,
                                },
                                "tool_name": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 100,
                                },
                                "arguments": {
                                    "type": "object",
                                    "properties": {},
                                },
                                "depends_on": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                    },
                                },
                                "description": {
                                    "type": "string",
                                    "maxLength": 1000,
                                },
                                "critical": {
                                    "type": "boolean",
                                },
                            },
                            "required": [
                                "step_id",
                                "tool_name",
                                "arguments",
                            ],
                        },
                    },
                    "session_id": {
                        "type": "string",
                    },
                    "turn_id": {
                        "type": "string",
                    },
                },
                "required": [
                    "goal",
                    "steps",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plan_status",
            "description": (
                "Возвращает состояние ранее созданного плана."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                    },
                },
                "required": ["plan_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_plan",
            "description": (
                "Отменяет активный план."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                    },
                },
                "required": ["plan_id"],
                "additionalProperties": False,
            },
        },
    },
]

ALL_TOOLS.extend(planning_tools)
background_plan_tools = [
    {
        "type": "function",
        "function": {
            "name": "start_background_plan",
            "description": (
                "Запускает валидированный многошаговый план "
                "в фоне и немедленно возвращает его идентификатор."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2000,
                    },
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": {
                            "type": "object",
                            "properties": {
                                "step_id": {
                                    "type": "string",
                                },
                                "tool_name": {
                                    "type": "string",
                                },
                                "arguments": {
                                    "type": "object",
                                    "properties": {},
                                },
                                "depends_on": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                    },
                                },
                                "description": {
                                    "type": "string",
                                },
                                "critical": {
                                    "type": "boolean",
                                },
                            },
                            "required": [
                                "step_id",
                                "tool_name",
                                "arguments",
                            ],
                        },
                    },
                    "session_id": {
                        "type": "string",
                    },
                    "turn_id": {
                        "type": "string",
                    },
                },
                "required": [
                    "goal",
                    "steps",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_background_plan_status",
            "description": (
                "Возвращает состояние фонового плана."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "background_id": {
                        "type": "string",
                    },
                },
                "required": ["background_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_background_plans",
            "description": (
                "Возвращает список фоновых планов."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retry_background_plan",
            "description": (
                "Повторно запускает failed-фоновый план с последнего "
                "сохранённого checkpoint, не повторяя completed-шаги."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "background_id": {
                        "type": "string",
                    },
                },
                "required": ["background_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_background_plan",
            "description": (
                "Отменяет активный фоновый план."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "background_id": {
                        "type": "string",
                    },
                },
                "required": ["background_id"],
                "additionalProperties": False,
            },
        },
    },
]

ALL_TOOLS.extend(background_plan_tools)

website_watch_tools = [
    {
        "type": "function",
        "function": {
            "name": "watch_website",
            "description": (
                "Создаёт явную подписку на изменения публичной "
                "HTTP/HTTPS-страницы и сохраняет начальный baseline."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2000,
                    },
                    "label": {
                        "type": "string",
                        "maxLength": 200,
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_website_watches",
            "description": "Показывает активные подписки на сайты.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_website_watch",
            "description": "Удаляет подписку на изменение сайта.",
            "parameters": {
                "type": "object",
                "properties": {
                    "watch_id": {
                        "type": "string",
                    },
                },
                "required": ["watch_id"],
                "additionalProperties": False,
            },
        },
    },
]

ALL_TOOLS.extend(website_watch_tools)

backup_watch_tools = [
    {
        "type": "function",
        "function": {
            "name": "watch_backup",
            "description": (
                "Включает контроль свежести резервных копий в явно "
                "указанном локальном файле или каталоге."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2000,
                    },
                    "max_age_hours": {
                        "type": "number",
                        "minimum": 0.1,
                        "maximum": 8760,
                    },
                    "label": {
                        "type": "string",
                        "maxLength": 200,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_backup_watches",
            "description": "Показывает настройки контроля backup.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_backup_watch",
            "description": "Удаляет настройку контроля backup.",
            "parameters": {
                "type": "object",
                "properties": {
                    "watch_id": {
                        "type": "string",
                    },
                },
                "required": ["watch_id"],
                "additionalProperties": False,
            },
        },
    },
]

ALL_TOOLS.extend(backup_watch_tools)

package_update_tools = [
    {
        "type": "function",
        "function": {
            "name": "watch_package_update",
            "description": (
                "Включает проверку обновлений явно указанного "
                "установленного Python-пакета через PyPI."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "package_name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                    },
                },
                "required": ["package_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_package_update_watches",
            "description": "Показывает контроль обновлений пакетов.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_package_update_watch",
            "description": "Удаляет контроль обновлений пакета.",
            "parameters": {
                "type": "object",
                "properties": {
                    "watch_id": {
                        "type": "string",
                    },
                },
                "required": ["watch_id"],
                "additionalProperties": False,
            },
        },
    },
]

ALL_TOOLS.extend(package_update_tools)
