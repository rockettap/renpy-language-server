"""Tests for file-local and workspace-wide completion."""

import pytest

from renpy_language_server import builtins as api
from renpy_language_server.completion import (
    _KEYWORDS,  # pyright: ignore[reportPrivateUsage]
    Completion,
    _builtin_documentation,  # pyright: ignore[reportPrivateUsage]
    complete,
)

SOURCE = """\
define e = Character("Eileen", color="#c8ffc8")
define nar = Character('Narrator')
image bg room = "bg room.png"
image eileen happy = "eileen happy.png"
image eileen sad:
    "eileen sad.png"
screen main_menu():
    pass
screen preferences():
    pass
label start:
    return
label chapter_one:
    return

# label commented_out:
"""


def labels(prefix: str) -> list[str]:
    return [item.label for item in complete(SOURCE, prefix).items]


def complete_at(
    marked: str,
    workspace: dict[str, list[Completion]] | None = None,
    container: str | None = None,
):
    """Complete at a ``|`` cursor marker in a full document."""
    position = marked.index("|")
    source = marked[:position] + marked[position + 1 :]
    line = source.count("\n", 0, position)
    line_start = source.rfind("\n", 0, position) + 1
    prefix = source[line_start:position]
    return complete(source, prefix, workspace, container, line)


def labels_at(marked: str) -> list[str]:
    return [item.label for item in complete_at(marked).items]


def test_empty_line_offers_statements_and_characters() -> None:
    result = complete(SOURCE, "    ")
    assert result.replace_start == 4
    assert {"show", "scene", "hide", "jump", "label", "e", "nar"} <= {
        item.label for item in result.items
    }


def test_statement_prefix_is_filtered() -> None:
    result = complete(SOURCE, "    sh")
    assert "show" in labels("    sh")
    assert "scene" not in labels("    sh")
    assert result.replace_start == 4


def test_show_scene_and_hide_offer_images() -> None:
    for prefix in ("    show ", "    scene ", "    hide "):
        result = complete(SOURCE, prefix)
        assert result.replace_start == len(prefix)
        assert {"bg room", "eileen happy", "eileen sad"} <= {
            item.label for item in result.items
        }


def test_show_target_replaces_the_whole_typed_target() -> None:
    result = complete(SOURCE, "    show eileen h")
    assert result.replace_start == len("    show ")
    assert [item.label for item in result.items] == ["eileen happy"]


def test_jump_and_call_offer_labels() -> None:
    for prefix in ("    jump ", "    call "):
        assert {"start", "chapter_one"} <= set(labels(prefix))


def test_call_screen_offers_screens() -> None:
    result = complete(SOURCE, "    call screen ")
    assert result.replace_start == len("    call screen ")
    assert {"main_menu", "preferences"} <= {item.label for item in result.items}


def test_call_screen_is_suggested_while_typing() -> None:
    assert "screen" in labels("    call scr")


def test_character_is_suggested_at_statement_start() -> None:
    assert "e" in labels("    e")
    assert complete(SOURCE, "    e").replace_start == 4


def test_no_completion_inside_dialogue_or_comment() -> None:
    assert complete(SOURCE, '    e "Hello').items == []
    assert complete(SOURCE, "    # show").items == []
    assert complete(SOURCE, '    show "bg').items == []


def test_other_statements_do_not_offer_completion() -> None:
    assert complete(SOURCE, "    define x = 1").items == []
    assert complete(SOURCE, "    label start:").items == []


def test_unknown_statement_context_does_not_dump_keywords() -> None:
    assert complete(SOURCE, "    add ").items == []
    assert complete(SOURCE, "    e ").items == []
    assert "and" in labels("    $ ")


def test_dollar_still_completes_before_the_space() -> None:
    assert labels("    $") == ["$"]


def test_commented_labels_are_ignored() -> None:
    assert "commented_out" not in labels("    jump ")


def test_duplicate_symbols_are_removed() -> None:
    source = 'image bg room = "one.png"\nimage bg room = "two.png"\n'
    result = complete(source, "    show ")
    assert [item.label for item in result.items].count("bg room") == 1
    assert result.items[0].label == "bg room"
    assert {"expression", "screen", "text"} <= {item.label for item in result.items}


