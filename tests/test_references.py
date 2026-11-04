"""Tests for references recorded by the index."""

from renpy_language_server.index import WorkspaceIndex, parse_document, utf16_length


def _references(source: str):
    document = parse_document("file:///script.rpy", source)
    return [
        (item.kind, item.name, item.line, item.character)
        for item in document.references
    ]


def test_jump_and_call_targets_are_indexed() -> None:
    source = "label start:\n    jump next\n    call other\n"

    assert _references(source) == [
        ("jump", "next", 1, 9),
        ("call", "other", 2, 9),
    ]


def test_dynamic_targets_are_not_indexed() -> None:
    source = "label start:\n    jump expression target\n    call screen main_menu\n"

    # ``jump expression`` is skipped; ``call screen`` is a screen use, not a
    # label target.
    assert _references(source) == [("screen", "main_menu", 2, 16)]


def test_local_targets_resolve_against_the_current_global_label() -> None:
    source = "label chapter:\n    jump .intro\n\nlabel other:\n    jump .intro\n"
    document = parse_document("file:///script.rpy", source)
    targets = [item for item in document.references if item.kind == "jump"]

    assert [item.name for item in targets] == ["chapter.intro", "other.intro"]
    # The written span still covers the ``.intro`` text.
    assert [item.source_name for item in targets] == [".intro", ".intro"]
    assert targets[0].end_character - targets[0].character == len(".intro")


def test_show_scene_and_hide_record_images_and_transforms() -> None:
    source = (
        "label start:\n"
        "    show eileen happy at center, bounce\n"
        "    scene bg room\n"
        "    hide eileen happy with dissolve\n"
    )

    assert _references(source) == [
        ("image", "eileen happy", 1, 9),
        ("transform", "center", 1, 25),
        ("transform", "bounce", 1, 33),
        ("image", "bg room", 2, 10),
        ("image", "eileen happy", 3, 9),
    ]


def test_screen_statements_are_indexed() -> None:
    source = (
        "screen main_menu:\n"
        "    use navigation\n"
        "\n"
        "label start:\n"
        "    call screen main_menu\n"
        "    show screen stats\n"
        "    hide screen stats\n"
    )

    assert _references(source) == [
        ("use", "navigation", 1, 8),
        ("screen", "main_menu", 4, 16),
        ("screen", "stats", 5, 16),
        ("screen", "stats", 6, 16),
    ]


def test_dialogue_speakers_are_indexed() -> None:
    source = (
        'define e = Character("Eileen")\n'
        "\n"
        "label start:\n"
        '    e "Hello."\n'
        '    e happy "Hi."\n'
        '    text "Not a speaker"\n'
        '    centered "Nor this."\n'
    )

    assert _references(source) == [
        ("speaker", "e", 3, 4),
        ("speaker", "e", 4, 4),
    ]


def test_workspace_references_are_filtered_by_kind_and_name() -> None:
    workspace = WorkspaceIndex()
    workspace.update("file:///a.rpy", "label start:\n    jump other\n")
    workspace.update("file:///b.rpy", "label other:\n    call other\n")

    targets = workspace.references("jump", "other")
    assert [(item.uri, item.line) for item in targets] == [("file:///a.rpy", 1)]
    assert len(workspace.all_references()) == 2


def test_crlf_lines_keep_correct_columns() -> None:
    source = "label start:\r\n    jump next\r\n"
    document = parse_document("file:///script.rpy", source)

    assert [(item.name, item.line, item.character) for item in document.references] == [
        ("next", 1, 9)
    ]


def test_non_ascii_before_a_reference_uses_utf16_columns() -> None:
    source = "label start:\n    show 😀 at center\n"
    document = parse_document("file:///script.rpy", source)

    image = next(item for item in document.references if item.kind == "image")
    transform = next(item for item in document.references if item.kind == "transform")
    assert image.character == 9
    assert image.end_character == 11
    assert transform.character == utf16_length("    show 😀 at ")
    assert transform.end_character - transform.character == len("center")


def test_target_name_does_not_match_an_earlier_keyword() -> None:
    source = "screen e():\n    pass\n\nscreen main():\n    use e\n"
    document = parse_document("file:///script.rpy", source)

    reference = next(item for item in document.references if item.kind == "use")
    assert (reference.name, reference.character) == ("e", 8)


def test_style_parent_references_are_indexed() -> None:
    source = 'style dark is base:\n    color "#000"\n'
    document = parse_document("file:///script.rpy", source)

    assert [(item.kind, item.name, item.character) for item in document.references] == [
        ("style", "base", 14)
    ]
