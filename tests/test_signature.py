"""Tests for signature help."""

from renpy_language_server.index import WorkspaceIndex
from renpy_language_server.signature import signature_at


def _index(*sources: str) -> WorkspaceIndex:
    workspace = WorkspaceIndex()
    for number, source in enumerate(sources):
        workspace.update(f"file:///script{number}.rpy", source)
    return workspace


def _signature(source: str, line: int, character: int):
    return signature_at(source, line, character, _index(source))


def _line(source: str, number: int) -> str:
    return source.splitlines()[number]


def test_builtin_signature_and_active_parameter() -> None:
    source = "label start:\n    renpy.pause(1.0, predict=True)\n"
    character = _line(source, 1).index("predict")

    help = _signature(source, 1, character)
    assert help is not None
    assert help.active_parameter == 1
    signature = help.signatures[0]
    assert (
        signature.label
        == "renpy.pause(delay=None, *, predict=False, modal=True, hard=False)"
    )
    assert [item.label for item in signature.parameters or []] == [
        "delay",
        "predict",
        "modal",
        "hard",
    ]


def test_commas_inside_strings_do_not_advance_the_parameter() -> None:
    source = 'label start:\n    renpy.pause("a,b", predict=True)\n'
    character = _line(source, 1).index("predict")

    help = _signature(source, 1, character)
    assert help is not None
    assert help.active_parameter == 1


def test_nested_calls_use_the_innermost_open_paren() -> None:
    source = (
        'label start:\n    renpy.pause(Character("x", color="#fff"), predict=True)\n'
    )
    line = _line(source, 1)

    outer = _signature(source, 1, line.index("predict"))
    assert outer is not None
    assert outer.signatures[0].label.startswith("renpy.pause(")
    assert outer.active_parameter == 1

    inner = _signature(source, 1, line.index("color"))
    assert inner is not None
    assert inner.signatures[0].label == "Character(name=..., kind=adv, **args)"
    assert inner.active_parameter == 1


def test_user_label_parameters() -> None:
    source = (
        "label chapter_one(a, b=1):\n"
        "    return\n"
        "\n"
        "label start:\n"
        "    call chapter_one(2, 3)\n"
    )

    help = _signature(source, 4, _line(source, 4).index("3"))
    assert help is not None
    assert help.active_parameter == 1
    signature = help.signatures[0]
    assert signature.label == "chapter_one(a, b=1)"
    assert [item.label for item in signature.parameters or []] == ["a", "b"]


def test_user_screen_parameters_after_use() -> None:
    source = (
        "screen stats(title, subtitle=None):\n"
        "    pass\n"
        "\n"
        "label start:\n"
        '    use stats("Hi", "There")\n'
    )

    help = _signature(source, 4, _line(source, 4).index("There"))
    assert help is not None
    assert help.active_parameter == 1
    assert help.signatures[0].label == "stats(title, subtitle=None)"


def test_multi_line_calls_track_the_active_parameter() -> None:
    source = (
        "label start:\n    renpy.pause(\n        1.0,\n        predict=True,\n    )\n"
    )

    help = _signature(source, 3, _line(source, 3).index("predict"))
    assert help is not None
    assert help.signatures[0].label.startswith("renpy.pause(")
    assert help.active_parameter == 1


def test_no_signature_without_a_known_call() -> None:
    source = (
        "label start:\n"
        "    if (a, b):\n"
        "        pass\n"
        "    call missing(\n"
        "    renpy.pause\n"
    )
    index = _index(source)

    assert signature_at(source, 1, _line(source, 1).index("b"), index) is None
    assert signature_at(source, 3, _line(source, 3).index("(") + 1, index) is None
    assert signature_at(source, 4, len(_line(source, 4)), index) is None


CLASS_SOURCE = """\
init python:
    class Hero:
        def __init__(self, name, hp=10):
            self.name = name

        def attack(self, target, damage=1):
            self.attack(1, 2)
            return damage

label start:
    $ h = Hero("Eileen", 20)
"""


def test_user_class_constructor_signature_strips_self() -> None:
    line = 10
    help = _signature(CLASS_SOURCE, line, _line(CLASS_SOURCE, line).index("20"))

    assert help is not None
    signature = help.signatures[0]
    assert signature.label == "Hero(name, hp=10)"
    assert [item.label for item in signature.parameters or []] == ["name", "hp"]
    assert help.active_parameter == 1


def test_self_method_signature_strips_self() -> None:
    line = 6
    help = _signature(CLASS_SOURCE, line, _line(CLASS_SOURCE, line).index("2)"))

    assert help is not None
    signature = help.signatures[0]
    assert signature.label == "attack(target, damage=1)"
    assert [item.label for item in signature.parameters or []] == ["target", "damage"]
    assert help.active_parameter == 1


def test_unknown_instance_methods_do_not_guess() -> None:
    source = "label start:\n    $ h = object()\n    $ h.attack(1, 2)\n"
    index = _index(source)

    assert signature_at(source, 2, _line(source, 2).index(", 2"), index) is None
