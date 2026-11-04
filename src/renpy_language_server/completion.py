"""Context-aware completion for Ren'Py statements and symbols.

This is the light, file-local completion layer: statement keywords plus the
labels, images, screens and characters defined in the current document, and
member access through the workspace index. Workspace-wide statement contexts
are supplied by the server and expanded in Phase 4.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache

from . import builtins as api
from .analysis import Block, analyze
from .completion_data import data as completion_data
from .index import mask_code


@dataclass(frozen=True)
class Completion:
    """One completion item, independent of the LSP data types."""

    label: str
    kind: str
    detail: str
    documentation: str = ""
    insert_text: str = ""
    sort_text: str = ""


@dataclass(frozen=True)
class CompletionResult:
    """Completion items plus the offset where the typed text starts."""

    replace_start: int
    items: list[Completion]


_KEYWORDS: tuple[Completion, ...] = (
    Completion("label", "keyword", "statement", "Define a label: `label name:`"),
    Completion("screen", "keyword", "statement", "Define a screen: `screen name():`"),
    Completion(
        "transform", "keyword", "statement", "Define a transform: `transform name:`"
    ),
    Completion("style", "keyword", "statement", "Define or modify a style"),
    Completion("init", "keyword", "statement", "Run a statement at startup"),
    Completion("image", "keyword", "statement", "Define an image"),
    Completion("define", "keyword", "statement", "Define a variable"),
    Completion("default", "keyword", "statement", "Define a default variable"),
    Completion("show", "keyword", "statement", "Show an image: `show eileen happy`"),
    Completion("scene", "keyword", "statement", "Replace the scene"),
    Completion("hide", "keyword", "statement", "Hide an image"),
    Completion("with", "keyword", "statement", "Apply a transition"),
    Completion("jump", "keyword", "statement", "Jump to a label"),
    Completion("call", "keyword", "statement", "Call a label"),
    Completion("expression", "keyword", "keyword", "Use a Python expression"),
    Completion("text", "keyword", "keyword", "Show text or define a text element"),
    Completion("return", "keyword", "statement", "Return from a label"),
    Completion("menu", "keyword", "statement", "Show a choice menu"),
    Completion("if", "keyword", "statement", "Conditional statement"),
    Completion("elif", "keyword", "statement", "Else-if branch"),
    Completion("else", "keyword", "statement", "Else branch"),
    Completion("while", "keyword", "statement", "While loop"),
    Completion("for", "keyword", "statement", "For loop"),
    Completion("python", "keyword", "statement", "Inline Python block"),
    Completion("python early", "keyword", "statement", "Early Python block"),
    Completion("pass", "keyword", "statement", "Do nothing"),
    Completion("pause", "keyword", "statement", "Pause the game"),
    Completion("play", "keyword", "statement", "Play an audio channel"),
    Completion("stop", "keyword", "statement", "Stop an audio channel"),
    Completion("queue", "keyword", "statement", "Queue audio"),
    Completion("voice", "keyword", "statement", "Play a voice line"),
    Completion("window", "keyword", "statement", "Control the dialogue window"),
    Completion("$", "keyword", "statement", "Run a Python statement"),
)

_AFTER_KEYWORD = {
    "show": "image",
    "scene": "image",
    "hide": "image",
    "jump": "label",
    "call": "label",
}

_LABEL_RE = re.compile(r"^[ \t]*label[ \t]+([A-Za-z_.][\w.]*)", re.MULTILINE)
_IMAGE_RE = re.compile(r"^[ \t]*image[ \t]+([^=\n:]+?)[ \t]*(?:=|:)", re.MULTILINE)
_SCREEN_RE = re.compile(
    r"^[ \t]*screen[ \t]+([A-Za-z_]\w*)[ \t]*(?:\(|:)", re.MULTILINE
)
_CHARACTER_RE = re.compile(
    r"^[ \t]*(?:define|default)[ \t]+([A-Za-z_]\w*)[ \t]*=[ \t]*"
    r"(?:Character|DynamicCharacter)[ \t]*\([ \t]*(?:\"([^\"]*)\"|'([^']*)')?",
    re.MULTILINE,
)
_WORD_RE = re.compile(r"[A-Za-z0-9_.$]*$")
_TARGET_RE = re.compile(r"\S+\s+")
_MEMBER_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\.([A-Za-z_]\w*)?$")
_TRANSFORM_RE = re.compile(r"^[ \t]*transform[ \t]+([A-Za-z_]\w*)", re.MULTILINE)
_STYLE_RE = re.compile(r"^[ \t]*style[ \t]+([A-Za-z_]\w*)", re.MULTILINE)
_CHANNEL_RE = re.compile(r"register_channel\s*\(\s*[\"']([^\"']+)[\"']", re.MULTILINE)
_AUDIO_VAR_RE = re.compile(r"^[ \t]*define[ \t]+audio\.([A-Za-z_]\w*)", re.MULTILINE)
_TRANSITION_VAR_RE = re.compile(
    r"^[ \t]*(?:define|default)[\w \t-]*?\s+([A-Za-z_]\w*)\s*=\s*"
    r"(?:[\w.]*Transition\w*|Dissolve|Fade|Pixellate|Move|Swing)\b",
    re.MULTILINE,
)
_CHARACTER_IMAGE_RE = re.compile(
    r"^[ \t]*(?:define|default)[ \t]+([A-Za-z_]\w*)[ \t]*=[ \t]*"
    r"(?:Character|DynamicCharacter)[ \t]*\((.*?)\)",
    re.MULTILINE | re.DOTALL,
)
_IMAGE_TAG_RE = re.compile(r"\bimage\s*=\s*[\"']([^\"']+)[\"']")
_LAYEREDIMAGE_RE = re.compile(
    r"^[ \t]*layeredimage[ \t]+([^:\n]+?)[ \t]*:", re.MULTILINE
)
_LAYERED_ATTRIBUTE_RE = re.compile(r"^[ \t]*(?:attribute|group)[ \t]+([A-Za-z_]\w*)")

_PYTHON_KEYWORDS = (
    "and",
    "as",
    "assert",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "False",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "None",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "True",
    "try",
    "while",
    "with",
    "yield",
)
_PYTHON_BUILTINS = (
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "float",
    "getattr",
    "hasattr",
    "int",
    "isinstance",
    "len",
    "list",
    "max",
    "min",
    "print",
    "range",
    "repr",
    "reversed",
    "set",
    "setattr",
    "sorted",
    "str",
    "sum",
    "tuple",
    "type",
    "zip",
)
_ACTION_PROPERTIES = frozenset(
    {
        "action",
        "alternate",
        "hovered",
        "unhovered",
        "released",
        "pressed",
        "selected",
        "insensitive",
    }
)
_SCREEN_CONTROL_WORDS = frozenset(
    {"if", "elif", "else", "for", "on", "showif", "python", "default", "style"}
)
_DISPLAYABLE_PROPERTIES = frozenset(
    {
        "background",
        "foreground",
        "idle",
        "hover",
        "selected_idle",
        "selected_hover",
        "insensitive",
        "selected_insensitive",
        "idle_background",
        "hover_background",
        "selected_background",
        "insensitive_background",
        "ground",
        "left_bar",
        "right_bar",
        "thumb",
        "thumb_shadow",
    }
)


@lru_cache(maxsize=1)
def _builtin_items() -> tuple[Completion, ...]:
    result: list[Completion] = []
    for builtin in api.iter_builtins():
        if builtin.type == "Action":
            kind = "action"
        elif builtin.kind in {"function", "class", "var", "image"}:
            kind = builtin.kind
        else:
            kind = "variable"
        insert = builtin.name
        if builtin.args and builtin.kind in {"function", "class"}:
            insert = f"{builtin.name}()"
        result.append(
            Completion(
                label=builtin.name,
                kind=kind,
                detail=builtin.signature,
                documentation=_builtin_documentation(builtin),
                insert_text=insert,
            )
        )
    return tuple(result)


def _builtin_documentation(builtin: api.Builtin) -> str:
    text = builtin.documentation.strip()
    if not text:
        return f"```renpy\n{builtin.signature}\n```"
    paragraph = text.split("\n\n", 1)[0].strip()
    return f"```renpy\n{builtin.signature}\n```\n\n{_sanitize_markdown(paragraph)}"


_SPHINX_ROLE_RE = re.compile(r":[A-Za-z][\w:-]*:`([^`]*)`")
_BACKTICK_RUN_RE = re.compile(r"`+")


def _sanitize_markdown(text: str) -> str:
    """Turn reStructuredText leftovers into plain Markdown.

    Ren'Py's bundled API documentation is reStructuredText. Sphinx roles such
    as ``:doc:`menu <menus>``` and stray unmatched backticks are not valid
    Markdown, so the completion popup would otherwise show them verbatim.
    Matched inline-code spans are preserved.
    """
    return _strip_unmatched_backticks(_SPHINX_ROLE_RE.sub(_plain_role, text))


def _plain_role(match: re.Match[str]) -> str:
    content = match.group(1)
    if content.endswith(">") and "<" in content:
        content = content[: content.rfind("<")].rstrip()
    return content


def _strip_unmatched_backticks(text: str) -> str:
    runs = [(match.start(), match.end()) for match in _BACKTICK_RUN_RE.finditer(text)]
    paired = [False] * len(runs)
    for index, (start, end) in enumerate(runs):
        if paired[index]:
            continue
        for other in range(index + 1, len(runs)):
            other_start, other_end = runs[other]
            if not paired[other] and other_end - other_start == end - start:
                paired[index] = paired[other] = True
                break

    pieces: list[str] = []
    position = 0
    for index, (start, end) in enumerate(runs):
        pieces.append(text[position:start])
        if paired[index]:
            pieces.append(text[start:end])
        position = end
    pieces.append(text[position:])
    return "".join(pieces)


@lru_cache(maxsize=1)
def _python_items() -> tuple[Completion, ...]:
    result = [
        Completion(name, "keyword", "Python keyword") for name in _PYTHON_KEYWORDS
    ]
    result += [
        Completion(name, "function", "Python built-in") for name in _PYTHON_BUILTINS
    ]
    return tuple(result)


def complete(
    source: str,
    prefix: str,
    workspace: Mapping[str, Sequence[Completion]] | None = None,
    container: str | None = None,
    line_index: int = -1,
) -> CompletionResult:
    """Return completions for ``prefix``, the line text before the cursor.

    ``workspace`` optionally supplies symbols from other files. Symbols in the
    current document take precedence when both define the same name.
    ``container`` is the enclosing Python class, used for ``self.`` members.
    ``line_index`` enables block-aware screen and Python completion.
    """
    stripped = prefix.lstrip()
    indentation = len(prefix) - len(stripped)
    empty = len(prefix)

    if not stripped:
        if line_index >= 0:
            screen = _screen_completion(
                source, prefix, workspace, line_index, indentation
            )
            if screen is not None:
                return screen
        return CompletionResult(
            empty,
            _keyword_items() + _symbol_items("character", source, workspace),
        )

    if _inside_string_or_comment(prefix):
        return CompletionResult(empty, [])

    member = _member_completion(prefix, workspace, container)
    if member is not None:
        return member

    namespace = _namespace_completion(prefix)
    if namespace is not None:
        return namespace

    special = _statement_context(source, prefix, workspace, indentation)
    if special is not None:
        return special

    screen = _screen_completion(source, prefix, workspace, line_index, indentation)
    if screen is not None:
        return screen

    dialogue = _dialogue_completion(source, prefix, workspace)
    if dialogue is not None:
        return dialogue

    python = _python_completion(source, prefix, workspace, line_index)
    if python is not None:
        return python

    tokens = stripped.split()
    first = tokens[0]
    trailing_space = stripped[-1].isspace()

    if first == "call" and len(tokens) >= 2 and tokens[1] == "screen":
        if len(tokens) >= 3 or trailing_space:
            start = _target_start(stripped, words=2) + indentation
            return CompletionResult(
                start,
                _filter_kind(
                    _symbol_items("screen", source, workspace), prefix[start:]
                ),
            )
        return CompletionResult(
            _word_start(prefix),
            _filter_items(_keyword_items("screen"), _current_word(prefix)),
        )

    kind = _AFTER_KEYWORD.get(first)
    if kind is not None and (len(tokens) >= 2 or trailing_space):
        start = _target_start(stripped, words=1) + indentation
        items = _symbol_items(kind, source, workspace)
        if first == "call":
            items += _keyword_items("screen")
        return CompletionResult(start, _filter_kind(items, prefix[start:]))

    if len(tokens) == 1:
        word = _current_word(prefix)
        if not word:
            # A token plus a space is a context we do not understand yet:
            # ``add `` (screen language), ``$ `` (Python), ``e `` (dialogue).
            # Do not dump every statement keyword here.
            return CompletionResult(empty, [])
        items = _filter_items(_keyword_items(), word)
        items += _filter_kind(_symbol_items("character", source, workspace), word)
        items += _filter_items(_top_level_builtin_items(), word)
        return CompletionResult(len(prefix) - len(word), items)

    return CompletionResult(empty, [])


def _top_level_builtin_items() -> list[Completion]:
    """Return callable API names suitable at the start of a statement."""
    return [
        item
        for item in _builtin_items()
        if item.kind in {"class", "function"}
        and "." not in item.label
        and not item.label.startswith("_")
    ]


def _namespace_completion(prefix: str) -> CompletionResult | None:
    """Complete immediate children of a bundled API namespace."""
    word = _current_word(prefix)
    if "." not in word:
        return None
    namespace = word[: word.rfind(".") + 1]
    if not namespace.startswith(("renpy.", "config.", "gui.", "persistent.")):
        return None

    typed = word[len(namespace) :]
    children: dict[str, bool] = {}
    for item in _builtin_items():
        if not item.label.startswith(namespace):
            continue
        remainder = item.label[len(namespace) :]
        child = remainder.split(".", 1)[0]
        if not child:
            continue
        children[child] = children.get(child, False) or "." in remainder
    if not children:
        return None
    items = [
        Completion(
            name,
            "keyword" if nested else "builtin",
            "API namespace" if nested else "Ren'Py API",
        )
        for name, nested in children.items()
    ]
    return CompletionResult(len(prefix) - len(typed), _filter_items(items, typed))


def _statement_context(
    source: str,
    prefix: str,
    workspace: Mapping[str, Sequence[Completion]] | None,
    indentation: int,
) -> CompletionResult | None:
    """Complete statement arguments and special statement values."""
    stripped = prefix.lstrip()
    tokens = stripped.split()
    if not tokens:
        return None
    first = tokens[0]
    trailing_space = stripped[-1].isspace()

    if first == "call" and len(tokens) >= 2 and tokens[1] == "screen":
        if len(tokens) >= 3 or trailing_space:
            start = _target_start(stripped, words=2) + indentation
            return CompletionResult(start, _screens(source, workspace, prefix[start:]))
        return CompletionResult(
            _word_start(prefix),
            _filter_items(_keyword_items("screen"), _current_word(prefix)),
        )

    if first in {"show", "hide"} and len(tokens) >= 2 and tokens[1] == "screen":
        if len(tokens) >= 3 or trailing_space:
            start = _target_start(stripped, words=2) + indentation
            return CompletionResult(start, _screens(source, workspace, prefix[start:]))
        return CompletionResult(
            _word_start(prefix),
            _filter_items(_keyword_items("screen"), _current_word(prefix)),
        )

    if first == "use" and (len(tokens) >= 2 or trailing_space):
        start = _target_start(stripped, words=1) + indentation
        return CompletionResult(start, _screens(source, workspace, prefix[start:]))

    if first in {"jump", "call"} and (len(tokens) >= 2 or trailing_space):
        start = _target_start(stripped, words=1) + indentation
        items = _labels(source, workspace)
        items += _keyword_items("expression")
        if first == "call":
            items += _keyword_items("screen")
        return CompletionResult(start, _filter_kind(items, prefix[start:]))

    masked = mask_code(stripped)
    at_match = (
        re.search(r"\bat\b", masked)
        if first in {"show", "scene", "hide", "label", "screen"}
        else None
    )
    if at_match is not None:
        at_end = at_match.end()
        if at_end < len(stripped) or trailing_space:
            start = at_end + indentation
            while start < len(prefix) and prefix[start].isspace():
                start += 1
            tail = prefix[start:]
            comma = tail.rfind(",")
            if comma >= 0:
                start += comma + 1
                while start < len(prefix) and prefix[start].isspace():
                    start += 1
            return CompletionResult(
                start, _transforms(source, workspace, prefix[start:])
            )

    if first == "with" and (len(tokens) >= 2 or trailing_space):
        start = _target_start(stripped, words=1) + indentation
        return CompletionResult(start, _transitions(source, workspace, prefix[start:]))

    if first in {"show", "scene", "hide"} and (len(tokens) >= 2 or trailing_space):
        if len(tokens) >= 2 and tokens[1] in {"expression", "text"}:
            return CompletionResult(len(prefix), [])
        start = _target_start(stripped, words=1) + indentation
        items = _images(source, workspace)
        items += _keyword_items("expression")
        items += _keyword_items("screen")
        if first == "show":
            items += _keyword_items("text")
        return CompletionResult(start, _filter_kind(items, prefix[start:]))

    if first in {"play", "queue", "stop"} and (len(tokens) >= 2 or trailing_space):
        return _audio_statement(source, prefix, workspace, first, indentation)

    return None


def _audio_statement(
    source: str,
    prefix: str,
    workspace: Mapping[str, Sequence[Completion]] | None,
    command: str,
    indentation: int,
) -> CompletionResult:
    stripped = prefix.lstrip()
    tokens = stripped.split()
    trailing_space = stripped[-1].isspace()
    data = completion_data()
    channels = _unique(list(data.audio_channels) + _local_channels(source))

    word = _current_word(prefix)
    if word.startswith("audio."):
        typed = word[len("audio.") :]
        items = [
            Completion(
                item.label[len("audio.") :],
                "audio",
                "audio variable",
                item.documentation,
                insert_text=item.label,
            )
            for item in _audio_assets(source, workspace)
            if item.label.startswith("audio.")
        ]
        return CompletionResult(len(prefix) - len(typed), _filter_items(items, typed))

    if len(tokens) == 1 and trailing_space:
        return CompletionResult(
            len(prefix),
            [Completion(name, "keyword", "audio channel") for name in channels],
        )
    if len(tokens) == 2 and not trailing_space:
        start = _target_start(stripped, words=1) + indentation
        return CompletionResult(
            start,
            _filter_items(
                [Completion(name, "keyword", "audio channel") for name in channels],
                tokens[1],
            ),
        )

    start = _target_start(stripped, words=2) + indentation
    if len(tokens) == 2:
        options = (
            ["fadeout"]
            if command == "stop"
            else [
                "fadein",
                "fadeout",
                "loop",
                "noloop",
                "if_changed",
                "volume",
            ]
        )
        items = _audio_assets(source, workspace)
        items += [Completion(name, "keyword", "audio option") for name in options]
        return CompletionResult(start, items)

    option_names = {
        "fadein",
        "fadeout",
        "loop",
        "noloop",
        "if_changed",
        "volume",
    }
    last = tokens[-1]
    if last in option_names and trailing_space:
        return CompletionResult(
            len(prefix),
            [
                Completion(name, "value", "audio option value")
                for name in completion_data().values_for(last)
            ],
        )
    word = _current_word(prefix)
    start = len(prefix) - len(word)
    return CompletionResult(
        start,
        _filter_items(
            [
                Completion(name, "keyword", "audio option")
                for name in (
                    ["fadeout"]
                    if command == "stop"
                    else [
                        "fadein",
                        "fadeout",
                        "loop",
                        "noloop",
                        "if_changed",
                        "volume",
                    ]
                )
            ],
            word,
        ),
    )


def _keyword_items(word: str | None = None) -> list[Completion]:
    return [item for item in _KEYWORDS if word is None or _matches(item.label, word)]


def _member_completion(
    prefix: str,
    workspace: Mapping[str, Sequence[Completion]] | None,
    container: str | None,
) -> CompletionResult | None:
    """Complete members after ``Class.``, ``self.``, ``persistent.`` or ``store.``."""
    if workspace is None:
        return None
    match = _MEMBER_RE.search(prefix)
    if match is None:
        return None

    owner = match.group(1)
    typed = match.group(2) or ""
    if owner == "self":
        if not container:
            return None
        key = f"member:{container}"
    elif owner == "persistent":
        key = "persistent"
    elif owner == "store":
        key = "variable"
    else:
        key = f"member:{owner}"

    items = workspace.get(key, ())
    if not items:
        return None
    start = match.start(2) if match.group(2) is not None else len(prefix)
    return CompletionResult(start, _filter_items(list(items), typed))


def _symbol_items(
    kind: str,
    source: str,
    workspace: Mapping[str, Sequence[Completion]] | None = None,
) -> list[Completion]:
    local = _local_symbol_items(kind, source)
    if workspace is None:
        return local
    return _merge_items(local, workspace.get(kind, ()))


def _labels(
    source: str, workspace: Mapping[str, Sequence[Completion]] | None
) -> list[Completion]:
    return _symbol_items("label", source, workspace)


def _images(
    source: str, workspace: Mapping[str, Sequence[Completion]] | None
) -> list[Completion]:
    return _symbol_items("image", source, workspace)


def _screens(
    source: str,
    workspace: Mapping[str, Sequence[Completion]] | None,
    typed: str,
) -> list[Completion]:
    return _filter_kind(_symbol_items("screen", source, workspace), typed)


def _transforms(
    source: str,
    workspace: Mapping[str, Sequence[Completion]] | None,
    typed: str,
) -> list[Completion]:
    local = [
        Completion(name, "transform", "transform")
        for name in _unique(_TRANSFORM_RE.findall(source))
    ]
    builtins = [
        Completion(name, "transform", "built-in transform")
        for name in completion_data().transforms
    ]
    external = workspace.get("transform", ()) if workspace is not None else ()
    items = _merge_items(local, builtins)
    items = _merge_items(items, external)
    return _filter_kind(items, typed)


def _transitions(
    source: str,
    workspace: Mapping[str, Sequence[Completion]] | None,
    typed: str,
) -> list[Completion]:
    local = [
        Completion(name, "transition", "transition")
        for name in _unique(_TRANSITION_VAR_RE.findall(source))
    ]
    builtins = [
        Completion(name, "transition", "built-in transition")
        for name in completion_data().transitions
    ]
    external = workspace.get("transition", ()) if workspace is not None else ()
    items = _merge_items(local, builtins)
    items = _merge_items(items, external)
    return _filter_kind(items, typed)


def _styles(
    source: str, workspace: Mapping[str, Sequence[Completion]] | None
) -> list[Completion]:
    local = [
        Completion(name, "style", "style")
        for name in _unique(_STYLE_RE.findall(source))
    ]
    external = workspace.get("style", ()) if workspace is not None else ()
    return _merge_items(local, external)


def _local_channels(source: str) -> list[str]:
    return _unique(_CHANNEL_RE.findall(source))


def _audio_assets(
    source: str, workspace: Mapping[str, Sequence[Completion]] | None
) -> list[Completion]:
    local = [
        Completion(
            f"audio.{name}",
            "audio",
            "audio variable",
            f"`audio.{name}`",
            insert_text=f"audio.{name}",
        )
        for name in _unique(_AUDIO_VAR_RE.findall(source))
    ]
    external = workspace.get("audio", ()) if workspace is not None else ()
    return _merge_items(local, external)


def _local_symbol_items(kind: str, source: str) -> list[Completion]:
    if kind == "label":
        names = _parse_labels(source)
        return [
            Completion(name, "label", "label", f"Label `{name}` in this file")
            for name in names
        ]
    if kind == "image":
        names = _parse_images(source)
        return [
            Completion(name, "image", "image", f"Image `{name}` in this file")
            for name in names
        ]
    if kind == "screen":
        names = _parse_screens(source)
        return [
            Completion(name, "screen", "screen", f"Screen `{name}` in this file")
            for name in names
        ]
    if kind == "character":
        return [
            Completion(
                name,
                "character",
                f'character "{display}"' if display else "character",
                f"Character `{name}` in this file",
            )
            for name, display in _parse_characters(source)
        ]
    return []


def _merge_items(
    local: Sequence[Completion], external: Sequence[Completion]
) -> list[Completion]:
    result = list(local)
    seen = {item.label for item in local}
    for item in external:
        if item.label not in seen:
            seen.add(item.label)
            result.append(item)
    return result


def _screen_completion(
    source: str,
    prefix: str,
    workspace: Mapping[str, Sequence[Completion]] | None,
    line_index: int,
    indentation: int,
) -> CompletionResult | None:
    """Complete screen elements, properties and property values."""
    if line_index < 0:
        return None
    analysis = analyze(source)
    probe = line_index if prefix.strip() else max(line_index - 1, 0)
    block = analysis.block_at(probe)
    screen = _screen_block(block)
    if screen is None:
        return None

    stripped = prefix.lstrip()
    data = completion_data()
    enclosing = _enclosing_element(block)
    elements = [
        Completion(name, "keyword", "screen element") for name in data.screen_elements
    ]

    if not stripped:
        items = list(elements)
        if enclosing:
            items += _property_items(enclosing)
        return CompletionResult(len(prefix), items)

    tokens = stripped.split()
    trailing_space = stripped[-1].isspace()
    first = tokens[0]
    if first in _SCREEN_CONTROL_WORDS:
        return None
    if first == "use" and (len(tokens) >= 2 or trailing_space):
        start = _target_start(stripped, words=1) + indentation
        return CompletionResult(start, _screens(source, workspace, prefix[start:]))

    element = first if first in data.screen_elements else enclosing
    properties = _property_items(element) if element else []
    property_names = {item.label for item in properties}
    before = tokens if trailing_space else tokens[:-1]
    last_property = next(
        (token for token in reversed(before) if token in property_names), ""
    )
    if last_property:
        start = _word_start(prefix)
        return CompletionResult(
            start,
            _property_value_items(last_property, source, workspace, prefix[start:]),
        )

    if first in data.screen_elements:
        if len(tokens) >= 2 or trailing_space:
            start = _word_start(prefix)
            return CompletionResult(
                start, _filter_items(properties, prefix[start:].strip())
            )
        word = _current_word(prefix)
        return CompletionResult(
            len(prefix) - len(word),
            _filter_items(elements + properties, word),
        )

    if first in property_names:
        if len(tokens) >= 2 or trailing_space:
            start = _word_start(prefix)
            return CompletionResult(
                start,
                _property_value_items(first, source, workspace, prefix[start:]),
            )
        word = _current_word(prefix)
        return CompletionResult(
            len(prefix) - len(word), _filter_items(properties, word)
        )

    word = _current_word(prefix)
    if word:
        items = list(elements)
        if enclosing:
            items += properties
        return CompletionResult(len(prefix) - len(word), _filter_items(items, word))
    return CompletionResult(len(prefix), elements)


def _block_word(block: Block) -> str:
    return block.line.first_word.rstrip(":")


def _screen_block(block: Block | None) -> Block | None:
    current = block
    while current is not None:
        if _block_word(current) == "screen":
            return current
        current = current.parent
    return None


def _enclosing_element(block: Block | None) -> str:
    data = completion_data()
    current = block
    while current is not None:
        word = _block_word(current)
        if word == "screen":
            return ""
        if word in data.screen_elements and word not in _SCREEN_CONTROL_WORDS:
            return word
        current = current.parent
    return ""


def _property_items(element: str) -> list[Completion]:
    if not element:
        return []
    return [
        Completion(name, "property", f"{element} property")
        for name in completion_data().properties_for(element)
    ]


def _property_value_items(
    name: str,
    source: str,
    workspace: Mapping[str, Sequence[Completion]] | None,
    typed: str,
) -> list[Completion]:
    if name in _ACTION_PROPERTIES:
        items = _action_items()
    elif name == "at":
        return _transforms(source, workspace, typed)
    elif name in {"with", "transition"}:
        return _transitions(source, workspace, typed)
    elif name == "style":
        return _filter_items(_styles(source, workspace), typed)
    elif name in _DISPLAYABLE_PROPERTIES:
        items = [
            Completion(value, "value", f"{name} value")
            for value in completion_data().values_for(name)
        ]
        items += _images(source, workspace)
    else:
        items = [
            Completion(value, "value", f"{name} value")
            for value in completion_data().values_for(name)
        ]
    return _filter_items(items, typed)


def _action_items() -> list[Completion]:
    return [item for item in _builtin_items() if item.kind == "action"]


def _dialogue_completion(
    source: str,
    prefix: str,
    workspace: Mapping[str, Sequence[Completion]] | None,
) -> CompletionResult | None:
    """Complete image attributes after a character speaking tag."""
    stripped = prefix.lstrip()
    tokens = stripped.split()
    if not tokens:
        return None
    trailing_space = stripped[-1].isspace()
    if len(tokens) < 2 and not trailing_space:
        return None
    speaker = tokens[0]
    characters = dict(_character_images(source))
    tag = characters.get(speaker)
    if not tag:
        return None
    attributes = _image_attributes(source, tag)
    if not attributes:
        return None
    word = _current_word(prefix)
    start = len(prefix) - len(word)
    items = [Completion(name, "attribute", f"{tag} attribute") for name in attributes]
    return CompletionResult(start, _filter_items(items, word))


def _python_completion(
    source: str,
    prefix: str,
    workspace: Mapping[str, Sequence[Completion]] | None,
    line_index: int,
) -> CompletionResult | None:
    """Complete Python keywords and built-ins in expression contexts."""
    stripped = prefix.lstrip()
    tokens = stripped.split()
    if not tokens:
        return None
    first = tokens[0]
    trailing_space = stripped[-1].isspace()
    word = _current_word(prefix)
    start = len(prefix) - len(word)
    extra = _python_symbol_items(source, workspace)

    if first == "$" and (len(tokens) >= 2 or trailing_space):
        items = list(_python_items()) + _top_level_builtin_items() + extra
        return CompletionResult(start, _filter_items(items, word))

    if first in {"if", "elif", "while"} and (len(tokens) >= 2 or trailing_space):
        return CompletionResult(
            start, _filter_items(list(_python_items()) + extra, word)
        )

    if first in {"define", "default"} and "=" in stripped:
        start = _word_start(prefix)
        typed = prefix[start:]
        return CompletionResult(
            start, _filter_items(list(_builtin_items()) + extra, typed)
        )

    if line_index >= 0 and _in_python_block(source, line_index):
        if "=" in prefix or stripped.startswith(("return ", "raise ")):
            return None
        return CompletionResult(start, _filter_items(list(_python_items()), word))

    return None


def _python_symbol_items(
    source: str, workspace: Mapping[str, Sequence[Completion]] | None
) -> list[Completion]:
    items = _symbol_items("variable", source, workspace)
    items += _symbol_items("class", source, workspace)
    items += _symbol_items("persistent", source, workspace)
    return items


def _in_python_block(source: str, line_index: int) -> bool:
    analysis = analyze(source)
    block = analysis.block_at(line_index)
    while block is not None:
        text = block.line.text.strip()
        if (
            text == "python:"
            or text.startswith("python ")
            or text.endswith(" python:")
            or " python early" in f" {text}"
        ):
            return True
        block = block.parent
    return False


def _character_images(source: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for match in _CHARACTER_IMAGE_RE.finditer(source):
        image = _IMAGE_TAG_RE.search(match.group(2))
        if image is not None:
            result.append((match.group(1), image.group(1)))
    return result


def _image_attributes(source: str, tag: str) -> list[str]:
    result: list[str] = []
    for match in _IMAGE_RE.finditer(source):
        name = match.group(1).strip()
        if not name.startswith(f"{tag} "):
            continue
        result.extend(name[len(tag) + 1 :].split())
    for match in _LAYEREDIMAGE_RE.finditer(source):
        if match.group(1).strip() != tag:
            continue
        tail = source[match.end() :]
        for line in tail.splitlines():
            if line.strip() and not line[:1].isspace():
                break
            attribute = _LAYERED_ATTRIBUTE_RE.match(line)
            if attribute is not None:
                result.append(attribute.group(1))
    return _unique(result)


def _parse_labels(source: str) -> list[str]:
    return _unique(match.group(1) for match in _LABEL_RE.finditer(source))


def _parse_images(source: str) -> list[str]:
    return _unique(
        match.group(1).strip()
        for match in _IMAGE_RE.finditer(source)
        if match.group(1).strip()
    )


def _parse_screens(source: str) -> list[str]:
    return _unique(match.group(1) for match in _SCREEN_RE.finditer(source))


def _parse_characters(source: str) -> list[tuple[str, str | None]]:
    result: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for match in _CHARACTER_RE.finditer(source):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        display = match.group(2) if match.group(2) is not None else match.group(3)
        result.append((name, display))
    return result


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _filter_items(items: list[Completion], typed: str) -> list[Completion]:
    if not typed:
        return items
    return [item for item in items if _matches(item.label, typed)]


def _filter_kind(items: list[Completion], typed: str) -> list[Completion]:
    return _filter_items(items, typed)


def _matches(name: str, typed: str) -> bool:
    name_lower = name.lower()
    typed_lower = typed.lower()
    return name_lower.startswith(typed_lower) or typed_lower in name_lower


def _current_word(prefix: str) -> str:
    match = _WORD_RE.search(prefix)
    return match.group(0) if match else ""


def _word_start(prefix: str) -> int:
    return len(prefix) - len(_current_word(prefix))


def _target_start(stripped: str, words: int) -> int:
    """Offset in ``stripped`` after the first ``words`` tokens and whitespace."""
    offset = 0
    for _ in range(words):
        match = re.match(r"\S+", stripped[offset:])
        if match is None:
            return len(stripped)
        offset += match.end()
        while offset < len(stripped) and stripped[offset].isspace():
            offset += 1
    return offset


def _inside_string_or_comment(prefix: str) -> bool:
    """True when the cursor is inside a quoted string or after a comment."""
    quote: str | None = None
    escaped = False
    for char in prefix:
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            return True
    return quote is not None
