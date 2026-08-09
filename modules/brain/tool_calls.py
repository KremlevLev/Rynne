# modules/brain/tool_calls.py
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any


logger = logging.getLogger("ToolCallParser")


def _normalize_arguments(arguments: Any) -> dict[str, Any] | None:
    if isinstance(arguments, dict):
        return arguments

    if not isinstance(arguments, str):
        return None

    text = arguments.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text or "{}")
    except json.JSONDecodeError:
        return None

    return parsed if isinstance(parsed, dict) else None


def normalize_tool_call(tool_call: dict[str, Any]) -> dict[str, Any] | None:
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return None

    name = function.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    arguments = _normalize_arguments(function.get("arguments", "{}"))
    if arguments is None:
        return None

    call_id = tool_call.get("id")
    if not isinstance(call_id, str) or not call_id:
        call_id = f"call_{uuid.uuid4().hex}"

    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name.strip(),
            "arguments": json.dumps(
                arguments,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    }


def extract_xml_tool_calls(
    text: str,
    allowed_names: list[str] | set[str],
) -> list[dict[str, Any]]:
    allowed = set(allowed_names)
    found: list[dict[str, Any]] = []

    patterns = [
        re.compile(
            r"<function=([A-Za-z_][A-Za-z0-9_]*)>\s*"
            r"(.*?)\s*</function>",
            re.DOTALL,
        ),
        re.compile(
            r"<([A-Za-z_][A-Za-z0-9_]*)>\s*"
            r"(.*?)\s*</\1>",
            re.DOTALL,
        ),
    ]

    for pattern in patterns:
        for match in pattern.finditer(text):
            name = match.group(1)

            if name == "function" or name not in allowed:
                continue

            arguments = _normalize_arguments(match.group(2))
            if arguments is None:
                logger.warning(
                    "Некорректные XML-аргументы инструмента %s.",
                    name,
                )
                continue

            found.append(
                {
                    "id": f"xml_{uuid.uuid4().hex}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(
                            arguments,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                }
            )

    return deduplicate_tool_calls(found)


def extract_json_tool_calls(text: str) -> list[dict[str, Any]]:
    """Recover a tool call when a provider prints one as plain JSON.

    Some OpenAI-compatible providers occasionally put ``{"tool": ...}`` in
    assistant content instead of the native ``tool_calls`` field.  Treating
    that as user-visible text is misleading; the registry still decides
    whether the named capability actually exists.
    """
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []

    function = payload.get("function")
    if isinstance(function, dict):
        name = function.get("name")
        arguments = function.get("arguments", {})
    else:
        name = payload.get("tool") or payload.get("name")
        arguments = payload.get("arguments", payload.get("parameters", {}))
    if not isinstance(name, str) or not name.strip():
        return []
    normalized = normalize_tool_call({
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    })
    return [normalized] if normalized is not None else []


def canonical_tool_signature(tool_call: dict[str, Any]) -> str:
    normalized = normalize_tool_call(tool_call)
    if normalized is None:
        return "invalid"

    function = normalized["function"]
    parsed = json.loads(function["arguments"])
    canonical_arguments = json.dumps(
        parsed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{function['name']}:{canonical_arguments}"


def deduplicate_tool_calls(
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw_call in tool_calls:
        normalized = normalize_tool_call(raw_call)
        if normalized is None:
            continue

        signature = canonical_tool_signature(normalized)
        if signature in seen:
            logger.warning(
                "Удален повторный вызов инструмента: %s",
                signature,
            )
            continue

        seen.add(signature)
        unique.append(normalized)

    return unique
