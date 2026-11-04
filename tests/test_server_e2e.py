"""End-to-end test: start the real server and format a document over stdio."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import IO, Any, cast

from renpy_language_server.edits import Edit, apply_edits


def _frame(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def _send(stream: IO[bytes], payload: dict[str, Any]) -> None:
    stream.write(_frame(payload))
    stream.flush()


def _read(stream: IO[bytes]) -> dict[str, Any]:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            raise EOFError("server closed stdout")
        if line in (b"\r\n", b"\n"):
            break
        name, value = line.decode("ascii").split(":", 1)
        headers[name.lower()] = value.strip()

    length = int(headers["content-length"])
    return json.loads(stream.read(length))


def _response(stream: IO[bytes], request_id: int) -> dict[str, Any]:
    """Read messages until the response for ``request_id`` arrives."""
    while True:
        message = _read(stream)
        if message.get("id") == request_id:
            return message


def _notification(stream: IO[bytes], method: str) -> dict[str, Any]:
    """Read messages until a notification with ``method`` arrives."""
    while True:
        message = _read(stream)
        if message.get("method") == method:
            return message


def _edits_from_response(message: dict[str, Any]) -> list[Edit]:
    result = message.get("result")
    if not isinstance(result, list):
        return []

    edits: list[Edit] = []
    for raw in cast(list[dict[str, Any]], result):
        text_range = cast(dict[str, Any], raw["range"])
        start = cast(dict[str, Any], text_range["start"])
        end = cast(dict[str, Any], text_range["end"])
        edits.append(
            Edit(
                start_line=int(start["line"]),
                start_char=int(start["character"]),
                end_line=int(end["line"]),
                end_char=int(end["character"]),
                new_text=cast(str, raw["newText"]),
            )
        )
    return edits


def test_format_over_stdio(tmp_path: Path) -> None:
    source = 'label start:\n  e "Hello!"\n  $ pv = Character("A", color = "#fff")\n'
    expected = 'label start:\n    e "Hello!"\n    $ pv = Character("A", color="#fff")\n'
    document = tmp_path / "script.rpy"
    document.write_text(source, encoding="utf-8")
    uri = document.as_uri()
    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        initialized = _response(process.stdout, 1)
        assert "result" in initialized, initialized

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "workspace/didChangeConfiguration",
                "params": {"settings": {}},
            },
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/formatting",
                "params": {
                    "textDocument": {"uri": uri},
                    "options": {"tabSize": 4, "insertSpaces": True},
                },
            },
        )

        edits = _edits_from_response(_response(process.stdout, 2))
        assert edits
        assert apply_edits(source, edits) == expected

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 3)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()

    log = log_path.read_text(encoding="utf-8")
    assert "starting (stdio)" in log
    assert "Ignoring notification" not in log
    assert "Sending data" not in log


def test_folding_over_stdio(tmp_path: Path) -> None:
    source = (
        "label start:\n"
        "    menu:\n"
        '        "1":\n'
        '            e "First."\n'
        '        "2":\n'
        '            e "Second."\n'
    )
    document = tmp_path / "script.rpy"
    document.write_text(source, encoding="utf-8")
    uri = document.as_uri()
    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        _response(process.stdout, 1)
        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/foldingRange",
                "params": {"textDocument": {"uri": uri}},
            },
        )

        result = _response(process.stdout, 2).get("result")
        assert isinstance(result, list), result
        assert [
            (item["startLine"], item["endLine"])
            for item in cast(list[dict[str, int]], result)
        ] == [(0, 5), (1, 5), (2, 3), (4, 5)]

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 3)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()

    log = log_path.read_text(encoding="utf-8")
    assert "starting (stdio)" in log
    assert "Ignoring notification" not in log
    assert "Sending data" not in log


def test_completion_over_stdio(tmp_path: Path) -> None:
    (tmp_path / "game" / "images").mkdir(parents=True)
    (tmp_path / "game" / "images" / "eileen smile.png").write_bytes(b"")
    source = (
        'define e = Character("Eileen")\n'
        'image eileen happy = "eileen.png"\n'
        "label start:\n"
        "    show e\n"
        "    Cha\n"
        "    lab\n"
    )
    document = tmp_path / "script.rpy"
    document.write_text(source, encoding="utf-8")
    uri = document.as_uri()
    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        _response(process.stdout, 1)
        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 3, "character": 10},
                },
            },
        )

        result = _response(process.stdout, 2).get("result")
        assert isinstance(result, list), result
        assert result
        labels = [
            cast(str, entry["label"]) for entry in cast(list[dict[str, Any]], result)
        ]
        assert "eileen smile" in labels

        item = cast(dict[str, Any], result[0])
        assert item["label"] == "eileen happy"
        text_edit = cast(dict[str, Any], item["textEdit"])
        text_range = cast(dict[str, Any], text_edit["range"])
        assert text_range["start"] == {"line": 3, "character": 9}
        assert text_range["end"] == {"line": 3, "character": 10}
        assert text_edit["newText"] == "eileen happy"

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 4, "character": 7},
                },
            },
        )
        builtins = cast(list[dict[str, Any]], _response(process.stdout, 3)["result"])
        character = next(item for item in builtins if item["label"] == "Character")
        assert character["textEdit"]["newText"] == "Character()"
        documentation = cast(dict[str, Any], character["documentation"])
        assert documentation["kind"] == "markdown"
        assert documentation["value"].count("```renpy") == 1
        assert "Character" in documentation["value"]

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 5, "character": 7},
                },
            },
        )
        keywords = cast(list[dict[str, Any]], _response(process.stdout, 4)["result"])
        label = next(item for item in keywords if item["label"] == "label")
        keyword_docs = cast(dict[str, Any], label["documentation"])
        assert keyword_docs["kind"] == "markdown"
        assert "`label name:`" in keyword_docs["value"]

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 5, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 5)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()

    log = log_path.read_text(encoding="utf-8")
    assert "starting (stdio)" in log
    assert "Ignoring notification" not in log
    assert "Sending data" not in log


def test_navigation_diagnostics_and_range_over_stdio(tmp_path: Path) -> None:
    source = (
        "label start:\n"
        "    jump chapter_one\n"
        "\n"
        "label a:\n"
        '  e "A"\n'
        "\n"
        "label b:\n"
        '    e "B"\n'
    )
    script = tmp_path / "script.rpy"
    script.write_text(source, encoding="utf-8")
    other = tmp_path / "other.rpy"
    other.write_text("label chapter_one:\n    return\n", encoding="utf-8")
    uri = script.as_uri()
    other_uri = other.as_uri()

    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        _response(process.stdout, 1)
        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )

        diagnostics = _notification(process.stdout, "textDocument/publishDiagnostics")
        params = cast(dict[str, Any], diagnostics["params"])
        codes = [
            item["code"] for item in cast(list[dict[str, Any]], params["diagnostics"])
        ]
        assert codes == ["renpy-language-server.indentation"]

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/documentSymbol",
                "params": {"textDocument": {"uri": uri}},
            },
        )
        symbols = cast(list[dict[str, Any]], _response(process.stdout, 2)["result"])
        assert [item["name"] for item in symbols] == ["start", "a", "b"]

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "textDocument/definition",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 1, "character": 10},
                },
            },
        )
        locations = cast(list[dict[str, Any]], _response(process.stdout, 3)["result"])
        assert len(locations) == 1
        assert locations[0]["uri"] == other_uri
        assert locations[0]["range"]["start"] == {"line": 0, "character": 6}

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 1, "character": 9},
                },
            },
        )
        items = cast(list[dict[str, Any]], _response(process.stdout, 4)["result"])
        assert "chapter_one" in {item["label"] for item in items}

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "textDocument/rangeFormatting",
                "params": {
                    "textDocument": {"uri": uri},
                    "range": {
                        "start": {"line": 4, "character": 0},
                        "end": {"line": 4, "character": 10},
                    },
                    "options": {"tabSize": 4, "insertSpaces": True},
                },
            },
        )
        edits = _edits_from_response(_response(process.stdout, 5))
        result = apply_edits(source, edits)
        assert result == source.replace('  e "A"', '    e "A"')

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 6, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 6)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()

    log = log_path.read_text(encoding="utf-8")
    assert "starting (stdio)" in log
    assert "Ignoring notification" not in log
    assert "Sending data" not in log


def test_local_labels_over_stdio(tmp_path: Path) -> None:
    source = (
        "label chapter:\n"
        "    jump .intro\n"
        "\n"
        "label other:\n"
        "    jump .intro\n"
        "\n"
        "label chapter.intro:\n"
        "    return\n"
        "\n"
        "label other.intro:\n"
        "    return\n"
    )
    document = tmp_path / "script.rpy"
    document.write_text(source, encoding="utf-8")
    uri = document.as_uri()

    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        _response(process.stdout, 1)
        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/documentSymbol",
                "params": {"textDocument": {"uri": uri}},
            },
        )
        symbols = cast(list[dict[str, Any]], _response(process.stdout, 2)["result"])
        assert [item["name"] for item in symbols] == [
            "chapter",
            "other",
            "chapter.intro",
            "other.intro",
        ]
        local = symbols[2]
        assert local["selectionRange"] == {
            "start": {"line": 6, "character": 6},
            "end": {"line": 6, "character": 19},
        }

        for request_id, line, expected_line in ((3, 1, 6), (4, 4, 9)):
            _send(
                process.stdin,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "textDocument/definition",
                    "params": {
                        "textDocument": {"uri": uri},
                        "position": {"line": line, "character": 10},
                    },
                },
            )
            locations = cast(
                list[dict[str, Any]],
                _response(process.stdout, request_id)["result"],
            )
            assert len(locations) == 1
            assert locations[0]["range"]["start"] == {
                "line": expected_line,
                "character": 6,
            }

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 5, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 5)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()

    log = log_path.read_text(encoding="utf-8")
    assert "starting (stdio)" in log
    assert "Ignoring notification" not in log
    assert "Sending data" not in log


def test_hover_over_stdio(tmp_path: Path) -> None:
    (tmp_path / "game" / "images").mkdir(parents=True)
    (tmp_path / "game" / "images" / "bg room.png").write_bytes(b"")
    (tmp_path / "other.rpy").write_text(
        "# Other label.\nlabel other:\n    return\n", encoding="utf-8"
    )
    source = "label start:\n    jump other\n    show bg room\n    renpy.pause(1.0)\n"
    document = tmp_path / "script.rpy"
    document.write_text(source, encoding="utf-8")
    uri = document.as_uri()
    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        _response(process.stdout, 1)
        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )

        cases = (
            (2, 1, 10, "Other label."),
            (3, 2, 11, "bg room"),
            (4, 3, 9, "renpy.pause"),
        )
        for request_id, line, character, expected in cases:
            _send(
                process.stdin,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "textDocument/hover",
                    "params": {
                        "textDocument": {"uri": uri},
                        "position": {"line": line, "character": character},
                    },
                },
            )
            result = _response(process.stdout, request_id)["result"]
            assert isinstance(result, dict), result
            contents = cast(dict[str, Any], result["contents"])
            assert contents["kind"] == "markdown"
            assert expected in cast(str, contents["value"])

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 5, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 5)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()

    log = log_path.read_text(encoding="utf-8")
    assert "starting (stdio)" in log
    assert "Ignoring notification" not in log
    assert "Sending data" not in log


def test_rename_over_stdio(tmp_path: Path) -> None:
    source = "label start:\n    jump target\n\nlabel target:\n    return\n"
    document = tmp_path / "script.rpy"
    document.write_text(source, encoding="utf-8")
    uri = document.as_uri()
    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        _response(process.stdout, 1)
        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/prepareRename",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 3, "character": 8},
                },
            },
        )
        prepared = _response(process.stdout, 2)["result"]
        assert prepared == {
            "start": {"line": 3, "character": 6},
            "end": {"line": 3, "character": 12},
        }

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "textDocument/rename",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 3, "character": 8},
                    "newName": "finish",
                },
            },
        )
        changes = cast(dict[str, Any], _response(process.stdout, 3)["result"])[
            "changes"
        ]
        assert changes == {
            uri: [
                {
                    "range": {
                        "start": {"line": 1, "character": 9},
                        "end": {"line": 1, "character": 15},
                    },
                    "newText": "finish",
                },
                {
                    "range": {
                        "start": {"line": 3, "character": 6},
                        "end": {"line": 3, "character": 12},
                    },
                    "newText": "finish",
                },
            ]
        }

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "textDocument/documentHighlight",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 3, "character": 8},
                },
            },
        )
        assert _response(process.stdout, 4)["result"] == [
            {
                "range": {
                    "start": {"line": 1, "character": 9},
                    "end": {"line": 1, "character": 15},
                },
                "kind": 2,
            },
            {
                "range": {
                    "start": {"line": 3, "character": 6},
                    "end": {"line": 3, "character": 12},
                },
                "kind": 3,
            },
        ]

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 5, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 5)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()

    log = log_path.read_text(encoding="utf-8")
    assert "starting (stdio)" in log
    assert "Ignoring notification" not in log
    assert "Sending data" not in log


def test_references_over_stdio(tmp_path: Path) -> None:
    source = "label start:\n    jump target\n"
    (tmp_path / "script.rpy").write_text(source, encoding="utf-8")
    other = tmp_path / "other.rpy"
    other.write_text("label target:\n    return\n", encoding="utf-8")
    uri = (tmp_path / "script.rpy").as_uri()
    other_uri = other.as_uri()

    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        initialized = _response(process.stdout, 1)
        assert initialized["result"]["capabilities"]["referencesProvider"] is True

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/references",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 1, "character": 10},
                    "context": {"includeDeclaration": True},
                },
            },
        )
        found = cast(list[dict[str, Any]], _response(process.stdout, 2)["result"])
        assert [(item["uri"], item["range"]["start"]) for item in found] == [
            (other_uri, {"line": 0, "character": 6}),
            (uri, {"line": 1, "character": 9}),
        ]

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "textDocument/references",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 1, "character": 10},
                    "context": {"includeDeclaration": False},
                },
            },
        )
        found = cast(list[dict[str, Any]], _response(process.stdout, 3)["result"])
        assert [item["uri"] for item in found] == [uri]

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 4)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()

    log = log_path.read_text(encoding="utf-8")
    assert "starting (stdio)" in log
    assert "Ignoring notification" not in log
    assert "Sending data" not in log


def test_expanded_definition_over_stdio(tmp_path: Path) -> None:
    source = (
        "screen stats():\n"
        "    pass\n"
        "\n"
        "transform bounce:\n"
        "    xoffset 0\n"
        "\n"
        "label start:\n"
        "    use stats\n"
        "    show e at bounce\n"
    )
    document = tmp_path / "script.rpy"
    document.write_text(source, encoding="utf-8")
    uri = document.as_uri()

    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        _response(process.stdout, 1)
        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )

        for request_id, line, character, expected_line in (
            (2, 7, 8, 0),
            (3, 8, 19, 3),
        ):
            _send(
                process.stdin,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "textDocument/definition",
                    "params": {
                        "textDocument": {"uri": uri},
                        "position": {"line": line, "character": character},
                    },
                },
            )
            found = cast(
                list[dict[str, Any]], _response(process.stdout, request_id)["result"]
            )
            assert len(found) == 1
            assert found[0]["uri"] == uri
            assert found[0]["range"]["start"]["line"] == expected_line

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 4)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()

    log = log_path.read_text(encoding="utf-8")
    assert "starting (stdio)" in log
    assert "Ignoring notification" not in log
    assert "Sending data" not in log


def test_signature_help_over_stdio(tmp_path: Path) -> None:
    source = "label start:\n    renpy.pause(1.0, predict=True)\n"
    document = tmp_path / "script.rpy"
    document.write_text(source, encoding="utf-8")
    uri = document.as_uri()
    character = source.splitlines()[1].index("predict")

    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        initialized = _response(process.stdout, 1)
        assert "signatureHelpProvider" in initialized["result"]["capabilities"]

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/signatureHelp",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 1, "character": character},
                },
            },
        )
        result = cast(dict[str, Any], _response(process.stdout, 2)["result"])
        assert result["activeParameter"] == 1
        signature = cast(dict[str, Any], result["signatures"][0])
        assert signature["label"].startswith("renpy.pause(")
        assert [item["label"] for item in signature["parameters"]] == [
            "delay",
            "predict",
            "modal",
            "hard",
        ]

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 3)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()

    log = log_path.read_text(encoding="utf-8")
    assert "starting (stdio)" in log
    assert "Ignoring notification" not in log
    assert "Sending data" not in log


def test_python_symbols_and_definition_over_stdio(tmp_path: Path) -> None:
    source = (
        "init python:\n"
        "    class Player:\n"
        "        hp = 10\n"
        "\n"
        "        def hurt(self):\n"
        "            self.hp -= 1\n"
        "\n"
        "label start:\n"
        "    $ Player.hp = 1\n"
    )
    document = tmp_path / "script.rpy"
    document.write_text(source, encoding="utf-8")
    uri = document.as_uri()
    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        _response(process.stdout, 1)
        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/documentSymbol",
                "params": {"textDocument": {"uri": uri}},
            },
        )
        symbols = cast(list[dict[str, Any]], _response(process.stdout, 2).get("result"))
        assert [(item["name"], item["kind"]) for item in symbols] == [
            ("Player", 5),
            ("start", 12),
        ]
        assert [(item["name"], item["kind"]) for item in symbols[0]["children"]] == [
            ("hp", 8),
            ("hurt", 6),
        ]

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "textDocument/definition",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 8, "character": 14},
                },
            },
        )
        locations = cast(
            list[dict[str, Any]], _response(process.stdout, 3).get("result")
        )
        assert [
            (item["uri"], item["range"]["start"]["line"]) for item in locations
        ] == [(uri, 2)]

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 4)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()

    log = log_path.read_text(encoding="utf-8")
    assert "starting (stdio)" in log
    assert "Ignoring notification" not in log
    assert "Sending data" not in log


def test_workspace_diagnostics_cover_closed_files(tmp_path: Path) -> None:
    script = tmp_path / "bad.rpy"
    script.write_text("label start:\n\treturn\n", encoding="utf-8")
    clean = tmp_path / "clean.rpy"
    clean.write_text("label other:\n    return\n", encoding="utf-8")
    script_uri = script.as_uri()

    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                    "initializationOptions": {
                        "renpyLanguageServer": {
                            "diagnostics_mode": "workspace",
                            "diagnostic_rules": {"tabs": "warning"},
                        }
                    },
                },
            },
        )
        _response(process.stdout, 1)
        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )

        published: dict[str, list[str]] = {}
        expected_uris = {script_uri, clean.as_uri()}
        while not expected_uris <= published.keys():
            message = _read(process.stdout)
            if message.get("method") != "textDocument/publishDiagnostics":
                continue
            params = cast(dict[str, Any], message["params"])
            uri = cast(str, params["uri"])
            published[uri] = [
                cast(str, item["code"])
                for item in cast(list[dict[str, Any]], params["diagnostics"])
            ]

        assert published[script_uri] == ["renpy-language-server.tabs"]
        assert published[clean.as_uri()] == []

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 2)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()


def test_semantic_tokens_over_stdio(tmp_path: Path) -> None:
    source = (
        'define e = Character("Eileen", color="#c8ffc8")\nlabel start:\n    return\n'
    )
    document = tmp_path / "script.rpy"
    document.write_text(source, encoding="utf-8")
    uri = document.as_uri()
    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "initializationOptions": {"semantic_tokens": True},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        initialized = _response(process.stdout, 1)
        capabilities = cast(dict[str, Any], initialized["result"]["capabilities"])
        semantic = cast(dict[str, Any], capabilities["semanticTokensProvider"])
        assert semantic["legend"]["tokenTypes"][0] == "class"

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/semanticTokens/full",
                "params": {"textDocument": {"uri": uri}},
            },
        )
        tokens = cast(dict[str, Any], _response(process.stdout, 2)["result"])
        assert tokens["data"]

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 3)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()

    log = log_path.read_text(encoding="utf-8")
    assert "starting (stdio)" in log
    assert "Ignoring notification" not in log
    assert "Sending data" not in log


def test_range_formatting_does_not_split_multiline_strings(tmp_path: Path) -> None:
    source = "label start:\n    e 'first\nsecond'\n    e 'single'\n"
    document = tmp_path / "script.rpy"
    document.write_text(source, encoding="utf-8")
    uri = document.as_uri()
    log_path = tmp_path / "server.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    stdin = process.stdin
    stdout = process.stdout

    try:
        _send(
            stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        _response(stdout, 1)
        _send(
            stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )

        def range_edits(request_id: int, start: int, end: int) -> list[Edit]:
            _send(
                stdin,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "textDocument/rangeFormatting",
                    "params": {
                        "textDocument": {"uri": uri},
                        "range": {
                            "start": {"line": start, "character": 0},
                            "end": {"line": end, "character": 0},
                        },
                        "options": {"tabSize": 4, "insertSpaces": True},
                    },
                },
            )
            return _edits_from_response(_response(stdout, request_id))

        # Only the opening line of the multi-line literal: both delimiters are
        # not in range, so the literal must stay untouched instead of being
        # left with one double quote and one single quote.
        assert apply_edits(source, range_edits(2, 1, 1)) == source

        # Both delimiter lines are in range: the literal converts atomically.
        converted = apply_edits(source, range_edits(3, 1, 2))
        assert converted == ("label start:\n    e \"first\nsecond\"\n    e 'single'\n")

        _send(
            stdin,
            {"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": None},
        )
        _response(stdout, 4)
        _send(stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()


def test_workspace_symbols_over_stdio(tmp_path: Path) -> None:
    (tmp_path / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    other = tmp_path / "other.rpy"
    other.write_text("label chapter_two:\n    return\n", encoding="utf-8")
    log_file = (tmp_path / "server.log").open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        _response(process.stdout, 1)
        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "workspace/symbol",
                "params": {"query": "chapter"},
            },
        )
        symbols = cast(list[dict[str, Any]], _response(process.stdout, 2)["result"])
        assert [item["name"] for item in symbols] == ["chapter_two"]
        assert symbols[0]["location"]["uri"] == other.as_uri()

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 3)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()


def test_code_actions_over_stdio(tmp_path: Path) -> None:
    source = "label start:\n    $ if a = 1:\n        pass\n"
    document = tmp_path / "script.rpy"
    document.write_text(source, encoding="utf-8")
    uri = document.as_uri()
    log_file = (tmp_path / "server.log").open("wb")
    env = os.environ.copy()
    env.pop("RENPY_LANGUAGE_SERVER_DEBUG", None)

    process = subprocess.Popen(
        [sys.executable, "-m", "renpy_language_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "rootUri": tmp_path.as_uri(),
                    "capabilities": {},
                    "initializationOptions": {
                        "diagnostic_rules": {"comparison": "warning"}
                    },
                    "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "tmp"}],
                },
            },
        )
        _response(process.stdout, 1)
        _send(
            process.stdin,
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        )
        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "renpy",
                        "version": 1,
                        "text": source,
                    }
                },
            },
        )

        _send(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/codeAction",
                "params": {
                    "textDocument": {"uri": uri},
                    "range": {
                        "start": {"line": 1, "character": 0},
                        "end": {"line": 1, "character": 20},
                    },
                    "context": {"diagnostics": []},
                },
            },
        )
        actions = cast(list[dict[str, Any]], _response(process.stdout, 2)["result"])
        assert [action["title"] for action in actions] == ['Replace "=" with "=="']

        _send(
            process.stdin,
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None},
        )
        _response(process.stdout, 3)
        _send(process.stdin, {"jsonrpc": "2.0", "method": "exit", "params": None})
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log_file.close()
