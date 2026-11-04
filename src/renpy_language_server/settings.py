"""Server settings and their defaults.

Settings are intentionally forgiving: an unknown key or a value of the wrong
type is ignored instead of disabling the server. This keeps an old extension or
a hand-written client configuration from breaking every feature.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from typing import Any, Literal, cast

ParserName = Literal["light", "tree-sitter", "auto"]
DiagnosticSeveritySetting = Literal["error", "warning", "off"]
DiagnosticMode = Literal["open", "workspace"]

# New rules default to ``off`` until they have been validated against real
# projects. The two pre-existing rules keep their previous behaviour.
DEFAULT_DIAGNOSTIC_RULES: dict[str, DiagnosticSeveritySetting] = {
    "indentation": "warning",
    "tabs": "warning",
    "filename": "off",
    "invalid_variable": "off",
    "reserved_names": "off",
    "comparison": "off",
    "stray_dollar": "off",
    "obsolete_api": "off",
    "undefined_persistent": "off",
    "undefined_store": "off",
    "duplicate_label": "off",
    "unknown_label": "warning",
    "unknown_image": "off",
    "undefined_screen": "off",
}
DIAGNOSTIC_RULES = frozenset(DEFAULT_DIAGNOSTIC_RULES)
_SEVERITIES = frozenset({"error", "warning", "off"})
_MODES = frozenset({"open", "workspace"})


@dataclass(frozen=True)
class Settings:
    """Options that affect server behaviour.

    Defaults match the current formatter and CLI behaviour.
    """

    indent: int = 4
    max_blank_lines: int = 2
    align_equals: bool = True
    normalize_spacing: bool = True
    normalize_quotes: bool = True
    format_python: bool = False
    diagnostics: bool = True
    unknown_label_diagnostics: bool = True
    code_actions: bool = True
    completion: bool = True
    automatic_assets: bool = True
    semantic_tokens: bool = False
    workspace_symbols: bool = True
    hover: bool = True
    rename: bool = True
    references: bool = True
    highlight: bool = True
    signature: bool = True
    extended_index: bool = True
    member_references: bool = True
    diagnostics_mode: DiagnosticMode = "open"
    diagnostic_rules: Mapping[str, DiagnosticSeveritySetting] = field(
        default_factory=lambda: dict(DEFAULT_DIAGNOSTIC_RULES)
    )
    parser: ParserName = "light"


_PARSERS = frozenset({"light", "tree-sitter", "auto"})
_KNOWN = frozenset(field.name for field in fields(Settings))


def settings_from_initialize(params: Any) -> Settings:
    """Read settings from ``initialize`` parameters.

    Both ``{"renpyLanguageServer": {...}}`` and a flat object are accepted. The nested form
    wins when both contain the same key.
    """
    options = getattr(params, "initialization_options", None)
    return merge_settings(Settings(), options)


def merge_settings(current: Settings, raw: Any) -> Settings:
    """Return ``current`` with every valid key from ``raw`` applied."""
    if not isinstance(raw, dict):
        return current

    data = cast(dict[str, Any], raw)
    values: dict[str, Any] = {}
    for key, value in data.items():
        if key in _KNOWN:
            values[key] = value

    nested = data.get("renpyLanguageServer")
    if isinstance(nested, dict):
        nested_data = cast(dict[str, Any], nested)
        for key, value in nested_data.items():
            if key in _KNOWN:
                values[key] = value

    changes: dict[str, Any] = {}
    for key, value in values.items():
        parsed = _coerce(key, value)
        if parsed is not None:
            changes[key] = parsed

    explicit_rules = cast(
        dict[str, DiagnosticSeveritySetting], changes.get("diagnostic_rules", {})
    )
    rules = dict(current.diagnostic_rules)
    rules.update(explicit_rules)

    if "unknown_label" in explicit_rules:
        changes["unknown_label_diagnostics"] = explicit_rules["unknown_label"] != "off"
    elif "unknown_label_diagnostics" in changes:
        rules["unknown_label"] = (
            "warning" if changes["unknown_label_diagnostics"] else "off"
        )

    if "diagnostic_rules" in changes or "unknown_label_diagnostics" in changes:
        changes["diagnostic_rules"] = rules

    if not changes:
        return current
    return replace(current, **changes)


def _coerce(key: str, value: Any) -> Any | None:
    if key == "indent":
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        return None
    if key == "max_blank_lines":
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None
    if key in {
        "align_equals",
        "normalize_spacing",
        "normalize_quotes",
        "format_python",
        "diagnostics",
        "unknown_label_diagnostics",
        "code_actions",
        "completion",
        "automatic_assets",
        "semantic_tokens",
        "workspace_symbols",
        "hover",
        "rename",
        "references",
        "highlight",
        "signature",
        "extended_index",
        "member_references",
    }:
        return value if isinstance(value, bool) else None
    if key == "parser":
        return value if isinstance(value, str) and value in _PARSERS else None
    if key == "diagnostics_mode":
        if not isinstance(value, str):
            return None
        mode = value.strip().lower().replace("-", "").replace("_", "")
        if mode == "openfilesonly":
            return "open"
        if mode in _MODES:
            return mode
        return None
    if key == "diagnostic_rules":
        if not isinstance(value, Mapping):
            return None
        rules: dict[str, DiagnosticSeveritySetting] = {}
        items = cast(Mapping[object, object], value).items()
        for name, severity in items:
            if not isinstance(name, str) or name not in DIAGNOSTIC_RULES:
                continue
            if not isinstance(severity, str):
                continue
            normalized = severity.strip().lower()
            if normalized in _SEVERITIES:
                rules[name] = cast(DiagnosticSeveritySetting, normalized)
        return rules
    return None
