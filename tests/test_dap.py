"""Launch-only DAP adapter: configuration, SDK discovery and stdio sessions."""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any, cast

import pytest

from renpy_language_server import dap


def _frame(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def _send(stream: IO[bytes], payload: dict[str, Any]) -> None:
    stream.write(_frame(payload))
    stream.flush()


def _read(stream: IO[bytes]) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        name, value = line.decode("ascii").split(":", 1)
        headers[name.lower()] = value.strip()

    length = int(headers["content-length"])
    return cast(dict[str, Any], json.loads(stream.read(length)))


class _Client:
    """A running ``renpy-language-server dap`` process with timeout-guarded reads."""

    def __init__(self, tmp_path: Path, env: dict[str, str] | None = None) -> None:
        self._log = (tmp_path / "dap.log").open("wb")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "renpy_language_server", "dap"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log,
            env=env,
        )
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self._stdin = self.process.stdin
        self._messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._reader = threading.Thread(
            target=self._read_loop, args=(self.process.stdout,), daemon=True
        )
        self._reader.start()

    def _read_loop(self, stream: IO[bytes]) -> None:
        try:
            while True:
                message = _read(stream)
                self._messages.put(message)
                if message is None:
                    return
        except (EOFError, ValueError):
            self._messages.put(None)

    def send(self, payload: dict[str, Any]) -> None:
        _send(self._stdin, payload)

    def message(self, timeout: float = 15.0) -> dict[str, Any]:
        message = self._messages.get(timeout=timeout)
        if message is None:
            raise EOFError("renpy-language-server dap closed stdout")
        return message

    def until(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for a DAP message")
            message = self.message(remaining)
            if predicate(message):
                return message

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.send(
                    {
                        "seq": 999,
                        "type": "request",
                        "command": "disconnect",
                        "arguments": {},
                    }
                )
            except (BrokenPipeError, OSError):
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self._log.close()


def _make_sdk(tmp_path: Path) -> Path:
    sdk = tmp_path / "renpy-9.9.9-sdk"
    sdk.mkdir()
    (sdk / "renpy.py").write_text(
        "import json, os, sys, time\n"
        "args_path = os.environ.get('RENPY_TEST_ARGS')\n"
        "if args_path:\n"
        "    with open(args_path, 'w', encoding='utf-8') as fh:\n"
        "        json.dump(sys.argv[1:], fh)\n"
        "print('fake renpy running', flush=True)\n"
        "delay = os.environ.get('RENPY_TEST_SLEEP')\n"
        "if delay:\n"
        "    time.sleep(float(delay))\n",
        encoding="utf-8",
    )
    launcher = sdk / "renpy.sh"
    launcher.write_text(
        '#!/bin/sh\nexec python3 "$(dirname "$0")/renpy.py" "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return sdk


def _make_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "Ren'Py games" / "my game"
    script = project / "game" / "chapter one.rpy"
    script.parent.mkdir(parents=True)
    script.write_text("label start:\n    return\n", encoding="utf-8")
    return project, script


def _launch_arguments(
    sdk: Path,
    project: Path,
    *,
    warp: Path | None = None,
    args_file: Path | None = None,
    sleep: str | None = None,
) -> dict[str, Any]:
    env: dict[str, str] = {}
    if args_file is not None:
        env["RENPY_TEST_ARGS"] = str(args_file)
    if sleep is not None:
        env["RENPY_TEST_SLEEP"] = sleep
    arguments: dict[str, Any] = {
        "request": "launch",
        "sdk": str(sdk),
        "project": str(project),
        "command": "run",
        "args": ["--foo"],
        "env": env,
    }
    if warp is not None:
        arguments["warp"] = f"{warp}:12"
    return arguments


def test_parse_launch_defaults_and_unknown_keys() -> None:
    config = dap.parse_launch_config(
        {
            "request": "launch",
            "label": "Run game",
            "adapter": "renpy",
            "noDebug": True,
            "env": {"RENPY_SKIP_SPLASHSCREEN": "1"},
        }
    )
    assert config.command == "run"
    assert config.args == ()
    assert config.env["RENPY_SKIP_SPLASHSCREEN"] == "1"
    assert dap.parse_launch_config(None).sdk is None


def test_parse_launch_rejects_attach_and_bad_fields() -> None:
    with pytest.raises(dap.DapError, match='only the "launch" request'):
        dap.parse_launch_config({"request": "attach"})
    with pytest.raises(dap.DapError, match="args"):
        dap.parse_launch_config({"args": "--not-a-list"})
    with pytest.raises(dap.DapError, match="env"):
        dap.parse_launch_config({"env": {"X": 1}})
    with pytest.raises(dap.DapError, match="sdk"):
        dap.parse_launch_config({"sdk": 3})


def test_find_sdk_prefers_renpy_sdk_and_newest_directory(tmp_path: Path) -> None:
    home = tmp_path / "home"
    older = home / "renpy-8.9-sdk"
    newer = home / "Downloads" / "renpy-8.10-sdk"
    for directory in (older, newer):
        directory.mkdir(parents=True)
        (directory / "renpy.py").write_text("", encoding="utf-8")
    (older / "renpy.sh").write_text("", encoding="utf-8")

    found = dap.find_sdk(
        environ={"HOME": str(home)},
        home=home,
        roots=[home, home / "Downloads"],
    )
    assert found == newer

    configured = dap.find_sdk(
        environ={"RENPY_SDK": str(older / "renpy.sh")},
        home=home,
        roots=[],
    )
    assert configured == older


def test_find_sdk_reports_missing_and_invalid(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(dap.DapError, match="No Ren'Py SDK found"):
        dap.find_sdk(environ={"HOME": str(empty)}, home=empty, roots=[])
    with pytest.raises(dap.DapError, match="RENPY_SDK is set"):
        dap.find_sdk(
            environ={"RENPY_SDK": str(tmp_path / "nope")},
            home=empty,
            roots=[],
        )


def test_find_project_from_subdirectory_and_nested_folder(tmp_path: Path) -> None:
    project, script = _make_project(tmp_path)
    assert dap.find_project(script.parent) == project
    assert dap.find_project(script) == project
    assert dap.find_project(tmp_path) == project
    assert dap.find_project(tmp_path / "unrelated") is None


def test_normalize_warp_is_project_relative(tmp_path: Path) -> None:
    project, script = _make_project(tmp_path)
    assert dap.normalize_warp(f"{script}:42", project) == "game/chapter one.rpy:42"
    assert dap.normalize_warp("game/other.rpy:7", project) == "game/other.rpy:7"
    outside = tmp_path / "outside.rpy"
    assert dap.normalize_warp(f"{outside}:3", project) == f"{outside}:3"


def test_validate_warp_accepts_script_inside_game(tmp_path: Path) -> None:
    project, _ = _make_project(tmp_path)
    dap.validate_warp("game/chapter one.rpy:12", project)


def test_validate_warp_rejects_script_outside_game(tmp_path: Path) -> None:
    project, _ = _make_project(tmp_path)
    misplaced = project / "legacy" / "chapter one.rpy"
    misplaced.parent.mkdir(parents=True)
    misplaced.write_text("label start:\n    return\n", encoding="utf-8")

    with pytest.raises(dap.DapError, match="not loaded by Ren'Py"):
        dap.validate_warp("legacy/chapter one.rpy:2", project)


def test_validate_warp_suggests_a_game_script(tmp_path: Path) -> None:
    project, _ = _make_project(tmp_path)
    (project / "game" / "legacy_dlc_day_two.rpy").write_text(
        "label dlc_day_two:\n    return\n", encoding="utf-8"
    )

    with pytest.raises(dap.DapError) as error:
        dap.validate_warp("dlc_day_two.rpy:2", project)

    assert 'Did you mean "game/legacy_dlc_day_two.rpy"?' in str(error.value)


def test_validate_warp_rejects_missing_script(tmp_path: Path) -> None:
    project, _ = _make_project(tmp_path)
    with pytest.raises(dap.DapError, match="does not exist"):
        dap.validate_warp("game/missing.rpy:1", project)


def test_validate_warp_allows_archived_scripts(tmp_path: Path) -> None:
    project, _ = _make_project(tmp_path)
    (project / "game" / "archive.rpa").write_bytes(b"")
    dap.validate_warp("game/archived.rpy:10", project)


def test_validate_warp_requires_a_label_at_or_before_the_line(tmp_path: Path) -> None:
    project, _ = _make_project(tmp_path)
    script = project / "game" / "screen.rpy"
    script.write_text(
        "init python:\n    pass\n\n\nlabel later:\n    return\n",
        encoding="utf-8",
    )

    with pytest.raises(dap.DapError, match="no label at or before"):
        dap.validate_warp("game/screen.rpy:2", project)
    dap.validate_warp("game/screen.rpy:6", project)


def test_validate_warp_rejects_bad_values(tmp_path: Path) -> None:
    project, _ = _make_project(tmp_path)
    with pytest.raises(dap.DapError, match="expected"):
        dap.validate_warp("game/chapter one.rpy", project)
    with pytest.raises(dap.DapError, match="lines start at 1"):
        dap.validate_warp("game/chapter one.rpy:0", project)
    with pytest.raises(dap.DapError, match="outside the project"):
        dap.validate_warp(f"{tmp_path / 'outside.rpy'}:1", project)


def test_launch_reports_an_unloadable_warp_target(tmp_path: Path) -> None:
    sdk = _make_sdk(tmp_path)
    project, _ = _make_project(tmp_path)
    misplaced = project / "legacy" / "chapter one.rpy"
    misplaced.parent.mkdir(parents=True)
    misplaced.write_text("label start:\n    return\n", encoding="utf-8")
    client = _Client(tmp_path)
    try:
        client.send(
            {
                "seq": 1,
                "type": "request",
                "command": "launch",
                "arguments": _launch_arguments(sdk, project, warp=misplaced),
            }
        )
        response = client.until(lambda message: message.get("request_seq") == 1)
        assert not response["success"]
        assert "not loaded by Ren'Py" in response["message"]
    finally:
        client.close()


def test_resolve_launch_uses_sdk_project_warp_and_args(tmp_path: Path) -> None:
    sdk = _make_sdk(tmp_path)
    project, script = _make_project(tmp_path)
    launch = dap.resolve_launch(
        dap.LaunchConfig(
            sdk=str(sdk),
            project=str(project),
            warp=f"{script}:12",
            args=("--foo",),
            env={"RENPY_SKIP_SPLASHSCREEN": "1"},
        )
    )
    assert launch.project == project
    assert launch.args[-5:] == (
        str(project),
        "run",
        "--warp",
        "game/chapter one.rpy:12",
        "--foo",
    )
    assert launch.env == {"RENPY_SKIP_SPLASHSCREEN": "1"}


def test_resolve_launch_rejects_bad_sdk(tmp_path: Path) -> None:
    with pytest.raises(dap.DapError, match="does not look like a Ren'Py SDK"):
        dap.resolve_launch(dap.LaunchConfig(sdk=str(tmp_path / "nope")))


def test_launch_and_output_over_stdio(tmp_path: Path) -> None:
    sdk = _make_sdk(tmp_path)
    project, script = _make_project(tmp_path)
    args_file = tmp_path / "args.json"
    client = _Client(tmp_path)
    try:
        client.send(
            {
                "seq": 1,
                "type": "request",
                "command": "initialize",
                "arguments": {},
            }
        )
        capabilities = client.until(lambda message: message.get("request_seq") == 1)
        assert capabilities["success"]
        assert capabilities["body"]["supportsTerminateRequest"] is True

        client.send(
            {
                "seq": 2,
                "type": "request",
                "command": "launch",
                "arguments": _launch_arguments(
                    sdk, project, warp=script, args_file=args_file
                ),
            }
        )
        response = client.until(lambda message: message.get("request_seq") == 2)
        assert response["success"], response
        client.until(lambda message: message.get("event") == "process")

        seen_output = False
        seen_terminated = False
        while not (seen_output and seen_terminated):
            message = client.message()
            if message.get("event") == "output":
                seen_output = seen_output or (
                    "fake renpy running" in message["body"]["output"]
                )
            seen_terminated = seen_terminated or message.get("event") == "terminated"

        assert json.loads(args_file.read_text(encoding="utf-8")) == [
            str(project),
            "run",
            "--warp",
            "game/chapter one.rpy:12",
            "--foo",
        ]
    finally:
        client.close()


def test_terminate_stops_the_game(tmp_path: Path) -> None:
    sdk = _make_sdk(tmp_path)
    project, _ = _make_project(tmp_path)
    client = _Client(tmp_path)
    try:
        client.send(
            {
                "seq": 1,
                "type": "request",
                "command": "launch",
                "arguments": _launch_arguments(sdk, project, sleep="30"),
            }
        )
        assert client.until(lambda message: message.get("request_seq") == 1)["success"]
        client.until(lambda message: message.get("event") == "process")

        client.send(
            {
                "seq": 2,
                "type": "request",
                "command": "terminate",
                "arguments": {},
            }
        )
        seen_response = False
        seen_terminated = False
        while not (seen_response and seen_terminated):
            message = client.message(timeout=10)
            if message.get("request_seq") == 2:
                assert message["success"]
                seen_response = True
            seen_terminated = seen_terminated or message.get("event") == "terminated"
    finally:
        client.close()


def test_launch_errors_are_reported(tmp_path: Path) -> None:
    client = _Client(tmp_path)
    try:
        client.send(
            {
                "seq": 1,
                "type": "request",
                "command": "launch",
                "arguments": {"request": "launch", "sdk": str(tmp_path / "nope")},
            }
        )
        response = client.until(lambda message: message.get("request_seq") == 1)
        assert response["success"] is False
        assert "does not look like a Ren'Py SDK" in response["message"]

        client.send(
            {
                "seq": 2,
                "type": "request",
                "command": "attach",
                "arguments": {},
            }
        )
        attach = client.until(lambda message: message.get("request_seq") == 2)
        assert attach["success"] is False
        assert "not supported" in attach["message"]

        client.send(
            {
                "seq": 3,
                "type": "request",
                "command": "launch",
                "arguments": {"request": "launch", "args": "--bad"},
            }
        )
        bad = client.until(lambda message: message.get("request_seq") == 3)
        assert bad["success"] is False
        assert "args" in bad["message"]
    finally:
        client.close()


def test_breakpoints_are_reported_as_unsupported(tmp_path: Path) -> None:
    client = _Client(tmp_path)
    try:
        client.send(
            {
                "seq": 1,
                "type": "request",
                "command": "setBreakpoints",
                "arguments": {
                    "source": {"path": str(tmp_path / "game" / "script.rpy")},
                    "breakpoints": [{"line": 4}],
                },
            }
        )
        response = client.until(lambda message: message.get("request_seq") == 1)
        assert response["success"]
        breakpoint = response["body"]["breakpoints"][0]
        assert breakpoint["verified"] is False
        assert breakpoint["line"] == 4
    finally:
        client.close()