def test_empty_source_still_offers_keywords() -> None:
    result = complete("", "    ju")
    assert [item.label for item in result.items] == ["jump"]
    assert result.replace_start == 4


def workspace_symbols() -> dict[str, list[Completion]]:
    return {
        "label": [Completion("chapter_two", "label", "label", "in chapter.rpy")],
        "image": [Completion("bg street", "image", "image", "in images.rpy")],
        "screen": [Completion("choice_overlay", "screen", "screen", "in ui.rpy")],
        "character": [Completion("narrator", "character", "character", "in cast.rpy")],
    }


def test_workspace_labels_complete_after_jump_and_call() -> None:
    for prefix in ("    jump ", "    call "):
        result = complete(SOURCE, prefix, workspace_symbols())
        assert "chapter_two" in {item.label for item in result.items}


def test_workspace_images_and_screens_complete() -> None:
    show = complete(SOURCE, "    show ", workspace_symbols())
    screen = complete(SOURCE, "    call screen ", workspace_symbols())

    assert "bg street" in {item.label for item in show.items}
    assert "choice_overlay" in {item.label for item in screen.items}


def test_workspace_characters_complete_at_statement_start() -> None:
    result = complete(SOURCE, "    nar", workspace_symbols())
    assert "narrator" in {item.label for item in result.items}


def test_local_symbols_win_over_workspace_duplicates() -> None:
    workspace = {"label": [Completion("start", "label", "label", "elsewhere")]}
    result = complete(SOURCE, "    jump ", workspace)
    starts = [item for item in result.items if item.label == "start"]

    assert len(starts) == 1
    assert "this file" in starts[0].documentation


def member_symbols() -> dict[str, list[Completion]]:
    return {
        "member:Player": [
            Completion("hp", "field", "field"),
            Completion("hurt", "method", "method"),
        ],
        "persistent": [Completion("score", "persistent", "define")],
        "variable": [Completion("gold", "variable", "default")],
    }


def test_self_members_complete_with_the_enclosing_class() -> None:
    result = complete(SOURCE, "    self.", member_symbols(), "Player")

    assert result.replace_start == len("    self.")
    assert [item.label for item in result.items] == ["hp", "hurt"]


def test_self_members_are_filtered_by_the_typed_prefix() -> None:
    result = complete(SOURCE, "    self.h", member_symbols(), "Player")

    assert result.replace_start == len("    self.")
    assert [item.label for item in result.items] == ["hp", "hurt"]


def test_class_members_complete_without_a_container() -> None:
    result = complete(SOURCE, "    Player.h", member_symbols())

    assert result.replace_start == len("    Player.")
    assert [item.label for item in result.items] == ["hp", "hurt"]


def test_persistent_and_store_members_complete() -> None:
    persistent = complete(SOURCE, "    persistent.", member_symbols())
    store = complete(SOURCE, "    store.g", member_symbols())

    assert [item.label for item in persistent.items] == ["score"]
    assert [item.label for item in store.items] == ["gold"]


def test_self_members_without_a_class_do_not_complete() -> None:
    assert complete(SOURCE, "    self.", member_symbols()).items == []


def test_member_completion_is_not_offered_inside_strings() -> None:
    assert complete(SOURCE, '    e "Player.h', member_symbols()).items == []


def extended_workspace() -> dict[str, list[Completion]]:
    return {
        "transform": [Completion("chapter_slide", "transform", "transform")],
        "style": [Completion("chapter_text", "style", "style")],
        "audio": [
            Completion(
                "audio/chapter.ogg",
                "audio",
                "audio file",
                insert_text='"audio/chapter.ogg"',
            )
        ],
    }


def test_statement_start_offers_builtin_classes_and_call_insertion() -> None:
    result = complete(SOURCE, "    Cha")
    character = next(item for item in result.items if item.label == "Character")
    assert character.insert_text == "Character()"


def test_jump_and_call_offer_expression_and_labels() -> None:
    assert "expression" in labels("    jump ")
    assert "expression" in labels("    call ")
    assert "screen" in labels("    call ")


