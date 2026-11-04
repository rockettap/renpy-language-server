"""Test the scanner + edits modules and the full LSP formatting pipeline."""

from pathlib import Path

import pytest

from renpy_language_server.edits import apply_edits, compute_edits
from renpy_language_server.formatter import FormatOptions, format_source
from renpy_language_server.scanner import State, scan_line


class TestScanner:
    def test_clean_line(self) -> None:
        info = scan_line('e "Hello!"', State())
        assert info.start.clean
        assert info.end.clean

    def test_open_bracket(self) -> None:
        info = scan_line("$ value = (", State())
        assert info.end.depth == 1
        assert not info.end.clean

    def test_close_bracket(self) -> None:
        info = scan_line(")", State(depth=1))
        assert info.end.depth == 0
        assert info.end.clean

    def test_triple_quote_opens(self) -> None:
        info = scan_line('e """', State())
        assert info.end.quote == '"""'
        assert not info.end.clean

    def test_triple_quote_closes(self) -> None:
        info = scan_line('This is inside."""', State(quote='"""'))
        assert info.end.quote is None
        assert info.end.clean

    def test_single_quote_string(self) -> None:
        info = scan_line("$ x = 'hello'", State())
        assert info.end.quote is None
        assert info.end.clean

    def test_unclosed_single_quote(self) -> None:
        info = scan_line("$ x = 'hello", State())
        assert info.end.quote == "'"
        assert not info.end.clean

    def test_backslash_continuation(self) -> None:
        info = scan_line("$ x = 1 + \\", State())
        assert info.end.backslash
        assert not info.end.clean

    def test_comment_no_backslash(self) -> None:
        info = scan_line("# a comment with trailing \\", State())
        assert not info.end.backslash

    def test_last_char_colon(self) -> None:
        info = scan_line("label start:", State())
        assert info.last_char == ":"

    def test_last_char_in_comment_line(self) -> None:
        info = scan_line("x = 1  # comment", State())
        assert info.last_char == "1"

    def test_escaped_quote(self) -> None:
        info = scan_line(r'"escaped \" quote"', State())
        assert info.end.quote is None
        assert info.end.clean

    def test_nested_brackets(self) -> None:
        info = scan_line("$ f((a, b), [c])", State())
        assert info.end.depth == 0

    def test_nested_brackets_partial(self) -> None:
        info = scan_line("$ f((a, b),", State())
        assert info.end.depth == 1  # outer paren still open


class TestEdits:
    def test_no_change(self) -> None:
        assert compute_edits("hello\n", "hello\n") == []

    def test_single_line_change(self) -> None:
        edits = compute_edits("  hello\n", "    hello\n")
        assert len(edits) == 1
        result = apply_edits("  hello\n", edits)
        assert result == "    hello\n"

    def test_multiline_roundtrip(self) -> None:
        old = "a\nb\nc\n"
        new = "a\nB\nc\n"
        edits = compute_edits(old, new)
        assert apply_edits(old, edits) == new

    def test_insertion(self) -> None:
        old = "a\nc\n"
        new = "a\nb\nc\n"
        edits = compute_edits(old, new)
        assert apply_edits(old, edits) == new

    def test_deletion(self) -> None:
        old = "a\nb\nc\n"
        new = "a\nc\n"
        edits = compute_edits(old, new)
        assert apply_edits(old, edits) == new


class TestFullPipeline:
    """Simulates what the LSP server does: format, compute edits, apply them."""

    MESSY_SCRIPT: str = """\
init:
  $ e = Character("Eileen", color="#c8ffc8")
  $ player_points = 0
transform bounce_in:
  alpha 0.0
  zoom 0.5
  yalign 1.0
  easein 0.5 alpha 1.0 zoom 1.0 yoffset 0
  block:
    easeout 1.0 yoffset -15
    easein 1.0 yoffset 0
    repeat
screen choice_counter_overlay():
  frame:
    xalign 0.98
    yalign 0.02
    padding (10, 10)
    hbox:
      spacing 10
      text "Points:" size 20
      text "[player_points]" size 20 color "#ff0"
label start:
  scene solid "#333333"
  show screen choice_counter_overlay
  "Welcome to the Ren'Py feature showcase script!"
  show eileen happy at bounce_in
  e "As you can see, I am bouncing thanks to a custom transform block."
  menu:
    "Give me 10 points!":
      $ player_points += 10
      e "Awesome! You gained 10 points."
      jump continuation
    "Take away 5 points!":
      $ player_points -= 5
      e "Ouch! Points decreased."
      jump continuation
label continuation:
  e "You finished the demonstration."
  hide screen choice_counter_overlay
  return
"""

    def test_pipeline_roundtrip(self) -> None:
        """format → compute_edits → apply_edits must equal format_source."""
        formatted = format_source(self.MESSY_SCRIPT)
        edits = compute_edits(self.MESSY_SCRIPT, formatted)
        applied = apply_edits(self.MESSY_SCRIPT, edits)
        assert applied == formatted

    def test_pipeline_idempotent(self) -> None:
        """Applying the pipeline twice should produce no further edits."""
        formatted = format_source(self.MESSY_SCRIPT)
        second_edits = compute_edits(formatted, format_source(formatted))
        assert second_edits == []

    def test_pipeline_with_crlf(self) -> None:
        crlf = self.MESSY_SCRIPT.replace("\n", "\r\n")
        formatted = format_source(crlf)
        edits = compute_edits(crlf, formatted)
        applied = apply_edits(crlf, edits)
        assert applied == formatted
        assert "\r\n" in applied

    def test_pipeline_preserves_semantics(self) -> None:
        """Formatting should only change whitespace, never content."""
        formatted = format_source(self.MESSY_SCRIPT)
        # Strip all whitespace from both and compare
        original_tokens = self.MESSY_SCRIPT.split()
        formatted_tokens = formatted.split()
        assert original_tokens == formatted_tokens

    def test_pipeline_with_custom_indent(self) -> None:
        formatted = format_source(self.MESSY_SCRIPT, FormatOptions(indent=2))
        edits = compute_edits(self.MESSY_SCRIPT, formatted)
        applied = apply_edits(self.MESSY_SCRIPT, edits)
        assert applied == formatted


