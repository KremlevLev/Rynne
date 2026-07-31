from __future__ import annotations

from modules.agent.execution_memory import ExecutionMemory, goal_terms


def successful(name: str) -> dict:
    return {
        "name": name,
        "arguments": {"password": "must-not-be-stored"},
        "result": {"success": True, "message": "ok"},
    }


def test_execution_memory_learns_only_tool_sequence(tmp_path) -> None:
    path = tmp_path / "patterns.json"
    memory = ExecutionMemory(path)

    assert memory.remember_success(
        "Открой OpenRouter и проверь активность",
        [successful("browser_open_url"), successful("browser_get_page_text")],
    )

    raw = path.read_text(encoding="utf-8")
    assert "browser_open_url" in raw
    assert "openrouter" not in raw.lower()
    assert "активность" not in raw.lower()
    assert "must-not-be-stored" not in raw
    assert "password" not in raw


def test_execution_memory_retrieves_relevant_available_playbook(tmp_path) -> None:
    memory = ExecutionMemory(tmp_path / "patterns.json")
    results = [successful("browser_open_url"), successful("browser_screenshot")]
    memory.remember_success("Открой сайт и сделай скрин", results)
    memory.remember_success("Открой сайт и сделай скрин", results)

    matches = memory.find(
        "Сделай скрин сайта",
        {"browser_open_url", "browser_screenshot"},
    )

    assert matches[0].tools == ("browser_open_url", "browser_screenshot")
    assert matches[0].success_count == 2
    assert "browser_open_url -> browser_screenshot" in memory.prompt_for(
        "Сделай скрин сайта",
        {"browser_open_url", "browser_screenshot"},
    )


def test_failed_execution_is_not_learned(tmp_path) -> None:
    memory = ExecutionMemory(tmp_path / "patterns.json")
    failed = {
        "name": "browser_open_url",
        "result": {"success": False, "message": "failed"},
    }

    assert not memory.remember_success("Открой сайт", [failed])
    assert not (tmp_path / "patterns.json").exists()


def test_goal_terms_remove_noise_without_storing_original_phrase() -> None:
    assert goal_terms("Открой мне сайт и сделай скрин") == (
        "открой",
        "сайт",
        "сделай",
        "скрин",
    )
