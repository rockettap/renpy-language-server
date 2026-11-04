# Changelog

## 0.2.1 - 2026-11-05

- Metadata and documentation refresh. The package author is now listed as
  `Oleksandr`, and the README no longer includes the screenshot or the
  roadmap. No code changes.

## 0.2.0 - 2026-11-05

- **Renamed** the project from `renpy-ls` to `renpy-language-server`. The
  Python package is now `renpy_language_server`, the CLI is
  `renpy-language-server`, and diagnostic codes use the
  `renpy-language-server.*` prefix.
- New `textDocument/codeAction` quick fixes: comparison `=` → `==`, stray `$`
  removal, leading tabs → spaces, and creating a missing label at the end of the
  file. Actions are offered only for overlapping diagnostics and never guess
  when a change would be unsafe. Controlled by the new `code_actions` setting
  (default `true`).
- Signature help now resolves user classes, module-level functions and
  `self.` / `cls.` / `Class.` methods, hiding `self`/`cls` and preserving
  parameter defaults. Arbitrary instance calls are left unresolved instead of
  guessing.
- New `workspace/symbol` provider for workspace-wide symbol search across
  labels, screens, images, characters, styles, variables, classes, members,
  stores, persistent variables, test cases and translations. Exact and prefix
  matches rank first; results are capped for large projects. Controlled by the
  new `workspace_symbols` setting (default `true`).
- Completion can omit image and audio files found on disk through the new
  `automatic_assets` setting (default `true`), matching VS Code's automatic
  image toggle. Declared images, audio channels and all other completion
  families are unaffected.
- New `renpy-language-server dap` command: a launch-only Debug Adapter Protocol server.
  It resolves the SDK from the configuration, `RENPY_SDK` or common install
  locations, finds the project containing `game/`, supports `warp`,
  `command`, `args` and `env`, streams game output, and stops the process on
  terminate or disconnect. Breakpoints, stepping, stack/scopes/variables,
  evaluate and attach are deliberately not implemented; unsupported requests
  return a clear error or an empty result.
- `renpy-language-server dap` validates `warp` targets before launching. Scripts must exist
  under the project's `game/` directory (or inside an `.rpa` archive) and have
  a label at or before the requested line. A misplaced file now fails with a
  clear message and a suggested `game/...` path instead of Ren'Py's "Could not
  find a statement to warp to" traceback.
- The formatter now rewrites single-quoted strings to double quotes, including
  dialogue, screen properties and `python:` blocks, so `'#99ccff'` becomes
  `"#99ccff"`. String values are never changed: a literal containing an
  unescaped `"`, and any unterminated literal, is left untouched. Controlled by
  the new `normalize_quotes` setting (default `true`) and
  `--quotes/--no-quotes` on the CLI. Range formatting converts a multi-line
  literal only when both of its delimiters are inside the requested range, so
  it can never leave one side single-quoted.
- The formatter now removes spaces around `=` in keyword arguments and default
  parameter values inside brackets, so `Character(u"A", color = "#00B7EB")`
  becomes `Character(u"A", color="#00B7EB")`. Top-level assignments such as
  `$ pv = ...` and `define` / `default` keep their spaced `=`, and comparison
  and augmented-assignment operators are unaffected.
