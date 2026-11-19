"""Tests for server settings parsing."""

from types import SimpleNamespace

from renpy_language_server.numeric_args import (
    ATL_WARPERS,
    DEFAULT_NUMERIC_FAMILIES,
)
from renpy_language_server.settings import (
    DEFAULT_DIAGNOSTIC_RULES,
    Settings,
    merge_settings,
    settings_from_initialize,
)


def test_defaults_match_current_behaviour() -> None:
    settings = Settings()
    assert settings.indent == 4
    assert settings.max_blank_lines == 2
    assert settings.align_equals is True
    assert settings.normalize_spacing is True
    assert settings.normalize_quotes is True
    assert settings.normalize_numeric_args is True
    assert settings.numeric_style == "bare"
    assert settings.numeric_floats is True
    assert settings.numeric_families == DEFAULT_NUMERIC_FAMILIES
    assert settings.numeric_warpers == ATL_WARPERS
    assert settings.format_python is False
    assert settings.diagnostics is True
    assert settings.code_actions is True
    assert settings.completion is True
    assert settings.automatic_assets is True
    assert settings.semantic_tokens is False
    assert settings.workspace_symbols is True
    assert settings.hover is True
    assert settings.rename is True
    assert settings.references is True
    assert settings.highlight is True
    assert settings.signature is True
    assert settings.extended_index is True
    assert settings.member_references is True
    assert settings.diagnostics_mode == "open"
    assert settings.diagnostic_rules == DEFAULT_DIAGNOSTIC_RULES
    assert settings.parser == "light"


def test_initialize_options_are_nested_under_renpy_language_server() -> None:
    params = SimpleNamespace(
        initialization_options={
            "renpyLanguageServer": {"indent": 2, "normalize_spacing": False}
        }
    )
    settings = settings_from_initialize(params)
    assert settings.indent == 2
    assert settings.normalize_spacing is False


def test_initialize_options_accept_a_flat_object() -> None:
    params = SimpleNamespace(initialization_options={"diagnostics": False})
    assert settings_from_initialize(params).diagnostics is False


def test_invalid_values_and_unknown_keys_are_ignored() -> None:
    current = Settings(indent=4, parser="light")
    merged = merge_settings(
        current,
        {
            "indent": 0,
            "max_blank_lines": -1,
            "align_equals": "yes",
            "parser": "magic",
            "wat": 1,
        },
    )
    assert merged == current


def test_bool_is_not_accepted_as_an_integer() -> None:
    assert merge_settings(Settings(), {"indent": True}).indent == 4


def test_semantic_tokens_can_be_toggled() -> None:
    assert merge_settings(Settings(), {"semantic_tokens": True}).semantic_tokens is True


def test_completion_assets_and_workspace_symbols_can_be_toggled() -> None:
    merged = merge_settings(
        Settings(), {"automatic_assets": False, "workspace_symbols": False}
    )
    assert merged.automatic_assets is False
    assert merged.workspace_symbols is False


def test_code_actions_can_be_disabled() -> None:
    assert merge_settings(Settings(), {"code_actions": False}).code_actions is False


def test_quote_normalization_can_be_disabled() -> None:
    merged = merge_settings(Settings(), {"normalize_quotes": False})
    assert merged.normalize_quotes is False


def test_numeric_normalization_can_be_configured() -> None:
    merged = merge_settings(
        Settings(),
        {
            "normalize_numeric_args": False,
            "numeric_style": "parenthesized",
            "numeric_floats": False,
        },
    )
    assert merged.normalize_numeric_args is False
    assert merged.numeric_style == "parens"
    assert merged.numeric_floats is False


def test_numeric_families_accept_lists_and_strings() -> None:
    merged = merge_settings(
        Settings(), {"numeric_families": ["pause", "atl", "unknown"]}
    )
    assert merged.numeric_families == frozenset({"pause", "atl"})

    merged = merge_settings(Settings(), {"numeric_families": "pause,timer"})
    assert merged.numeric_families == frozenset({"pause", "timer"})

    merged = merge_settings(Settings(), {"numeric_families": []})
    assert merged.numeric_families == frozenset()


