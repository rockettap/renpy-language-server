"""Position-encoding tests for non-ASCII and CRLF text."""

from pygls.workspace.text_document import TextDocument

from renpy_language_server.index import utf16_length
from renpy_language_server.positions import client_position


def test_utf16_length_for_wide_characters() -> None:
    assert utf16_length("abc") == 3
    assert utf16_length("Привіт") == 6
    assert utf16_length("😀") == 2
    assert utf16_length("a😀b") == 4


def testclient_position_uses_utf16_units() -> None:
    source = "a😀b\n"
    doc = TextDocument("file:///x.rpy", source=source)

    # Python offset 2 is right after the emoji, which is UTF-16 column 3.
    assert client_position(doc, source, 0, 2) == doc.client_position_at_offset(2)
    assert client_position(doc, source, 0, 2).character == 3


def testclient_position_at_the_end_of_a_file_without_newline() -> None:
    source = 'label start:\n    e "Привіт"'
    doc = TextDocument("file:///x.rpy", source=source)

    position = client_position(doc, source, 1, len('    e "Привіт"'))
    assert position.line == 1
    assert position.character == utf16_length('    e "Привіт"')


def test_crlf_offsets_are_converted() -> None:
    source = 'label start:\r\n    e "Hi."\r\n'
    doc = TextDocument("file:///x.rpy", source=source)

    assert client_position(doc, source, 1, 4).line == 1
    assert client_position(doc, source, 1, 4).character == 4
