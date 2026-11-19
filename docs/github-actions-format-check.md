# Format-check Ren'Py scripts in GitHub Actions

This tutorial creates a GitHub Actions workflow that runs the
`renpy-language-server` formatter in check mode. The job fails when a `.rpy` or
`.rpym` file is not formatted. Mark the job as a required status check in branch
protection to block merges until the files are formatted.

You do not need a published GitHub Action: the workflow installs the CLI and
runs `renpy-language-server format --check`.

## What you will build

A workflow at `.github/workflows/renpy-format.yml` that:

- runs on every push to `main` and on every pull request;
- installs a pinned version of `renpy-language-server` with
  [uv](https://docs.astral.sh/uv/);
- checks every Ren'Py script under `game/`;
- fails with exit code 1 when formatting changes are needed.

## Before you start

- A repository containing a Ren'Py project, usually with a `game/` directory.
- The workflow needs only read access to the repository.
- Python is not required on the runner: `uvx` downloads its own Python when
  needed.

## Step 1: Format the project locally

Run the formatter once and commit the result. This gives CI a clean baseline
instead of failing on pre-existing formatting.

```bash
# One-off run with uv (no permanent install)
uvx renpy-language-server format game/

# Or install the CLI
uv tool install renpy-language-server
renpy-language-server format game/
```

Directories are searched recursively for `.rpy` and `.rpym` files.

Review the changes before committing:

```bash
git diff --stat
git diff game/
git add game/
git commit -m "Format Ren'Py scripts"
```

Confirm that the project is now clean:

```bash
uvx renpy-language-server format --check game/
echo $?   # 0
```

## Step 2: Create the workflow

Create `.github/workflows/renpy-format.yml`:

```yaml
name: Ren'Py format

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  format-check:
    name: Format check
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Check Ren'Py formatting
        run: uvx renpy-language-server@0.2.2 format --check game/
```

Commit and push the workflow. The next push or pull request runs it. If your
default branch is not `main`, change the branch name under `on.push`.

To make the check block merges, open **Settings → Branches** (or **Rules**),
add a branch protection rule for `main`, and mark the **Format check** job as a
required status check.

### What each part does

| Part                              | Purpose                                                    |
| --------------------------------- | ---------------------------------------------------------- |
| `on: pull_request`                | Checks every pull request, including pushes to the branch. |
| `permissions: contents: read`     | Gives the job only the access it needs.                    |
| `actions/checkout@v4`             | Puts the repository in the runner workspace.               |
| `astral-sh/setup-uv@v5`           | Installs uv and caches downloaded packages.                |
| `uvx renpy-language-server@0.2.2` | Runs a pinned CLI version without a separate install step. |
| `format --check game/`            | Verifies formatting and exits non-zero on changes.         |

Pin the version (`@0.2.2`) so a new release cannot change the formatter output
in an unrelated pull request. When adding the workflow, pin whatever the
[latest version](https://pypi.org/project/renpy-language-server/) is at that
time. Update the pin deliberately, together with a formatting commit.

## Step 3: Understand the result

On a formatted repository the job succeeds and the formatter prints nothing.

When a file needs formatting, `--check` writes one line per file to stderr and
exits with code 1:

```text
would reformat game/script.rpy
would reformat game/tl/french/script.rpy
```

The job fails, which is the point. Fix it locally and push:

```bash
uvx renpy-language-server format game/
git add game/
git commit -m "Format Ren'Py scripts"
```

Exit codes used by the command:

| Code | Meaning                                                           |
| ---- | ----------------------------------------------------------------- |
| `0`  | All files are formatted, or no `.rpy` / `.rpym` files were found. |
| `1`  | At least one file would change (with `--check` or `--diff`).      |
| `2`  | Invalid command-line usage, such as an unknown option.            |

> **Do not run `format` without `--check` or `--diff` in CI.** It rewrites files
> inside the temporary runner and exits 0, so the job passes even though the
> committed files are still unformatted.

## Step 4: Show a diff on failure

`--check` names the files; `--diff` prints the exact unified diff and also
exits 1 on changes. Replace the last step with:

```yaml
- name: Check Ren'Py formatting
  run: uvx renpy-language-server@0.2.2 format --diff game/
```

The workflow log then shows what the formatter wants to change:

```diff
--- game/script.rpy
+++ game/script.rpy
@@ -1,3 +1,3 @@
 label start:
-    $ points=1
+    $ points = 1
     return
```

If both options are passed, the diff is printed and the command still exits 1;
`--diff` takes precedence over the per-file messages.

## Step 5: Match your project's style

The CLI flags mirror the formatter settings used by the language server. Pass
the same options in CI and when formatting locally.

| Flag                         | Default       | Use it when                                         |
| ---------------------------- | ------------- | --------------------------------------------------- |
| `--indent N`                 | `4`           | Your project uses a different indentation width.    |
| `--quotes` / `--no-quotes`   | `--quotes`    | You want to keep single-quoted strings.             |
| `--spacing` / `--no-spacing` | `--spacing`   | You do not want operator spacing normalized.        |
| `--python` / `--no-python`   | `--no-python` | You also want `python:` blocks formatted with Ruff. |

For example, a project with two-space indentation and single quotes:

```yaml
- name: Check Ren'Py formatting
  run: >-
    uvx renpy-language-server@0.2.2 format
    --indent 2
    --no-quotes
    --check game/
```

### Formatting `python:` blocks with Ruff

`--python` is opt-in because Ruff changes more than whitespace. It is provided
by the `python-format` extra, so select it with `uvx --from`:

```yaml
- name: Check Ren'Py formatting
  run: >-
    uvx --from "renpy-language-server[python-format]==0.2.2"
    renpy-language-server format
    --python
    --check game/
```

Use the same command locally before pushing.

## Step 6 (optional): Add inline pull-request annotations

The CLI does not emit GitHub annotations itself. A short shell wrapper can turn
each `would reformat` line into an error annotation on the changed file:

```yaml
- name: Check Ren'Py formatting
  shell: bash
  run: |
    set +e
    output="$(uvx renpy-language-server@0.2.2 format --check game/ 2>&1)"
    rc=$?
    printf '%s\n' "$output"
    while IFS= read -r line; do
      case "$line" in
        "would reformat "*)
          file="${line#would reformat }"
          echo "::error file=${file},title=Ren'Py formatting::Run 'renpy-language-server format ${file}' and commit the result."
          ;;
      esac
    done <<< "$output"
    exit "$rc"
```

Annotations appear on the pull request's **Files changed** tab, in addition to
the job log.

## Alternative: use pip instead of uv

If your workflow already uses Python, install the pinned package with pip:

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"

- name: Install formatter
  run: pip install renpy-language-server==0.2.2

- name: Check Ren'Py formatting
  run: renpy-language-server format --check game/
```

The uv version is faster and caches tool downloads across runs.

## Troubleshooting

**The job passes but nothing was checked.** The path does not contain Ren'Py
scripts, or it is misspelled. Only `.rpy` and `.rpym` files are considered:

```bash
find game -type f \( -name '*.rpy' -o -name '*.rpym' \) | head
```

**A file is still reported after you formatted it.** The local and CI versions
or flags differ. Pin the same version and pass the same `--indent`,
`--quotes`, `--spacing` and `--python` options in both places.

**Line endings changed unexpectedly.** The formatter preserves LF and CRLF as
found in each file. Check that Git is not rewriting line endings on checkout;
if needed, add a `.gitattributes` entry such as `*.rpy text eol=lf`.

**`--python` fails to install Ruff.** The option requires the extra. Use the
`uvx --from "renpy-language-server[python-format]==0.2.2"` form shown above, or
`pip install "renpy-language-server[python-format]==0.2.2"`.

**The workflow fails with exit code 2.** That is a usage error, not a
formatting failure. Run the same command locally to see the message, and check
for a mistyped flag or a missing path argument.

## Full reference workflow

```yaml
name: Ren'Py format

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  format-check:
    name: Format check
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Check Ren'Py formatting
        shell: bash
        run: |
          set +e
          output="$(uvx renpy-language-server@0.2.2 format --check game/ 2>&1)"
          rc=$?
          printf '%s\n' "$output"
          while IFS= read -r line; do
            case "$line" in
              "would reformat "*)
                file="${line#would reformat }"
                echo "::error file=${file},title=Ren'Py formatting::Run 'renpy-language-server format ${file}' and commit the result."
                ;;
            esac
          done <<< "$output"
          exit "$rc"
```

To check a different directory or several paths, list them all:

```bash
uvx renpy-language-server@0.2.2 format --check game/ tools/ extra.rpy
```
