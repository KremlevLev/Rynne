from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.build_installer import (
    resolve_package_asset,
    validate_core_runtime_assets,
)


def test_installer_resolves_fastmcp_grammar_from_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = tmp_path / "rfc3987_syntax"
    package_root.mkdir()
    expected = package_root / "syntax_rfc3987.lark"
    expected.write_text("start: value\n", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.build_installer.importlib.util.find_spec",
        lambda _package: SimpleNamespace(
            submodule_search_locations=[str(package_root)],
            origin=None,
        ),
    )

    grammar = resolve_package_asset(
        "rfc3987_syntax",
        "syntax_rfc3987.lark",
    )

    assert grammar == expected


def test_installer_allows_new_mcp_without_legacy_grammar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.build_installer.importlib.util.find_spec",
        lambda _package: None,
    )

    assert resolve_package_asset(
        "rfc3987_syntax",
        "syntax_rfc3987.lark",
    ) is None
    validate_core_runtime_assets(Path("unused"), required_assets=())


def test_installer_requires_fastmcp_grammar(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="syntax_rfc3987\\.lark"):
        validate_core_runtime_assets(tmp_path)

    grammar = (
        tmp_path
        / "_internal"
        / "rfc3987_syntax"
        / "syntax_rfc3987.lark"
    )
    grammar.parent.mkdir(parents=True)
    grammar.write_text("start: value\nvalue: /.+/\n", encoding="utf-8")

    validate_core_runtime_assets(tmp_path)
