"""Tests for indentation and unknown-label diagnostics."""

from pathlib import Path

from lsprotocol import types

from renpy_language_server.analysis import analyze
from renpy_language_server.assets import AssetIndex
from renpy_language_server.diagnostics import (
    COMPARISON,
    DUPLICATE_LABEL,
    FILENAME,
    INDENTATION,
    INVALID_VARIABLE,
    OBSOLETE_API,
    RESERVED_NAMES,
    STRAY_DOLLAR,
    TABS,
    UNDEFINED_PERSISTENT,
    UNDEFINED_SCREEN,
    UNDEFINED_STORE,
    UNKNOWN_IMAGE,
    UNKNOWN_LABEL,
    diagnostics_for_document,
    indentation_diagnostics,
    unknown_label_diagnostics,
)
from renpy_language_server.index import WorkspaceIndex
from renpy_language_server.settings import DEFAULT_DIAGNOSTIC_RULES, Settings


def index_with(source: str) -> WorkspaceIndex:
    index = WorkspaceIndex()
    index.update("file:///script.rpy", source)
    return index


def codes(source: str, index: WorkspaceIndex | None = None) -> list[str]:
    index = index or index_with("")
    return [
        str(item.code) for item in diagnostics_for_document(source, index, Settings())
    ]


def all_rules() -> Settings:
    return Settings(
        diagnostic_rules={rule: "warning" for rule in DEFAULT_DIAGNOSTIC_RULES}
    )


def rule_codes(
    source: str,
    *,
    index: WorkspaceIndex | None = None,
    uri: str = "file:///script.rpy",
    assets: AssetIndex | None = None,
) -> list[str]:
    index = index or index_with(source)
    return [
        str(item.code)
        for item in diagnostics_for_document(source, index, all_rules(), uri, assets)
    ]


def test_clean_two_and_four_space_files_are_quiet() -> None:
    two = "label start:\n  jump other\nlabel other:\n  return\n"
    four = "label start:\n    jump other\nlabel other:\n    return\n"

    assert codes(two, index_with(two)) == []
    assert codes(four, index_with(four)) == []


def test_mixed_indentation_warns() -> None:
    source = 'label start:\n    e "Hi."\n  return\n'
    assert codes(source) == [INDENTATION]


def test_empty_body_warns() -> None:
    source = "label start:\nlabel next:\n    return\n"
    assert codes(source) == [INDENTATION]


def test_continuations_strings_comments_and_blanks_are_ignored() -> None:
    source = (
        "label start:\n"
        "    # note:\n"
        '    e """\n'
        "not code:\n"
        '        """\n'
        "    $ x = func(\n"
        "        1,\n"
        "    )\n"
        "    return\n"
    )
    assert codes(source) == []


def test_unknown_label_warns() -> None:
    source = "label start:\n    jump missing\n"
    index = index_with(source)
    result = unknown_label_diagnostics(analyze(source), source.split("\n"), index)

    assert len(result) == 1
    assert result[0].code == UNKNOWN_LABEL
    assert result[0].range.start.line == 1
    assert result[0].range.start.character == 9


def test_known_cross_file_label_is_quiet() -> None:
    source = "label start:\n    call chapter_one\n"
    index = WorkspaceIndex()
    index.update("file:///a.rpy", source)
    index.update("file:///b.rpy", "label chapter_one:\n    return\n")

    assert codes(source, index) == []


def test_dynamic_targets_and_call_screen_are_quiet() -> None:
    source = (
        "label start:\n"
        "    jump expression target\n"
        "    call screen main_menu\n"
        "    jump 'literal'\n"
    )
    assert codes(source) == []


def test_known_local_label_is_quiet() -> None:
    source = "label start:\n    jump .local\n\nlabel .local:\n    return\n"
    assert codes(source, index_with(source)) == []


