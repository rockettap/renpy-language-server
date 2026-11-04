"""Launch-only Debug Adapter Protocol server.

``renpy-language-server dap`` speaks DAP over stdin/stdout. It resolves a Ren'Py SDK and a
project the same way the Zed tasks do, launches ``renpy.sh <project> run``
(optionally warped to a file and line), forwards the game's output to the
debug console and terminates it when the editor asks.

Breakpoints, stepping, stack traces and variable inspection are deliberately
not implemented in this version. Requests for them are answered with empty
results or a clear error instead of pretending to debug.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, cast

SDK_GLOB = re.compile(r"^renpy-.*-sdk$", re.IGNORECASE)
PROJECT_SCAN_SKIP = {"node_modules", "target", "cache", "saves", "tmp"}
TERMINAL_GRACE_SECONDS = 3.0


class DapError(Exception):
    """A user-facing launch configuration or environment problem."""


@dataclass(frozen=True)
class LaunchConfig:
    """The subset of a debug configuration the launch-only adapter understands."""

    sdk: str | None = None
    project: str | None = None
    warp: str | None = None
    command: str = "run"
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=lambda: dict[str, str]())


@dataclass(frozen=True)
class Launch:
    """A resolved command line for starting the game."""

    program: str
    args: tuple[str, ...]
    env: Mapping[str, str]
    project: Path


def _optional_string(arguments: Mapping[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DapError(f'invalid launch configuration: field "{key}" must be a string')
    value = value.strip()
    return value or None


def parse_launch_config(arguments: object) -> LaunchConfig:
    """Validate a DAP ``launch`` payload, ignoring unknown editor keys.

    Every field has a default, so a malformed field must fail instead of
    silently launching a different project or SDK.
    """

    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise DapError("invalid launch configuration: arguments must be an object")
    raw = cast(Mapping[str, Any], arguments)

    request = raw.get("request", "launch")
    if request != "launch":
        raise DapError(
            'only the "launch" request is supported; attaching to a running '
            "Ren'Py game is not implemented yet"
        )

    args_raw = raw.get("args", [])
    if not isinstance(args_raw, list):
        raise DapError(
            'invalid launch configuration: field "args" must be a list of strings'
        )
    args_values = cast(list[object], args_raw)
    if not all(isinstance(item, str) for item in args_values):
        raise DapError(
            'invalid launch configuration: field "args" must be a list of strings'
        )
    args = tuple(cast(list[str], args_values))

    env_raw = raw.get("env", {})
    if not isinstance(env_raw, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in cast(Mapping[object, object], env_raw).items()
    ):
        raise DapError(
            'invalid launch configuration: field "env" must be an object '
            "with string values"
        )
    env = dict(cast(Mapping[str, str], env_raw))

    command = _optional_string(raw, "command") or "run"
    return LaunchConfig(
        sdk=_optional_string(raw, "sdk"),
        project=_optional_string(raw, "project"),
        warp=_optional_string(raw, "warp"),
        command=command,
        args=args,
        env=env,
    )


def is_sdk_dir(path: Path) -> bool:
    """True if ``path`` is the SDK root (the one containing ``renpy.py``)."""

    return (path / "renpy.py").is_file()


def _normalize_sdk_path(raw: str) -> Path:
    """Accept either the SDK directory or a launcher inside it."""

    path = Path(raw).expanduser()
    if path.is_file():
        path = path.parent
    return path


def _version_key(name: str) -> tuple[int, ...]:
    """Natural ordering, so renpy-8.10 beats renpy-8.5."""

    keys: list[int] = []
    current: int | None = None
    for character in name:
        if character.isdigit():
            current = (current or 0) * 10 + int(character)
        elif current is not None:
            keys.append(current)
            current = None
    if current is not None:
        keys.append(current)
    return tuple(keys)


def find_sdk(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    roots: Sequence[Path] | None = None,
) -> Path:
    """Resolve the SDK from the configuration environment or common locations.

    Resolution order matches the Zed tasks: ``RENPY_SDK`` first, then
    ``renpy-*-sdk`` directories in the home directory, Documents, Downloads,
    Desktop, Applications and ``/Applications``, newest version first.
    """

    env = os.environ if environ is None else environ
    configured = env.get("RENPY_SDK")
    if configured:
        path = _normalize_sdk_path(configured)
        if is_sdk_dir(path):
            return path
        raise DapError(
            f"RENPY_SDK is set but '{path}' does not look like a Ren'Py SDK "
            "(no renpy.py inside)."
        )

    if home is None:
        raw_home = env.get("HOME") or env.get("USERPROFILE")
        if not raw_home:
            raise DapError(
                "No Ren'Py SDK found: HOME is not set and RENPY_SDK is empty."
            )
        home = Path(raw_home).expanduser()

    parents = (
        list(roots)
        if roots is not None
        else [
            home,
            home / "Documents",
            home / "Downloads",
            home / "Desktop",
            home / "Applications",
            Path("/Applications"),
        ]
    )
    candidates: list[Path] = []
    seen: set[Path] = set()
    for parent in parents:
        if parent in seen:
            continue
        seen.add(parent)
        try:
            entries = list(parent.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not SDK_GLOB.match(entry.name) or entry in candidates:
                continue
            if is_sdk_dir(entry):
                candidates.append(entry)

    if not candidates:
        raise DapError(
            'No Ren\'Py SDK found. Set "sdk" in the debug configuration, set '
            "RENPY_SDK to the SDK directory (the one containing renpy.py), or "
            "keep a renpy-*-sdk directory in your home, Documents, Downloads "
            "or Desktop folder."
        )
    candidates.sort(key=lambda path: _version_key(path.name))
    return candidates[-1]


def sdk_invocation(sdk: Path) -> tuple[str, list[str]]:
    """Return the program and leading arguments that start this SDK."""

    if os.name == "nt":
        python = sdk / "lib" / "py3-windows-x86_64" / "python.exe"
        if python.is_file():
            return str(python), [str(sdk / "renpy.py")]

    launcher = sdk / "renpy.sh"
    if os.name != "nt" and launcher.is_file():
        return str(launcher), []

    python = sys.executable
    if not python:
        raise DapError(
            f"Ren'Py SDK at '{sdk}' has no usable launcher; expected renpy.sh "
            "(macOS/Linux) or the bundled CPython (Windows)."
        )
    return python, [str(sdk / "renpy.py")]


def _subdirectories(path: Path) -> list[Path]:
    try:
        entries = list(path.iterdir())
    except OSError:
        return []
    result = sorted(
        entry
        for entry in entries
        if entry.is_dir()
        and not entry.name.startswith(".")
        and entry.name not in PROJECT_SCAN_SKIP
    )
    return result


def find_project(start: Path) -> Path | None:
    """Find the project base directory (the one containing ``game/``)."""

    start = start.expanduser()
    if start.is_file():
        start = start.parent
    if (start / "game").is_dir():
        return start

    for ancestor in start.parents:
        if (ancestor / "game").is_dir():
            return ancestor

    children = _subdirectories(start)
    for child in children:
        if (child / "game").is_dir():
            return child
    for child in children:
        for grandchild in _subdirectories(child):
            if (grandchild / "game").is_dir():
                return grandchild
    return None


def _relative_to(path: Path, project: Path) -> Path | None:
    try:
        return path.relative_to(project)
    except ValueError:
        pass
    try:
        return path.resolve().relative_to(project.resolve())
    except (OSError, ValueError):
        return None


def normalize_warp(warp: str, project: Path) -> str:
    """Turn an editor path into Ren'Py's project-relative ``file:line`` form."""

    path, separator, line = warp.rpartition(":")
    if not separator or not line.isdigit():
        return warp.replace("\\", "/")
    path = path.strip()
    if not path:
        return warp

    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        relative = _relative_to(candidate, project)
        if relative is not None:
            return f"{relative.as_posix()}:{line}"
        native = path.replace("\\", "/")
        return f"{native}:{line}"
    return f"{Path(path).as_posix()}:{line}"


def _warp_directory(warp: str) -> Path | None:
    path, separator, line = warp.rpartition(":")
    if not separator or not line.isdigit():
        return None
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.parent
    return None


WARP_LABEL = re.compile(r"^label\s+\S")


def _warp_script_path(path: str, project: Path) -> Path:
    """Return the on-disk file Ren'Py loads for a project-relative warp path."""

    if path.startswith("game/"):
        return project / path
    return project / "game" / path


