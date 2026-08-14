from pathlib import Path

import pytest

from scripts.build_installer import (
    resolve_package_asset,
    validate_core_runtime_assets,
)


def test_installer_resolves_fastmcp_grammar_from_package() -> None:
    grammar = resolve_package_asset(
        "rfc3987_syntax",
        "syntax_rfc3987.lark",
    )

    assert grammar.is_file()
    assert grammar.name == "syntax_rfc3987.lark"


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
