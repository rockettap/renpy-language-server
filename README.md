# renpy-language-server

Language server and formatter for [Ren'Py](https://www.renpy.org) scripts, built with
[pygls](https://github.com/openlawlibrary/pygls) and managed with [uv](https://docs.astral.sh/uv/).
Part of [renpy-zed](https://github.com/rockettap/renpy-zed) (Ren'Py support
for Zed), but it speaks standard LSP and works with any client.

Requires Python 3.10 or newer.

> Unofficial project, not affiliated with Ren'Py.

## Features

- `textDocument/formatting` and `textDocument/rangeFormatting`, returned as
  minimal line edits (the cursor does not jump)
- `textDocument/completion` for statements, labels, images (including automatic
  images from `game/images`), screens, characters, transforms, transitions,
  audio channels/assets and the bundled Ren'Py API namespaces. Screen bodies
  complete elements, properties and property values, dialogue completes image
  attributes, and `$` / conditions / declarations complete Python keywords and
  built-ins
- `textDocument/documentSymbol` for labels, screens, transforms, images,
  characters, styles, layered images, `define` / `default` variables, and for
  Python classes, functions, methods, properties, fields, stores, persistent
  variables, test cases and translations. Class and store members are nested in
  the outline
- `textDocument/definition` for labels, screens, transforms, images, layered
  images, characters, styles and variables, including local labels (`.local`)
  resolved against the most recent global label and images after `show` /
  `scene` / `hide` (declared images or automatic image files)
- Definition also follows Python member access where it is unambiguous:
  `self.field`, `Class.member`, `persistent.value`, `store.value` and class
  base names
- `textDocument/hover` for labels, screens, transforms, images, characters and
  other declarations, for references such as `jump`, `show`, `use` and `at`,
  for automatic images from `game/images`, and for the bundled Ren'Py API
  (signature, documentation and source location)
- Hover includes comment-block documentation above a declaration and works for
  references across files
- `textDocument/prepareRename` and `textDocument/rename` for labels (global,
  dotted and local), screens, transforms, images, layered images, characters,
  styles and `define` / `default` variables, across every indexed file.
  Class/function/member rename is deliberately deferred
- `textDocument/documentHighlight` for the symbol under the cursor, so Zed
  shades declarations and references while editing and renaming
- `textDocument/references` for the same families as rename, across every
  indexed file, with `includeDeclaration` respected
- `workspace/symbol` for workspace-wide symbol search across labels, screens,
  images, characters, styles, variables, classes, members, stores, persistent
  variables, test cases and translations
- `textDocument/signatureHelp` for bundled Ren'Py API calls, labels, screens,
  user classes/functions and `self.` / `Class.` methods
- `textDocument/codeAction` quick fixes for comparison typos, stray `$`,
  leading tabs and unknown labels
- `textDocument/semanticTokens/full` (opt-in) for declarations, references,
  built-ins, obsolete APIs, keywords, parameters and literals
- Completion of class members after `Class.` and `self.`, persistent fields
  after `persistent.`, variables after `store.`, and API names after
  `renpy.`, `renpy.music.`, `renpy.audio.`, `config.` and `gui.`
- Callable built-ins insert their parentheses (`Character()`), and completion
  is available from spaces, `.`, `(`, `@` and `-`
- Completion documentation is sent as Markdown, so signature fences and inline
  code render as code blocks in the editor
- configurable diagnostics for indentation, tabs, filenames, variable names,
  comparisons, stray `$`, obsolete APIs, unknown labels and images, undefined
  screens, persistent/store variables and duplicate labels, with per-rule
  severity and open-file or workspace modes (see [Settings](#settings))
- `textDocument/foldingRange` for labels, menus, menu choices, screens,
  transforms and other indented blocks
- `renpy-language-server dap`, a launch-only Debug Adapter Protocol server that starts a
  project through an installed Ren'Py SDK, supports `warp`, streams output and
  terminates the game. Breakpoints, stepping, variables and attach are not
  implemented yet
- `renpy-language-server format` command for scripts and CI (`--check`, `--diff`)
- Safe formatting by default: whitespace and quote delimiters only, never
  string values or program behaviour
- Inline spacing for Python-ish statements (`$ points=1` becomes
  `$ points = 1`) and inside `python:` blocks
- Single-quoted strings become double-quoted unless the value contains an
  unescaped `"` (`--no-quotes` / `normalize_quotes: false` disables it)
- Optional Ruff formatting for `python:` block bodies

## Install

```bash
uv tool install renpy-language-server
uv tool install "renpy-language-server[python-format]"   # with optional Ruff formatting
# for development, from a clone:
uv tool install --editable .
uv tool install --editable ".[python-format]"
```

## Use

```bash
renpy-language-server format game/             # format every .rpy under game/ in place
renpy-language-server format --check game/     # exit 1 if anything would change (CI)
renpy-language-server format --diff script.rpy
renpy-language-server format --python game/    # also format python: blocks with Ruff
cat script.rpy | renpy-language-server format -
renpy-language-server                          # start the language server on stdio
renpy-language-server dap                      # start the launch-only debug adapter on stdio
```

### Debug adapter

`renpy-language-server dap` speaks DAP over stdin/stdout. It is normally launched by the
`renpy-zed` Zed extension, but any DAP client can start it. A launch
configuration accepts:

| Field     | Default | Meaning                                                       |
| --------- | ------- | ------------------------------------------------------------- |
| `request` | launch  | Only `launch` is accepted                                     |
| `sdk`     | auto    | SDK directory or a launcher inside it                         |
| `project` | auto    | Directory containing `game/`; inferred from `warp` or the cwd |
| `warp`    | none    | `file:line`, made project-relative when possible              |
| `command` | `run`   | Ren'Py CLI command (`run`, `lint`, `compile`, ...)            |
| `args`    | `[]`    | Extra arguments appended to the Ren'Py command line           |
| `env`     | `{}`    | Extra environment variables for the game process              |

The SDK is resolved from `sdk`, then `RENPY_SDK`, then `renpy-*-sdk`
directories in the home directory, `Documents`, `Downloads`, `Desktop`,
`Applications` and `/Applications`, newest version first. `RENPY_SDK` may name
the SDK directory or a launcher inside it.

`terminate` and `disconnect` stop the game, escalating to a forced kill after
three seconds. `setBreakpoints` reports the requested lines as unverified and
stepping, pause and evaluate return a clear "launch-only" error. `attach` is
rejected.

### In Zed

Until the renpy-zed extension is published, point Zed at the binary
(`which renpy-language-server`) in `settings.json`:

```json
{
  "lsp": {
    "renpy-language-server": {
      "binary": { "path": "/home/you/.local/bin/renpy-language-server" }
    }
  }
}
```

The language itself (`.rpy` files) must be registered by the extension first.

Zed uses LSP folding ranges only when its `document_folding_ranges` setting is
enabled. Without it, Zed falls back to indentation-based folding, which can
attach a menu choice's fold to the next choice:

```json
{
  "languages": {
    "Ren'Py": { "document_folding_ranges": "on" }
  }
}
```

### Settings

The server accepts settings from the language client's `initializationOptions`
(under `renpyLanguageServer`, or flat) and from
`workspace/didChangeConfiguration`:

```json
{
  "renpyLanguageServer": {
    "indent": 4,
    "max_blank_lines": 2,
    "align_equals": true,
    "normalize_spacing": true,
    "normalize_quotes": true,
    "format_python": false,
    "diagnostics": true,
    "code_actions": true,
    "unknown_label_diagnostics": true,
    "diagnostics_mode": "open",
    "diagnostic_rules": {
      "indentation": "warning",
      "tabs": "warning",
      "unknown_label": "warning"
    },
    "completion": true,
    "automatic_assets": true,
    "semantic_tokens": false,
    "workspace_symbols": true,
    "hover": true,
    "rename": true,
    "references": true,
    "highlight": true,
    "signature": true,
    "extended_index": true,
    "member_references": true
  }
}
```

| Setting                     | Default   | Meaning                                                       |
| --------------------------- | --------- | ------------------------------------------------------------- |
| `indent`                    | `4`       | Fallback spaces per indentation level                         |
| `max_blank_lines`           | `2`       | Maximum consecutive blank lines                               |
| `align_equals`              | `true`    | Align consecutive assignment `=`                              |
| `normalize_spacing`         | `true`    | Inline operator spacing                                       |
| `normalize_quotes`          | `true`    | Rewrite single-quoted strings to double quotes                |
| `format_python`             | `false`   | Format `python:` bodies with Ruff                             |
| `diagnostics`               | `true`    | Enable all diagnostics                                        |
| `code_actions`              | `true`    | Enable diagnostic quick fixes                                 |
| `unknown_label_diagnostics` | `true`    | Legacy switch for the unknown-label rule                      |
| `diagnostics_mode`          | `"open"`  | Check open files (`open`) or the workspace                    |
| `diagnostic_rules`          | see below | Per-rule `error`, `warning` or `off`                          |
| `completion`                | `true`    | Enable completion                                             |
| `automatic_assets`          | `true`    | Offer images/audio found on disk in completion                |
| `semantic_tokens`           | `false`   | Enable semantic tokens (opt-in)                               |
| `workspace_symbols`         | `true`    | Enable `workspace/symbol` search                              |
| `hover`                     | `true`    | Enable hover information                                      |
| `rename`                    | `true`    | Enable prepare-rename and rename                              |
| `references`                | `true`    | Enable find-references                                        |
| `highlight`                 | `true`    | Enable occurrence highlights                                  |
| `signature`                 | `true`    | Enable signature help                                         |
| `extended_index`            | `true`    | Index Python classes, stores and related declaration families |
| `member_references`         | `true`    | Index `self.x` / `Class.x` / `persistent.x` / `store.x`       |

`diagnostic_rules` accepts these keys: `indentation`, `tabs`, `filename`,
`invalid_variable`, `reserved_names`, `comparison`, `stray_dollar`,
`obsolete_api`, `undefined_persistent`, `undefined_store`, `duplicate_label`,
`unknown_label`, `unknown_image` and `undefined_screen`. The two pre-existing
rules (`indentation`, `unknown_label`) and `tabs` default to `warning`; all
newer rules default to `off` until they have been validated on real projects.
Set a rule to `error` for stricter projects, or to `off` to silence it. The
legacy `unknown_label_diagnostics` flag still maps to the `unknown_label` rule.

Semantic tokens are disabled by default because Zed already highlights Ren'Py
through tree-sitter and the two layers should be validated together. Set
`semantic_tokens` to `true` to let the server add declaration, reference,
built-in and obsolete-API tokens; the capability and legend are always
advertised, and the provider returns an empty stream while disabled.

Diagnostics have the source `renpy-language-server` and a stable code such as
`renpy-language-server.unknown-image`. In `workspace` mode the server publishes diagnostics
for every indexed file on startup and after configuration, save and watched-file
events; normal typing only rechecks the current document.

Rename follows the indexed references: `jump` / `call`, screen statements,
`show` / `scene` / `hide`, `at`, dialogue speakers and style parents. Variables
are renamed in code, dialogue interpolation (`"[var]"`), and across files,
including declarations with an init priority (`define -1 foo = ...`) and the
`+=` / `|=` operators.

Rename protects Ren'Py syntax: statement and screen-language keywords, audio
channel names, `with` / `as` / `onlayer` / `behind` clauses, dialogue
attributes, screen-local `default` variables and ordinary strings. Dynamic
targets such as `jump expression`, automatic image files and arbitrary
attribute access are not renamed. Store-qualified declarations such as
`define config.name`, variable names passed as strings (for example
`SetVariable("points", ...)`), and local names that shadow a store variable
inside Python functions are not handled. If several declarations share a name,
all of them are renamed together.

Classes, functions, methods, fields, properties, stores, persistent variables,
test cases and translations are indexed for navigation and completion, but
class/function/member rename is intentionally deferred to a later release.

Occurrence highlights use Zed's `editor.document_highlight.write_background`
for declarations and `editor.document_highlight.read_background` for
references. Adjust those keys in the theme overrides if the shade is too
subtle.

Hover documentation for Ren'Py built-ins comes from the MIT-licensed
`vscode-language-renpy` data; see [`NOTICE.md`](NOTICE.md).

### Logs

The server writes logs to stderr, never stdout. Normal runs print only a startup
line; pygls protocol logs, which include full document contents, are disabled by
default. To inspect the JSON-RPC traffic, launch Zed with:

```bash
RENPY_LANGUAGE_SERVER_DEBUG=1 zed .
```

## Formatting rules

| Rule                | Detail                                                                                                                   |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Indentation         | `tabSize` from the editor (default 4) spaces per level; tabs are expanded                                                |
| Trailing whitespace | removed                                                                                                                  |
| Assignments         | the `=` of consecutive assignment lines at the same indentation level is aligned into one column                         |
| Inline spacing      | assignment and comparison operators in `$`, `define`, `default`, `if`, `elif`, `while`, `return` and `assert` lines      |
| Keyword arguments   | spaces around `=` are removed (`color = "#fff"` becomes `color="#fff"`); real assignments keep them                      |
| Quotes              | single-quoted strings become double-quoted unless the value contains an unescaped `"`; comments and values are untouched |
| Python blocks       | assignment, comparison, arithmetic and bitwise operators inside `python:` blocks                                         |
| Ruff (opt-in)       | `--python` formats `python:` bodies with Ruff, changing more than the default rules                                      |
| Blank lines         | runs capped at 2; none at the start of the file                                                                          |
| Block spacing       | a blank line before top-level `label`, `screen`, `init`, `transform`; a comment block directly above stays attached      |
| End of file         | exactly one newline                                                                                                      |
| Line endings        | LF or CRLF is kept as found                                                                                              |
| Comments            | re-indented to the block they sit in; a comment right after `label x:` joins the body                                    |

String contents are never edited: a single-quoted literal is only rewritten to
double quotes when it contains no unescaped `"`, and quoted text in comments is
skipped. Indentation and alignment rules never touch dialogue, screen
properties or ATL lines; continuation lines of open brackets or backslashes are
shifted together with their first line, keeping their relative alignment.
Keyword and default-parameter `=` inside brackets is the only operator the
spacing pass tightens; top-level assignment `=` still gets spaces.

### Known assumptions and limits

- A string opened with a single `"` or `'` that is still open at the end of a
  line is assumed to continue on the next line. A stray, unbalanced quote
  outside a string or comment can therefore make the rest of the file look like
  string content; the formatter leaves that part alone instead of guessing.
- Inline spacing outside `python:` blocks is limited to assignment and
  comparison operators. Arithmetic spacing is applied inside `python:` blocks,
  but not to every Ren'Py expression. Use `--no-spacing` to disable the pass.
- Quote normalization is on by default. Use `--no-quotes` or
  `normalize_quotes: false` to keep single quotes. Literals containing an
  unescaped `"` and unterminated literals are left unchanged. Range formatting
  converts a multi-line literal only when both delimiters are in the selected
  lines, so it is never left half-converted.
- Diagnostics are intentionally conservative. Newer rules are opt-in, and each
  rule can be reduced to a warning or disabled independently.
- Ruff formatting changes more than whitespace, so it is opt-in and failure-safe.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run pyright
```

- `scanner.py`: tracks strings, comments and brackets across physical lines
- `analysis.py`: logical lines and the block tree
- `index.py`: workspace symbol index for Ren'Py declarations, references and
  related declaration families
- `python_index.py`: conservative indentation parser for `python:` blocks
- `resolve.py`: shared target and occurrence resolution
- `references.py`: find-references provider
- `signature.py`: signature-help provider
- `completion.py`: context-aware completion for statements, screen bodies,
  API namespaces, audio, dialogue attributes and Python expressions
- `completion_data.py` and `data/completion.json`: versioned screen, ATL and
  keyword/value vocabulary
- `strings.py`: physical-line string spans shared by semantic tokens
- `semantic.py`: opt-in semantic tokens and UTF-16 delta encoding
- `definition.py`: literal `jump` / `call` target resolution
- `diagnostics.py`: configurable per-rule diagnostics and workspace publishing
- `code_actions.py`: safe quick fixes for diagnostics
- `symbols.py`: LSP document and workspace symbols
- `positions.py`: client-position conversion helpers
- `folding.py`: explicit block fold ranges
- `spacing.py`: inline operator spacing
- `python_format.py`: optional Ruff bridge
- `formatter.py`: indentation, blank lines, comments
- `edits.py`: old text to minimal LSP edits
- `server.py`: pygls glue (stdout carries the protocol, so log to stderr only)
- `dap.py`: launch-only Debug Adapter Protocol server, SDK/project discovery,
  output streaming and process termination
- `tests/test_formatter_renpy.py`: formatter cases, idempotency and
  "only whitespace changed" checks
- `tests/test_pipeline.py`: scanner, edits and CLI tests
- `tests/test_server_e2e.py`: starts the real server and formats over stdio
- `tests/test_dap.py`: launch configuration, SDK discovery and a fixture-SDK
  DAP session over stdio

CI runs the test suite on Python 3.10 through 3.14.

### Checked against real scripts

Run on six files from the `renpy/renpy` repository (`the_question`, `tutorial`,
`launcher`; about 4,000 lines): in every file only whitespace changed and a
second pass changed nothing. Four were already formatted and came out unchanged.

## License

MIT. See [LICENSE](LICENSE).
