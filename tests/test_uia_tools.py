from modules.domain.results import ToolResult
from modules.windows.uia import UIAGrounder, UIElement, create_uia_tools


def test_uia_tools_expose_active_inspection_and_semantic_click() -> None:
    tools = create_uia_tools()

    assert "inspect_active_window" in tools
    assert "click_ui_element" in tools


def test_active_window_inspection_returns_compact_elements(monkeypatch) -> None:
    grounder = UIAGrounder()
    monkeypatch.setattr(
        grounder,
        "get_active_window_elements",
        lambda: [
            UIElement("1", "Google", "Button", "", 10, 20, 100, 40),
            UIElement("2", "", "Pane", "", 0, 0, 10, 10),
        ],
    )

    result = grounder.inspect_active_window()

    assert isinstance(result, ToolResult)
    assert result.success
    assert result.data["elements"][0]["name"] == "Google"
    assert len(result.data["elements"]) == 1


def test_semantic_click_reports_candidates_when_element_is_missing(monkeypatch) -> None:
    grounder = UIAGrounder()
    monkeypatch.setattr(
        grounder,
        "get_active_window_elements",
        lambda: [UIElement("1", "Microsoft", "Button", "", 10, 20, 100, 40)],
    )

    result = grounder.click_ui_element("Google")

    assert not result.success
    assert result.code == "UI_ELEMENT_NOT_FOUND"
    assert result.data["visible_candidates"] == ["Microsoft"]