def _suggest_script(path: str, project: Path) -> str | None:
    """Suggest a game script whose name resembles a misplaced warp target."""

    stem = Path(path).stem
    if not stem:
        return None
    matches = [
        candidate
        for candidate in (project / "game").rglob("*.rpy")
        if candidate.is_file()
        and (
            candidate.stem == stem
            or candidate.stem.endswith(stem)
            or candidate.stem.startswith(stem)
            or stem.endswith(candidate.stem)
            or stem.startswith(candidate.stem)
        )
    ]
    if len(matches) != 1:
        return None
    return matches[0].relative_to(project).as_posix()


def _has_label_before(script: Path, line: int) -> bool:
    """Whether a label starts at or before ``line``, the anchor warp needs."""

    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    return any(WARP_LABEL.match(source) for source in text.splitlines()[:line])


def validate_warp(warp: str, project: Path) -> None:
    """Reject warp targets that Ren'Py cannot load or reach."""

    path, separator, line = warp.rpartition(":")
    if not separator or not line.isdigit() or not path:
        raise DapError(
            f'Invalid "warp" value "{warp}": expected "path/to/script.rpy:line".'
        )
    number = int(line)
    if number < 1:
        raise DapError(f'Invalid "warp" line {number}: lines start at 1.')
    if Path(path).is_absolute():
        raise DapError(
            f'warp target "{path}" is outside the project. Warp only works with '
            "scripts inside the project's game/ directory."
        )

    game_dir = project / "game"
    script = _warp_script_path(path, project)
    if not script.is_file():
        # Scripts may live inside an .rpa archive, which cannot be inspected.
        if any(game_dir.glob("*.rpa")):
            return
        suggestion = _suggest_script(path, project)
        hint = f' Did you mean "{suggestion}"?' if suggestion is not None else ""
        raise DapError(
            f'warp target "{path}" is not loaded by Ren\'Py: it resolves to '
            f'"{script}", which does not exist. Ren\'Py only loads scripts from '
            f'"{game_dir}".{hint}'
        )

    if not _has_label_before(script, number):
        raise DapError(
            f'warp target "{path}:{number}" has no label at or before that line. '
            "Ren'Py can only warp into a label, so put the cursor inside one."
        )