def test_numeric_warpers_add_to_the_builtins() -> None:
    merged = merge_settings(Settings(), {"numeric_warpers": ["my_warper"]})
    assert "my_warper" in merged.numeric_warpers
    assert merged.numeric_warpers >= ATL_WARPERS

    merged = merge_settings(Settings(), {"numeric_warpers": ["bad name", "ok"]})
    assert "ok" in merged.numeric_warpers
    assert "bad name" not in merged.numeric_warpers


def test_invalid_numeric_settings_are_ignored() -> None:
    current = Settings()
    merged = merge_settings(
        current,
        {
            "numeric_style": "fancy",
            "numeric_families": 3,
            "numeric_warpers": 3,
            "normalize_numeric_args": "yes",
        },
    )
    assert merged == current


def test_hover_can_be_disabled() -> None:
    merged = merge_settings(Settings(), {"hover": False})
    assert merged.hover is False


def test_rename_can_be_disabled() -> None:
    merged = merge_settings(Settings(), {"rename": False})
    assert merged.rename is False


def test_references_can_be_disabled() -> None:
    merged = merge_settings(Settings(), {"references": False})
    assert merged.references is False


def test_signature_can_be_disabled() -> None:
    merged = merge_settings(Settings(), {"signature": False})
    assert merged.signature is False


def test_highlight_can_be_disabled() -> None:
    merged = merge_settings(Settings(), {"highlight": False})
    assert merged.highlight is False


def test_partial_merge_keeps_other_values() -> None:
    current = Settings(indent=2, normalize_spacing=False)
    merged = merge_settings(current, {"format_python": True})
    assert merged.indent == 2
    assert merged.normalize_spacing is False
    assert merged.format_python is True


def test_extended_index_can_be_disabled() -> None:
    merged = merge_settings(Settings(), {"extended_index": False})
    assert merged.extended_index is False


def test_member_references_can_be_disabled() -> None:
    merged = merge_settings(Settings(), {"member_references": False})
    assert merged.member_references is False


def test_new_diagnostic_rules_default_to_off() -> None:
    settings = Settings()
    assert settings.diagnostic_rules["indentation"] == "warning"
    assert settings.diagnostic_rules["unknown_label"] == "warning"
    assert settings.diagnostic_rules["tabs"] == "warning"
    assert settings.diagnostic_rules["filename"] == "off"
    assert settings.diagnostic_rules["unknown_image"] == "off"


def test_diagnostic_rules_merge_partially_and_ignore_invalid_entries() -> None:
    merged = merge_settings(
        Settings(),
        {
            "diagnostic_rules": {
                "tabs": "ERROR",
                "filename": "off",
                "unknown_image": "loud",
                "not_a_rule": "warning",
                3: "warning",
            }
        },
    )
    assert merged.diagnostic_rules["tabs"] == "error"
    assert merged.diagnostic_rules["filename"] == "off"
    assert merged.diagnostic_rules["unknown_image"] == "off"
    assert merged.diagnostic_rules["indentation"] == "warning"
    assert "not_a_rule" not in merged.diagnostic_rules


def test_diagnostic_mode_accepts_workspace_and_vscode_alias() -> None:
    assert (
        merge_settings(Settings(), {"diagnostics_mode": "workspace"}).diagnostics_mode
        == "workspace"
    )
    assert (
        merge_settings(
            Settings(), {"diagnostics_mode": "openFilesOnly"}
        ).diagnostics_mode
        == "open"
    )
    assert (
        merge_settings(Settings(), {"diagnostics_mode": "nonsense"}).diagnostics_mode
        == "open"
    )


def test_legacy_unknown_label_flag_updates_the_rule() -> None:
    disabled = merge_settings(Settings(), {"unknown_label_diagnostics": False})
    assert disabled.diagnostic_rules["unknown_label"] == "off"
    assert disabled.unknown_label_diagnostics is False

    enabled = merge_settings(disabled, {"unknown_label_diagnostics": True})
    assert enabled.diagnostic_rules["unknown_label"] == "warning"


def test_explicit_diagnostic_rule_wins_over_the_legacy_flag() -> None:
    merged = merge_settings(
        Settings(),
        {
            "unknown_label_diagnostics": False,
            "diagnostic_rules": {"unknown_label": "error"},
        },
    )
    assert merged.diagnostic_rules["unknown_label"] == "error"
    assert merged.unknown_label_diagnostics is True