- Completion documentation is sent as Markdown (`MarkupContent`), so
  ` ```renpy ` signature fences and inline code render as code blocks
  instead of literal backticks. Bundled reStructuredText roles and unmatched
  backticks are converted to plain Markdown first, so Sphinx markup no longer
  leaks into the popup.
- LSP `textDocument/semanticTokens/full` for declarations, references, bundled
  APIs, obsolete APIs, keywords, parameters, strings and numbers. Tokens use
  UTF-16 positions and declaration/definition/defaultLibrary/deprecated
  modifiers. Controlled by the new `semantic_tokens` setting, which defaults to
  `false` until tree-sitter and semantic highlighting are validated together.
- Completion covers `jump` / `call` labels, `use` and screen statements,
  `show` / `scene` / `hide` images and `expression`, `at` transforms, `with`
  transitions, audio channels/assets/options, and user/automatic audio.
- Bundled API namespaces complete after `renpy.`, `renpy.music.`,
  `renpy.audio.`, `config.` and `gui.`; callable built-ins insert `name()`.
- Screen bodies complete element keywords, element-aware properties and
  property values, including actions and displayables. Dialogue completes image
  attributes for the speaking character.
- `$`, `if` / `elif` / `while`, `python:` blocks and `define` / `default`
  assignments complete Python keywords, constants and built-ins.
- Added `data/completion.json` for versioned screen/ATL vocabulary and the
  MIT-licensed `renpyauto` keyword/value table.
- Completion triggers now include `(`, `@` and `-` alongside space, colon and
  dot.
- Diagnostics are now configurable per rule through `diagnostic_rules`, with
  `error`, `warning` and `off` severities and stable `renpy-language-server.<rule>` codes.
- New rules for tab indentation, filename conventions, invalid and reserved
  `define` / `default` names, `=` vs `==`, stray `$`, obsolete APIs, undefined
  persistent and store variables, duplicate labels, unknown images and
  undefined screens. Newer rules default to `off`.
- New `diagnostics_mode` setting: `open` checks open documents, while
  `workspace` publishes diagnostics for every indexed file on startup,
  configuration, save and watched-file events. Closed and deleted files are
  cleared.
- `unknown_label_diagnostics` is retained as a compatibility switch for the
  `unknown_label` rule.
- The workspace index now records Python classes, functions, methods,
  properties, fields, store boundaries, persistent variables, test cases and
  translations. Class and store members are nested in `textDocument/documentSymbol`.
- Navigation understands unambiguous member access: `self.field`, `Class.member`,
  `persistent.value`, `store.value` and class base names. Two classes may use the
  same field or method name without their references colliding.
- Completion after `Class.` and `self.` lists indexed members; `persistent.` and
  `store.` list persistent fields and variables. The server now triggers
  completion on `.`.
- New `extended_index` and `member_references` settings; both default to `true`.
  Changing either one rebuilds the workspace index.
- Class, function, method, field, property, store, persistent, test case and
  translation rename is intentionally not enabled yet; references, highlights,
  hover and go-to-definition work for them.
- Internal: per-document analyses are cached on the index, and Python-body
  indexing has symbol/reference caps plus a large-file fallback.
- Internal: symbol lookup and occurrence enumeration now live in a shared
  resolver used by rename, highlights and future navigation providers.
- LSP `textDocument/references` for labels (global, dotted and local), screens,
  transforms, images, layered images, characters, styles and variables across
  every indexed file. `includeDeclaration` is respected.
- New `references` setting to disable find-references; it defaults to `true`.
- Go-to-definition now resolves labels, screens (`use` and screen statements),
  transforms (`at`), images and layered images, characters (speakers), styles
  (`is`) and variables, from declarations or references. Built-ins without a
  real source file still return no location.
- LSP `textDocument/signatureHelp` for bundled API calls and for labels and
  screens declared with parameters. It tracks the active parameter across
  nested calls, strings and multi-line calls.
- New `signature` setting to disable signature help; it defaults to `true`.
- LSP `textDocument/hover` for declarations and references: labels, screens,
  transforms, images, layered images, characters, `jump` / `call` targets,
  `show` / `scene` / `hide` images, `at` transforms, `use` and
  `call` / `show` / `hide` `screen` statements, and dialogue speakers.
- Hover shows the declaration kind and full name, source location, declaration
  parameters and the contiguous comment block above the declaration. Local
  labels show both the full name and the written form.
- Hover falls back to automatic images found under `game/images` and to the
  bundled Ren'Py API table, including signatures and documentation.
- The workspace index now records references, declaration parameters, and
  `style` / `layeredimage` declarations.
- Automatic image and audio asset index for `game/images`, `game/audio` and
  root-level `images` / `audio` folders; it is rescanned on watched-file and
  workspace-folder changes.
- Automatic images appear in `show` / `scene` / `hide` completion and
  go-to-definition opens the image file. Declared images and layered images
  still take precedence.
- Bundled Ren'Py API data from the MIT-licensed `vscode-language-renpy`
  extension. See `NOTICE.md`.
- New `hover` setting to disable hover; it defaults to `true`.
- LSP `textDocument/prepareRename` and `textDocument/rename` for labels
  (global, dotted and local), screens, transforms, images, layered images,
  characters and styles. Rename updates declarations and indexed references
  across the workspace, preserves `.local` / `global.local` written forms, and
  refuses invalid names and non-symbol positions.
- `define` and `default` variables are now indexed as document symbols. Rename
  updates their declarations, ordinary uses, cross-file uses and dialogue
  interpolation such as `"[ambience]"`; attribute access and keyword-argument
  names are left alone.
- Variable declarations with an init priority (`define -1 foo = ...`) and the
  `+=` / `|=` operators are indexed and renamed.
- Rename no longer treats Ren'Py syntax as variables: statement and
  screen-language keywords, audio channel names, `with` / `as` / `onlayer` /
  `behind` clauses, dialogue attributes and screen-local `default` variables
  are protected. Rename also works from continuation lines.
- LSP `textDocument/documentHighlight` for the symbol under the cursor.
  Declarations are reported as writes and references as reads, so Zed shades
  all occurrences while editing and renaming.
- New `highlight` setting to disable occurrence highlights; it defaults to
  `true`.
- New `rename` setting to disable rename; it defaults to `true`.
- Style parent references (`style dark is base`) are now indexed and appear in
  hover and rename; dialogue-speaker references are restricted to label and
  translation blocks to avoid matching screen and style properties.
- Workspace index for labels, screens, transforms, images and characters in
  `.rpy` and `.rpym` files, updated on open, change, save and watched-file
  events.
- LSP `textDocument/completion` for Ren'Py statements and symbols from the
  whole workspace. Current-file symbols take precedence over duplicates.
- Completion is context-aware: images after `show` / `scene` / `hide`, labels
  after `jump` / `call`, screens after `call screen`, and characters at the
  start of a statement.
- Completion is suppressed inside strings and comments.
- LSP `textDocument/documentSymbol` for labels, screens, transforms, images and
  characters.
- LSP `textDocument/definition` for literal `jump` / `call` targets, including
  targets in other files.
- Local labels (`.local`) are indexed under their full `global.local` name,
  resolved against the most recent global label for go-to-definition and
  unknown-label diagnostics, and still shown as written in symbol ranges.
- Diagnostics for inconsistent indentation and unknown literal `jump` / `call`
  labels, published with a debounce and cleared on close.
- Server settings from `initializationOptions` and
  `workspace/didChangeConfiguration`.
- Inline spacing for Python-ish statements: assignment and comparison
  operators are normalized, so `$ points=1` becomes `$ points = 1`. Strings,
  comments, dialogue, screen properties, ATL and keyword arguments are left
  untouched.
- Inline spacing inside `python:` blocks now covers arithmetic and bitwise
  operators while leaving unary operators, slices, `*args`, `**kwargs` and
  keyword arguments alone.
- Optional Ruff formatting for `python:` block bodies via `--python` or the
  `format_python` setting. Missing Ruff, invalid Python and timeouts leave the
  block unchanged.
- `renpy-language-server format --no-spacing` disables the inline-spacing pass.
- LSP `textDocument/rangeFormatting`; formatting still runs on the whole file
  for indentation context but returns edits only in the requested lines.
- LSP `textDocument/foldingRange` with explicit block ranges for labels, menus,
  menu choices, screens, transforms and nested blocks. This avoids overlapping
  folds between adjacent menu choices.
- Folding excludes trailing blank lines and never creates ranges inside
  multi-line strings or bracket continuations.
- Formatting edit positions now go through the client position codec, so
  non-ASCII text uses correct UTF-16 columns.

## 0.1.0

- LSP `textDocument/formatting` with minimal line edits.
- `renpy-language-server format` CLI with `--check`, `--diff`, stdin and directory support.
- Whitespace-only formatter: indentation, trailing whitespace, blank lines,
  block spacing, end-of-file newline, CRLF preservation and assignment
  alignment.
- Scanner that leaves multi-line strings and bracket continuations untouched.
- Quiet logging by default; `RENPY_LANGUAGE_SERVER_DEBUG=1` enables JSON-RPC logs.
- Handles `workspace/didChangeConfiguration` without a pygls warning.
- Python 3.10+ support and CI across Python 3.10-3.14.