def test_unknown_local_label_warns_with_its_full_name() -> None:
    source = "label start:\n    jump .missing\n"
    result = unknown_label_diagnostics(
        analyze(source), source.split("\n"), index_with(source)
    )

    assert len(result) == 1
    assert result[0].code == UNKNOWN_LABEL
    assert result[0].message == "Unknown label 'start.missing'."


def test_local_label_resolves_under_the_nearest_global_label() -> None:
    source = (
        "label chapter:\n"
        "    jump .intro\n"
        "\n"
        "label other:\n"
        "    jump .intro\n"
        "\n"
        "label .intro:\n"
        "    return\n"
        "\n"
        "label chapter.intro:\n"
        "    return\n"
    )
    # Both targets exist in the workspace index, so neither warns.
    assert codes(source, index_with(source)) == []


def test_local_label_without_a_global_label_is_skipped() -> None:
    source = "jump .orphan\n"
    assert codes(source) == []


def test_rules_can_be_disabled() -> None:
    source = "label start:\n    jump missing\n"
    assert (
        diagnostics_for_document(
            source, index_with(source), Settings(diagnostics=False)
        )
        == []
    )
    assert (
        diagnostics_for_document(
            source,
            index_with(source),
            Settings(unknown_label_diagnostics=False),
        )
        == []
    )


def test_indentation_helper_accepts_raw_lines() -> None:
    source = 'label start:\n    e "Hi."\n'
    result = indentation_diagnostics(analyze(source), source.split("\n"))
    assert result == []


def test_tabs_warn_but_spaces_and_string_contents_do_not() -> None:
    assert rule_codes("label start:\n\treturn\n") == [TABS]
    assert rule_codes("label start:\n    return\n") == []
    source = 'label start:\n    e """\n\ttab inside a string\n    """\n'
    assert rule_codes(source) == []


def test_filename_rule_uses_the_document_uri_and_ignore_comment(
    tmp_path: Path,
) -> None:
    source = "label start:\n    return\n"
    bad_uri = (tmp_path / "00bad.rpy").as_uri()
    bad_index = WorkspaceIndex()
    bad_index.update(bad_uri, source)
    assert rule_codes(source, index=bad_index, uri=bad_uri) == [FILENAME]

    good_uri = (tmp_path / "script.rpy").as_uri()
    good_index = WorkspaceIndex()
    good_index.update(good_uri, source)
    assert rule_codes(source, index=good_index, uri=good_uri) == []

    ignored = "#@renpy-filename:ignore\n" + source
    ignored_index = WorkspaceIndex()
    ignored_index.update(bad_uri, ignored)
    assert rule_codes(ignored, index=ignored_index, uri=bad_uri) == []


def test_invalid_and_reserved_variable_names() -> None:
    assert rule_codes("define 1bad = 1\n") == [INVALID_VARIABLE]
    assert rule_codes("define _secret = 1\n") == [
        INVALID_VARIABLE,
        RESERVED_NAMES,
    ]
    assert rule_codes("define list = []\n") == [RESERVED_NAMES]
    assert rule_codes("define score = 1\n") == []
    assert rule_codes("# define list = []\n") == []


def test_comparison_rule_ignores_strings_and_real_comparisons() -> None:
    assert rule_codes("label start:\n    if x = 1:\n        pass\n") == [COMPARISON]
    assert rule_codes("label start:\n    if x == 1:\n        pass\n") == []
    assert rule_codes("label start:\n    while x >= 1:\n        pass\n") == []
    assert rule_codes('label start:\n    e "if x = 1"\n') == []


def test_stray_dollar_rule_allows_a_statement_prefix() -> None:
    assert rule_codes("label start:\n    $ x = 1\n") == []
    assert rule_codes("label start:\n    $ x = 1 $ y\n") == [STRAY_DOLLAR]
    assert rule_codes('label start:\n    e "Cost $5"\n') == []