def resolve_launch(
    config: LaunchConfig,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
) -> Launch:
    """Resolve a launch configuration into a concrete Ren'Py command line."""

    env = os.environ if environ is None else environ
    sdk = _normalize_sdk_path(config.sdk) if config.sdk else None
    if sdk is not None and not is_sdk_dir(sdk):
        raise DapError(f"'{sdk}' does not look like a Ren'Py SDK (no renpy.py inside).")
    if sdk is None:
        sdk = find_sdk(environ=env, home=home)
    program, prefix_args = sdk_invocation(sdk)

    start = Path(cwd) if cwd is not None else Path.cwd()
    if config.project:
        start = Path(config.project).expanduser()
    elif config.warp:
        warp_dir = _warp_directory(config.warp)
        if warp_dir is not None:
            start = warp_dir

    project = find_project(start)
    if project is None:
        raise DapError(
            f"No Ren'Py project found at '{start}' (no game/ directory). "
            'Set "project" in the debug configuration.'
        )

    args = [*prefix_args, str(project), config.command]
    if config.warp:
        warp = normalize_warp(config.warp, project)
        validate_warp(warp, project)
        args.extend(["--warp", warp])
    args.extend(config.args)

    return Launch(
        program=program,
        args=tuple(args),
        env=dict(config.env),
        project=project,
    )


def read_message(reader: BinaryIO) -> dict[str, Any] | None:
    """Read one Content-Length framed DAP message, or ``None`` at EOF."""

    content_length: int | None = None
    while True:
        line = reader.readline()
        if not line:
            return None
        line = line.rstrip(b"\r\n")
        if not line:
            if content_length is not None:
                break
            continue
        name, separator, value = line.partition(b":")
        if not separator:
            continue
        if name.strip().lower() == b"content-length":
            try:
                content_length = int(value.strip())
            except ValueError:
                content_length = None

    body = reader.read(content_length)
    if len(body) != content_length:
        raise DapError("DAP message ended before Content-Length bytes arrived")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise DapError("DAP message must be a JSON object")
    return cast(dict[str, Any], payload)