def test_use_show_screen_and_hide_screen_offer_screens() -> None:
    for prefix in ("    use ", "    show screen ", "    hide screen "):
        assert {"main_menu", "preferences"} <= set(labels(prefix))


def test_show_expression_and_text_do_not_offer_images() -> None:
    assert complete(SOURCE, "    show expression ").items == []
    assert complete(SOURCE, "    show text ").items == []


def test_at_offers_user_and_builtin_transforms() -> None:
    source = (
        "transform chapter_slide:\n"
        "    xpos 0\n"
        "label start:\n"
        "    show eileen happy at chapter\n"
    )
    result = complete(source, "    show eileen happy at chapter", None, None, 3)
    assert [item.label for item in result.items] == ["chapter_slide"]
    assert result.replace_start == len("    show eileen happy at ")

    builtin = complete(SOURCE, "    show eileen happy at ")
    assert "left" in {item.label for item in builtin.items}
    assert "chapter_slide" in {
        item.label
        for item in complete(
            SOURCE,
            "    show eileen happy at ",
            extended_workspace(),
        ).items
    }


def test_with_offers_builtin_and_user_transitions() -> None:
    source = "define slow = Dissolve(1.0)\nlabel start:\n    with slo"
    result = complete(source, "    with slo", None, None, 2)
    assert [item.label for item in result.items] == ["slow"]

    builtin = complete(SOURCE, "    with ")
    assert {"Dissolve", "Fade", "None"} <= {item.label for item in builtin.items}


def test_audio_channels_assets_and_options() -> None:
    source = 'define audio.theme = "audio/theme.ogg"\n'
    channels = complete(source, "    play ", None, None, 1)
    assert {"music", "sound", "voice", "audio"} <= {
        item.label for item in channels.items
    }

    assets = complete(source, "    play music ", extended_workspace(), None, 1)
    labels = {item.label for item in assets.items}
    assert "audio.theme" in labels
    assert "audio/chapter.ogg" in labels
    assert {"loop", "noloop", "fadein", "volume"} <= labels

    stop = complete(source, "    stop music ", None, None, 1)
    assert "fadeout" in {item.label for item in stop.items}


def test_audio_namespace_completes_defined_variables() -> None:
    source = 'define audio.theme = "audio/theme.ogg"\n'
    result = complete(source, "    play music audio.th", None, None, 1)
    assert [item.label for item in result.items] == ["theme"]
    assert result.items[0].insert_text == "audio.theme"


def test_screen_body_elements_properties_values_and_actions() -> None:
    source = (
        "screen main_menu():\n"
        "    vbox:\n"
        '        text "Hello" xa|\n'
        '        textbutton "Start" act|\n'
        '        text "Child" at |\n'
    )
    assert {"xalign", "xanchor"} <= set(labels_at(source.replace("|", "", 0)))
    marked_text = source.replace("|", "", 2).replace(
        '        textbutton "Start" act\n',
        '        textbutton "Start" act|\n',
    )
    assert {"action", "activate_sound"} <= set(labels_at(marked_text))

    marked_at = 'screen main_menu():\n    text "Child" at |\n'
    assert "left" in set(labels_at(marked_at))


def test_screen_blank_line_offers_elements_inside_the_screen() -> None:
    marked = "screen main_menu():\n    vbox:\n        |\n"
    assert {"text", "textbutton", "add"} <= set(labels_at(marked))


def test_screen_property_value_completion() -> None:
    marked = 'screen main_menu():\n    text "Hi" xalign |\n'
    assert {"0.0", "0.5", "1.0"} <= set(labels_at(marked))

    action = 'screen main_menu():\n    textbutton "Go" action |\n'
    assert "Return" in set(labels_at(action))


def test_screen_values_offer_images_for_displayable_properties() -> None:
    marked = "screen main_menu():\n    frame:\n        background |\n"
    labels = set(labels_at(marked))
    assert "None" in labels


def test_dialogue_attributes_come_from_the_character_image_tag() -> None:
    source = (
        'define e = Character("Eileen", image="eileen")\n'
        'image eileen happy = "happy.png"\n'
        'image eileen sad = "sad.png"\n'
        "label start:\n"
        "    e ha|\n"
    )
    position = source.index("|")
    document = source[:position] + source[position + 1 :]
    line = document.count("\n", 0, position)
    prefix = document[document.rfind("\n", 0, position) + 1 : position]
    result = complete(document, prefix, None, None, line)
    assert [item.label for item in result.items] == ["happy"]


