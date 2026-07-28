from __future__ import annotations

from modules.tools.app_indexer import (
    AppMatch,
    WindowsAppIndexer,
)


def test_launch_batch_is_bounded_and_uses_distinct_apps() -> None:
    indexer = object.__new__(WindowsAppIndexer)
    launched: list[str] = []

    def find_app(app_name: str) -> AppMatch:
        return AppMatch(
            query=app_name,
            matched_name=app_name,
            path=f"{app_name}.exe",
            score=1.0,
            match_type="exact",
        )

    def launch_by_name(app_name: str):
        launched.append(app_name)
        return True, f"opened {app_name}"

    indexer.find_app = find_app
    indexer.launch_by_name = launch_by_name

    result = indexer.launch_batch(5)

    assert result.success
    assert result.data["requested_count"] == 5
    assert result.data["successful_count"] == 5
    assert len(launched) == 5
    assert len(set(launched)) == 5