class DapWriter:
    """Thread-safe Content-Length framing for responses and events."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()
        self._sequence = 0

    def send(self, message: dict[str, Any]) -> None:
        with self._lock:
            self._sequence += 1
            message["seq"] = self._sequence
            body = json.dumps(message, ensure_ascii=False).encode("utf-8")
            self._stream.write(b"Content-Length: %d\r\n\r\n" % len(body))
            self._stream.write(body)
            self._stream.flush()

    def respond(
        self, request: Mapping[str, Any], body: Mapping[str, Any] | None = None
    ) -> None:
        self.send(
            {
                "type": "response",
                "request_seq": request.get("seq", 0),
                "command": request.get("command", ""),
                "success": True,
                "body": dict(body or {}),
            }
        )

    def fail(self, request: Mapping[str, Any], message: str) -> None:
        self.send(
            {
                "type": "response",
                "request_seq": request.get("seq", 0),
                "command": request.get("command", ""),
                "success": False,
                "message": message,
            }
        )

    def event(self, event: str, body: Mapping[str, Any] | None = None) -> None:
        self.send({"type": "event", "event": event, "body": dict(body or {})})

    def output(self, category: str, text: str) -> None:
        self.event("output", {"category": category, "output": text})


class Session:
    """One DAP client connection and at most one running game."""

    def __init__(
        self,
        reader: BinaryIO,
        writer: DapWriter,
        *,
        environ: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        home: Path | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._environ = dict(os.environ if environ is None else environ)
        self._cwd = Path.cwd() if cwd is None else Path(cwd)
        self._home = home
        self._process: subprocess.Popen[bytes] | None = None
        self._process_lock = threading.Lock()
        self._terminate_timer: threading.Timer | None = None

    # -- process control -------------------------------------------------

    def _running(self) -> subprocess.Popen[bytes] | None:
        with self._process_lock:
            return self._process

    def _set_process(self, process: subprocess.Popen[bytes] | None) -> None:
        with self._process_lock:
            self._process = process

    def _clear_process(self, process: subprocess.Popen[bytes]) -> None:
        with self._process_lock:
            if self._process is process:
                self._process = None

    def _signal(self, process: subprocess.Popen[bytes], *, force: bool) -> None:
        if os.name == "nt":
            command = ["taskkill", "/T", "/PID", str(process.pid)]
            if force:
                command.append("/F")
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return

        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        except OSError:
            try:
                process.send_signal(sig)
            except OSError:
                pass

    def _terminate(self, *, force: bool = False, escalate: bool = False) -> None:
        process = self._running()
        if process is None:
            return
        self._signal(process, force=force)
        if not escalate:
            return

        def kill_if_running() -> None:
            if self._running() is process:
                self._signal(process, force=True)

        timer = threading.Timer(TERMINAL_GRACE_SECONDS, kill_if_running)
        timer.daemon = True
        self._terminate_timer = timer
        timer.start()

    def _cleanup(self) -> None:
        if self._terminate_timer is not None:
            self._terminate_timer.cancel()
        process = self._running()
        if process is None:
            return
        self._signal(process, force=True)
        try:
            process.wait(timeout=TERMINAL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._signal(process, force=True)
        self._clear_process(process)

    # -- request handling ------------------------------------------------

    def serve(self) -> None:
        try:
            while True:
                message = read_message(self._reader)
                if message is None:
                    break
                if message.get("type") != "request":
                    continue
                if not self._handle(message):
                    break
        finally:
            self._cleanup()

    def _handle(self, request: dict[str, Any]) -> bool:
        command = request.get("command")
        if command == "initialize":
            self._initialize(request)
        elif command == "launch":
            self._launch(request)
        elif command == "attach":
            self._writer.fail(
                request,
                "Attaching to a running Ren'Py game is not supported yet — "
                "use a launch configuration.",
            )
        elif command == "setBreakpoints":
            self._set_breakpoints(request)
        elif command in {"setFunctionBreakpoints", "setExceptionBreakpoints"}:
            self._writer.respond(request, {"breakpoints": []})
        elif command == "configurationDone":
            self._writer.respond(request)
        elif command == "threads":
            self._writer.respond(request, {"threads": [{"id": 1, "name": "Ren'Py"}]})
        elif command == "stackTrace":
            self._writer.respond(request, {"stackFrames": [], "totalFrames": 0})
        elif command == "scopes":
            self._writer.respond(request, {"scopes": []})
        elif command == "variables":
            self._writer.respond(request, {"variables": []})
        elif command in {"continue", "next", "stepIn", "stepOut", "pause"}:
            self._writer.fail(
                request,
                "Stepping and pausing are not supported in launch-only debug "
                "sessions yet.",
            )
        elif command == "evaluate":
            self._writer.fail(
                request,
                "Evaluate is not supported in launch-only debug sessions yet.",
            )
        elif command == "terminate":
            # Respond before signalling so a fast exit cannot race the
            # response with the exited/terminated events it causes.
            self._writer.respond(request)
            self._terminate(escalate=True)
        elif command == "disconnect":
            self._writer.respond(request)
            self._terminate(force=True)
            return False
        else:
            self._writer.fail(request, f"unsupported request '{command or 'unknown'}'")
        return True

    def _initialize(self, request: Mapping[str, Any]) -> None:
        self._writer.respond(
            request,
            {
                "supportsConfigurationDoneRequest": True,
                "supportsTerminateRequest": True,
            },
        )
        self._writer.event("initialized")

    def _set_breakpoints(self, request: Mapping[str, Any]) -> None:
        arguments = request.get("arguments")
        values: object = (
            cast(Mapping[str, object], arguments).get("breakpoints", [])
            if isinstance(arguments, dict)
            else []
        )
        raw = cast(list[object], values) if isinstance(values, list) else []
        breakpoints: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            line = cast(Mapping[str, Any], item).get("line")
            if isinstance(line, int):
                breakpoints.append(
                    {
                        "verified": False,
                        "line": line,
                        "message": "Breakpoints are not supported in "
                        "launch-only debug sessions yet.",
                    }
                )
        self._writer.respond(request, {"breakpoints": breakpoints})

    def _launch(self, request: Mapping[str, Any]) -> None:
        if self._running() is not None:
            self._writer.fail(request, "a Ren'Py game is already running")
            return
        try:
            config = parse_launch_config(request.get("arguments"))
            launch = resolve_launch(
                config,
                environ=self._environ,
                cwd=self._cwd,
                home=self._home,
            )
        except DapError as error:
            self._writer.fail(request, str(error))
            return

        env = dict(self._environ)
        env.update(launch.env)
        options: dict[str, Any] = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True

        try:
            process = cast(
                subprocess.Popen[bytes],
                subprocess.Popen(
                    [launch.program, *launch.args],
                    cwd=str(launch.project),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    **options,
                ),
            )
        except OSError as error:
            self._writer.fail(
                request,
                f"failed to start '{launch.program}': {error}",
            )
            return

        self._set_process(process)
        self._writer.output(
            "console",
            f"Launching: {launch.program} {' '.join(launch.args)}\n",
        )
        self._writer.respond(request)
        self._writer.event(
            "process",
            {
                "name": str(launch.project),
                "systemProcessId": process.pid,
                "isLocalProcess": True,
                "startMethod": "launch",
            },
        )

        for stream, category in (
            (process.stdout, "stdout"),
            (process.stderr, "stderr"),
        ):
            if stream is None:
                continue
            thread = threading.Thread(
                target=self._forward_output,
                args=(stream, category),
                daemon=True,
            )
            thread.start()

        waiter = threading.Thread(
            target=self._wait_for_exit,
            args=(process,),
            daemon=True,
        )
        waiter.start()

    def _forward_output(self, stream: BinaryIO, category: str) -> None:
        while True:
            line = stream.readline()
            if not line:
                break
            self._writer.output(category, line.decode("utf-8", errors="replace"))

    def _wait_for_exit(self, process: subprocess.Popen[bytes]) -> None:
        code = process.wait()
        self._clear_process(process)
        self._writer.event("exited", {"exitCode": code})
        self._writer.event("terminated")


def run() -> int:
    """Run the DAP server on stdio until the client disconnects."""

    session = Session(sys.stdin.buffer, DapWriter(sys.stdout.buffer))
    try:
        session.serve()
    except (DapError, BrokenPipeError, KeyboardInterrupt):
        return 0
    return 0