class TestCLI:
    def test_version(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "renpy_language_server", "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.startswith("renpy-language-server ")

    def test_main_format_stdin(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import io

        from renpy_language_server.cli import main

        messy = 'label start:\n  e "Hello!"\n'
        monkeypatch.setattr("sys.stdin", io.StringIO(messy))
        rc = main(["format", "-"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out == 'label start:\n    e "Hello!"\n'

    def test_main_format_file(self, tmp_path: Path) -> None:
        from renpy_language_server.cli import main

        f = tmp_path / "test.rpy"
        f.write_text('label start:\n  e "Hello!"\n', encoding="utf-8")
        rc = main(["format", str(f)])
        assert rc == 0
        assert f.read_text(encoding="utf-8") == 'label start:\n    e "Hello!"\n'

    def test_main_format_check(self, tmp_path: Path) -> None:
        from renpy_language_server.cli import main

        f = tmp_path / "test.rpy"
        f.write_text('label start:\n  e "Hello!"\n', encoding="utf-8")
        rc = main(["format", "--check", str(f)])
        assert rc == 1
        # File should NOT have been modified
        assert f.read_text(encoding="utf-8") == 'label start:\n  e "Hello!"\n'

    def test_main_format_no_spacing(self, tmp_path: Path) -> None:
        from renpy_language_server.cli import main

        f = tmp_path / "test.rpy"
        f.write_text("$ points=1\n", encoding="utf-8")
        rc = main(["format", "--no-spacing", str(f)])
        assert rc == 0
        assert f.read_text(encoding="utf-8") == "$ points=1\n"

    def test_main_format_spacing_is_on_by_default(self, tmp_path: Path) -> None:
        from renpy_language_server.cli import main

        f = tmp_path / "test.rpy"
        f.write_text("$ points=1\n", encoding="utf-8")
        rc = main(["format", str(f)])
        assert rc == 0
        assert f.read_text(encoding="utf-8") == "$ points = 1\n"

    def test_main_format_quotes_are_on_by_default(self, tmp_path: Path) -> None:
        from renpy_language_server.cli import main

        f = tmp_path / "test.rpy"
        f.write_text("define accent = '#99ccff'\n", encoding="utf-8")
        rc = main(["format", str(f)])
        assert rc == 0
        assert f.read_text(encoding="utf-8") == 'define accent = "#99ccff"\n'

    def test_main_format_no_quotes(self, tmp_path: Path) -> None:
        from renpy_language_server.cli import main

        f = tmp_path / "test.rpy"
        source = "define accent = '#99ccff'\n"
        f.write_text(source, encoding="utf-8")
        rc = main(["format", "--no-quotes", str(f)])
        assert rc == 0
        assert f.read_text(encoding="utf-8") == source

    def test_main_format_python_is_opt_in(self, tmp_path: Path) -> None:
        from renpy_language_server.cli import main

        f = tmp_path / "test.rpy"
        source = "python:\n    values=[1,2 ,3]\n"
        f.write_text(source, encoding="utf-8")

        assert main(["format", str(f)]) == 0
        assert f.read_text(encoding="utf-8") == "python:\n    values = [1,2 ,3]\n"

        assert main(["format", "--python", str(f)]) == 0
        assert f.read_text(encoding="utf-8") == "python:\n    values = [1, 2, 3]\n"

    def test_main_format_diff(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from renpy_language_server.cli import main

        f = tmp_path / "test.rpy"
        f.write_text('label start:\n  e "Hello!"\n', encoding="utf-8")
        rc = main(["format", "--diff", str(f)])
        assert rc == 1
        captured = capsys.readouterr()
        assert "---" in captured.out
        assert "+++" in captured.out

    def test_main_format_already_formatted(self, tmp_path: Path) -> None:
        from renpy_language_server.cli import main

        f = tmp_path / "test.rpy"
        f.write_text('label start:\n    e "Hello!"\n', encoding="utf-8")
        rc = main(["format", "--check", str(f)])
        assert rc == 0

    def test_main_format_directory(self, tmp_path: Path) -> None:
        from renpy_language_server.cli import main

        (tmp_path / "a.rpy").write_text("label a:\n  return\n", encoding="utf-8")
        (tmp_path / "b.rpy").write_text("label b:\n  return\n", encoding="utf-8")
        rc = main(["format", str(tmp_path)])
        assert rc == 0
        assert (tmp_path / "a.rpy").read_text(
            encoding="utf-8"
        ) == "label a:\n    return\n"
        assert (tmp_path / "b.rpy").read_text(
            encoding="utf-8"
        ) == "label b:\n    return\n"