def test_obsolete_api_rule_ignores_comments_and_similar_names() -> None:
    assert rule_codes('define x = im.Crop("a.png")\n') == [OBSOLETE_API]
    assert rule_codes('# define x = im.Crop("a.png")\n') == []
    assert rule_codes('define x = my_im.Crop("a.png")\n') == []


def test_undefined_persistent_rule_accepts_definitions_and_private_names() -> None:
    source = "label start:\n    $ persistent.score += 1\n"
    assert rule_codes(source) == [UNDEFINED_PERSISTENT]

    defined = "default persistent.score = 0\n" + source
    assert rule_codes(defined) == []

    private = "label start:\n    $ persistent._internal = 1\n"
    assert rule_codes(private) == []


def test_undefined_store_rule_accepts_defaults_and_built_in_names() -> None:
    source = "label start:\n    $ store.thing = 1\n"
    assert rule_codes(source) == [UNDEFINED_STORE]

    defined = "default thing = 1\n" + source
    assert rule_codes(defined) == []

    builtin = "label start:\n    $ store.menu = 1\n    $ store._private = 2\n"
    assert rule_codes(builtin) == []


def test_duplicate_label_rule_reports_other_files() -> None:
    first = "label start:\n    return\n"
    second = "label start:\n    return\n"
    index = WorkspaceIndex()
    index.update("file:///a.rpy", first)
    index.update("file:///b.rpy", second)

    result = diagnostics_for_document(first, index, all_rules(), "file:///a.rpy")
    duplicates = [item for item in result if item.code == DUPLICATE_LABEL]
    assert len(duplicates) == 1
    assert "a.rpy" not in duplicates[0].message
    assert "b.rpy:1" in duplicates[0].message


def test_duplicate_label_rule_is_quiet_for_unique_labels() -> None:
    first = "label start:\n    jump other\n"
    second = "label other:\n    return\n"
    index = WorkspaceIndex()
    index.update("file:///a.rpy", first)
    index.update("file:///b.rpy", second)

    assert rule_codes(first, index=index, uri="file:///a.rpy") == []


def test_unknown_image_rule_accepts_declarations_and_assets(tmp_path: Path) -> None:
    source = "label start:\n    show bg missing\n"
    assert rule_codes(source) == [UNKNOWN_IMAGE]

    declared = 'image bg missing = "bg.png"\n' + source
    assert rule_codes(declared, index=index_with(declared)) == []

    automatic = "label start:\n    show bg room\n"
    images = tmp_path / "game" / "images"
    images.mkdir(parents=True)
    (images / "bg room.png").write_bytes(b"")
    assets = AssetIndex()
    assets.scan([tmp_path])
    assert rule_codes(automatic, index=index_with(automatic), assets=assets) == []


def test_unknown_image_rule_ignores_expressions() -> None:
    assert rule_codes("label start:\n    show expression picture\n") == []


def test_undefined_screen_rule_accepts_declarations_and_built_ins() -> None:
    missing = "label start:\n    call screen missing\n"
    assert rule_codes(missing) == [UNDEFINED_SCREEN]

    declared = "screen missing():\n    text 'ok'\n" + missing
    assert rule_codes(declared, index=index_with(declared)) == []

    assert rule_codes("label start:\n    call screen main_menu\n") == []
    assert rule_codes("label start:\n    call screen expression name\n") == []
    assert rule_codes("screen menu():\n    use missing\n") == [UNDEFINED_SCREEN]


def test_severity_and_rule_switch_are_configurable() -> None:
    source = "label start:\n\treturn\n"
    error = Settings(diagnostic_rules={"tabs": "error"})
    result = diagnostics_for_document(source, index_with(source), error)
    assert [item.code for item in result] == [TABS]
    assert result[0].severity == types.DiagnosticSeverity.Error

    disabled = Settings(diagnostic_rules={"tabs": "off"})
    assert diagnostics_for_document(source, index_with(source), disabled) == []
