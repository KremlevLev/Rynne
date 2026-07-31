from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core.config import _collect_keys


def test_core_config_imports_without_provider_keys() -> None:
    project_root = Path(__file__).resolve().parent.parent
    environment = os.environ.copy()
    environment["PYTHON_DOTENV_DISABLED"] = "1"
    for name in tuple(environment):
        if (
            name.startswith("GROQ_API_KEY")
            or name.startswith("OPENROUTER_API_KEY")
            or name.startswith("GEMINI_API_KEY")
        ):
            environment.pop(name)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import core.config as c; "
                "assert c.HAS_MODEL_PROVIDER is False; "
                "assert c.PROVIDER == 'unconfigured'; "
                "assert c.API_KEY == ''"
            ),
        ],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


def test_collect_keys_has_no_numbered_key_limit(
    monkeypatch,
) -> None:
    prefix = "NOVA_TEST_PROVIDER_KEY"
    monkeypatch.setenv(
        "NOVA_TEST_PROVIDER_KEYS",
        "csv-one,csv-two",
    )
    monkeypatch.setenv(prefix, "legacy")
    monkeypatch.setenv(f"{prefix}_37", "numbered")
    monkeypatch.setenv(f"{prefix}_999", "csv-one")

    assert _collect_keys(
        "NOVA_TEST_PROVIDER_KEYS",
        prefix,
        prefix,
    ) == (
        "csv-one",
        "csv-two",
        "legacy",
        "numbered",
    )