def test_python_expression_contexts() -> None:
    assert "and" in labels("    $ ")
    assert "Character" in labels("    $ Cha")
    assert "True" in labels("    if ")
    assert "Define" not in labels("    if ")


def test_python_block_offers_keywords_and_builtins() -> None:
    marked = "python:\n    re|\n"
    assert "return" in set(labels_at(marked))


def test_define_assignment_offers_builtins() -> None:
    assert "Character" in labels("    define x = Cha")
    assert "Character" in labels("    default x = Cha")


def test_api_namespace_completion_inserts_the_child_segment() -> None:
    music = complete(SOURCE, "    $ renpy.music.")
    assert {"play", "queue", "register_channel"} <= {item.label for item in music.items}

    root = complete(SOURCE, "    $ renpy.")
    assert {"music", "audio", "call"} <= {item.label for item in root.items}
    music_item = next(item for item in root.items if item.label == "music")
    assert music_item.insert_text == ""


def test_namespace_completion_is_filtered_and_avoids_strings() -> None:
    assert "afm_bonus" in {
        item.label for item in complete(SOURCE, "    $ config.afm").items
    }
    assert complete(SOURCE, '    $ "renpy.').items == []


def test_completion_filters_a_large_workspace_quickly() -> None:
    import time

    workspace = {
        "label": [
            Completion(f"chapter_{index}", "label", "label") for index in range(5000)
        ]
    }
    started = time.perf_counter()
    result = complete(SOURCE, "    jump chapter_4999", workspace)
    elapsed = time.perf_counter() - started

    assert [item.label for item in result.items] == ["chapter_4999"]
    assert elapsed < 1.0


def test_at_inside_dialogue_text_does_not_offer_transforms() -> None:
    assert complete(SOURCE, '    e "meet me at "').items == []


def _markdown_backticks_balanced(text: str) -> bool:
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.count("`") % 2:
            return False
    return not in_fence


def test_generated_documentation_is_valid_markdown() -> None:
    documents = [_builtin_documentation(item) for item in api.iter_builtins()]
    documents.extend(item.documentation for item in _KEYWORDS)

    for text in documents:
        assert text
        assert _markdown_backticks_balanced(text), text
        assert ":doc:`" not in text
        assert ":ref:`" not in text


def test_builtin_documentation_sanitizes_sphinx_roles() -> None:
    documentation = next(
        _builtin_documentation(item)
        for item in api.iter_builtins()
        if item.name == "config.scene"
    )

    assert ":ref:`" not in documentation
    assert "scene statement <scene-statement>" not in documentation
    assert "the scene\nstatement." in documentation


def test_builtin_documentation_strips_unmatched_backticks() -> None:
    documentation = next(
        _builtin_documentation(item)
        for item in api.iter_builtins()
        if item.name == "config.bottom_layers"
    )

    assert "config.layers`" not in documentation
    assert "in config.layers or config.top_layers." in documentation


def test_automatic_assets_can_be_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from renpy_language_server import server  # pyright: ignore[reportPrivateUsage]
    from renpy_language_server.assets import Asset
    from renpy_language_server.index import WorkspaceIndex

    class FakeAssets:
        def images(self) -> list[Asset]:
            return [Asset("image", "bg room", Path("/project/images/bg room.png"))]

        def audio(self) -> list[Asset]:
            return [Asset("audio", "theme", Path("/project/audio/theme.ogg"))]

    monkeypatch.setattr(server, "_assets", FakeAssets())
    monkeypatch.setattr(server, "_index", WorkspaceIndex())

    without_assets = server._completion_symbols(  # pyright: ignore[reportPrivateUsage]
        include_assets=False
    )
    assert without_assets["image"] == []
    assert without_assets["audio"] == []

    with_assets = server._completion_symbols(  # pyright: ignore[reportPrivateUsage]
        include_assets=True
    )
    assert [item.label for item in with_assets["image"]] == ["bg room"]
    assert [item.label for item in with_assets["audio"]] == ["theme"]
