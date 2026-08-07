from __future__ import annotations

from modules.agent.skill_library import SkillLibrary


def test_triggered_skill_loads_instructions_and_declared_tools(tmp_path) -> None:
    root = tmp_path / "global"
    skill_dir = root / "browser"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: Browser Operator
description: Надёжная навигация
triggers: [openrouter, личный кабинет]
tools: [browser_open_url, browser_get_page_text, missing_tool]
---
Сначала открой прямой URL, затем прочитай страницу.
""",
        encoding="utf-8",
    )

    bundle = SkillLibrary(root, tmp_path / "no-builtins").match(
        "Открой OpenRouter и проверь личный кабинет",
        None,
        {"browser_open_url", "browser_get_page_text"},
    )

    assert bundle.names == ("Browser Operator",)
    assert "Сначала открой прямой URL" in bundle.prompt
    assert bundle.tools == frozenset({
        "browser_open_url", "browser_get_page_text",
    })


def test_unmatched_triggered_skill_is_not_injected(tmp_path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    (root / "docker.md").write_text(
        "---\ntriggers: [docker]\n---\nИспользуй compose.\n",
        encoding="utf-8",
    )

    bundle = SkillLibrary(root, tmp_path / "no-builtins").match(
        "Открой браузер", None, set()
    )

    assert not bundle.prompt
    assert not bundle.names


def test_path_triggered_skill_matches_mentioned_file(tmp_path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    (root / "python.md").write_text(
        "---\npaths: [**/*.py]\n---\nПосле правки запусти pytest.\n",
        encoding="utf-8",
    )

    bundle = SkillLibrary(root, tmp_path / "no-builtins").match(
        "Исправь src/main.py",
        None,
        set(),
    )

    assert "запусти pytest" in bundle.prompt


def test_workspace_skill_overrides_global_skill_by_name(tmp_path) -> None:
    global_root = tmp_path / "global"
    workspace = tmp_path / "repo"
    project_root = workspace / ".nova" / "skills"
    global_root.mkdir()
    project_root.mkdir(parents=True)
    (global_root / "git.md").write_text(
        "---\nname: Git Flow\n---\nГлобальная процедура.\n",
        encoding="utf-8",
    )
    (project_root / "git.md").write_text(
        "---\nname: Git Flow\n---\nПроектная процедура.\n",
        encoding="utf-8",
    )

    bundle = SkillLibrary(global_root, tmp_path / "no-builtins").match(
        "Сделай коммит",
        str(workspace),
        set(),
    )

    assert "Проектная процедура" in bundle.prompt
    assert "Глобальная процедура" not in bundle.prompt


def test_builtin_browser_skill_is_available_without_user_setup(tmp_path) -> None:
    bundle = SkillLibrary(global_root=tmp_path / "empty").match(
        "Открой сайт в браузере и проверь страницу",
        None,
        {"browser_open_url", "browser_get_page_text"},
    )

    assert "Browser Operator" in bundle.names
    assert "Запуск браузера сам по себе не является результатом" in bundle.prompt
