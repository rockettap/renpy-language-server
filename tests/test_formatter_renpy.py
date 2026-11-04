"""Test the formatter with real-world Ren'Py code examples."""

from renpy_language_server.formatter import FormatOptions, format_source

DEFAULT = FormatOptions()


def fmt(source: str, options: FormatOptions | None = None) -> str:
    return format_source(source, options or DEFAULT)


class TestBasicIndentation:
    def test_label_block(self) -> None:
        src = 'label start:\n  e "Hello!"\n  e "Goodbye!"\n'
        result = fmt(src)
        assert result == ('label start:\n    e "Hello!"\n    e "Goodbye!"\n')

    def test_nested_blocks(self) -> None:
        src = (
            "label start:\n"
            "  menu:\n"
            '    "Choice A":\n'
            "      jump a\n"
            '    "Choice B":\n'
            "      jump b\n"
        )
        result = fmt(src)
        assert result == (
            "label start:\n"
            "    menu:\n"
            '        "Choice A":\n'
            "            jump a\n"
            '        "Choice B":\n'
            "            jump b\n"
        )

    def test_tab_expansion(self) -> None:
        src = 'label start:\n\te "Tabs should become spaces."\n'
        result = fmt(src)
        assert result == ('label start:\n    e "Tabs should become spaces."\n')

    def test_custom_indent(self) -> None:
        src = 'label start:\n    e "Hello!"\n'
        result = fmt(src, FormatOptions(indent=2))
        assert result == ('label start:\n  e "Hello!"\n')


class TestBlankLines:
    def test_blank_line_before_top_level_blocks(self) -> None:
        src = "label start:\n    return\nlabel another:\n    return\n"
        result = fmt(src)
        assert "\n\nlabel another:" in result

    def test_blank_line_before_screen(self) -> None:
        src = 'label start:\n    return\nscreen my_screen():\n    text "hello"\n'
        result = fmt(src)
        assert "\n\nscreen my_screen():" in result

    def test_max_blank_lines_capped(self) -> None:
        src = "label start:\n    return\n\n\n\n\n\nlabel next:\n    return\n"
        result = fmt(src)
        # By default max_blank_lines=2, so at most 2 consecutive blanks.
        assert "\n\n\n\n" not in result

    def test_no_leading_blank_lines(self) -> None:
        src = "\n\n\nlabel start:\n    return\n"
        result = fmt(src)
        assert result.startswith("label start:")

    def test_no_trailing_blank_lines(self) -> None:
        src = "label start:\n    return\n\n\n\n"
        result = fmt(src)
        assert result.endswith("return\n")


class TestTrailingWhitespace:
    def test_trailing_spaces_removed(self) -> None:
        src = 'label start:   \n    e "Hello!"   \n'
        result = fmt(src)
        for line in result.split("\n"):
            if line:  # skip the empty tail
                assert line == line.rstrip(), f"Trailing whitespace in: {line!r}"


class TestLineEndings:
    def test_lf_preserved(self) -> None:
        src = "label start:\n    return\n"
        result = fmt(src)
        assert "\r\n" not in result

    def test_crlf_preserved(self) -> None:
        src = "label start:\r\n    return\r\n"
        result = fmt(src)
        assert "\r\n" in result
        # Should not have bare \n (all \n should be preceded by \r)
        stripped = result.replace("\r\n", "")
        assert "\n" not in stripped


class TestStrings:
    def test_single_line_string(self) -> None:
        src = 'label start:\n    e "This is a normal string."\n'
        result = fmt(src)
        assert '"This is a normal string."' in result

    def test_multiline_triple_quoted_string(self) -> None:
        """Triple-quoted strings should be left verbatim inside."""
        src = (
            "label start:\n"
            '    e """\n'
            "    This is a multi-line\n"
            "        string with indentation.\n"
            '    """\n'
        )
        result = fmt(src)
        # The interior lines of the string should be preserved.
        assert "    This is a multi-line\n" in result
        assert "        string with indentation.\n" in result

    def test_string_with_special_chars(self) -> None:
        src = 'label start:\n    $ name = "O\'Brien"\n'
        result = fmt(src)
        assert '"O\'Brien"' in result


class TestComments:
    def test_comment_indentation(self) -> None:
        src = 'label start:\n  # A comment inside the block\n  e "Hello!"\n'
        result = fmt(src)
        assert "    # A comment inside the block\n" in result

    def test_comment_before_block_keyword(self) -> None:
        """A comment directly above a block keyword should stay attached."""
        src = (
            "label start:\n"
            "    return\n"
            "# This describes the next label\n"
            "label next:\n"
            "    return\n"
        )
        result = fmt(src)
        # The blank line should be *before* the comment, not between the
        # comment and the label.
        idx_comment = result.index("# This describes")
        idx_label = result.index("label next:")
        between = result[idx_comment:idx_label]
        assert "\n\n" not in between


class TestAlignEquals:
    def test_consecutive_assignments_are_aligned(self) -> None:
        src = (
            "label start:\n"
            '    $ pv = Character("Pavlo")\n'
            '    $ doter_me = Character("Doter")\n'
        )
        result = fmt(src)
        assert result == (
            "label start:\n"
            '    $ pv       = Character("Pavlo")\n'
            '    $ doter_me = Character("Doter")\n'
        )

    def test_already_aligned_is_stable(self) -> None:
        src = (
            "label start:\n"
            '    $ pv       = Character("Pavlo")\n'
            '    $ doter_me = Character("Doter")\n'
            '    $ mk       = Character("Mykhailo")\n'
        )
        assert fmt(src) == src

    def test_define_and_default_align(self) -> None:
        src = 'define e = Character("Eileen")\ndefault points = 0\n'
        result = fmt(src)
        assert result == ('define e       = Character("Eileen")\ndefault points = 0\n')

    def test_group_breaks_on_other_statement(self) -> None:
        src = (
            "label start:\n"
            "    $ a = 1\n"
            "    $ longer = 2\n"
            "    return\n"
            "    $ b = 3\n"
            "    $ longer2 = 4\n"
        )
        result = fmt(src)
        assert "    $ a      = 1\n" in result
        assert "    $ longer = 2\n" in result
        assert "    return\n" in result
        assert "    $ b       = 3\n" in result
        assert "    $ longer2 = 4\n" in result

    def test_comments_break_the_group(self) -> None:
        src = "label start:\n    $ a = 1\n    # a note\n    $ longer = 2\n"
        result = fmt(src)
        assert "    $ a = 1\n" in result
        assert "    $ longer = 2\n" in result

    def test_operators_are_not_assignments(self) -> None:
        src = "label start:\n    $ a == b\n    $ c += 1\n    $ d != e\n"
        result = fmt(src)
        assert "    $ a == b\n" in result
        assert "    $ c += 1\n" in result
        assert "    $ d != e\n" in result

    def test_keyword_arguments_are_tightened(self) -> None:
        src = (
            "label start:\n"
            '    $ a = Character("A", color="#fff")\n'
            '    $ bb = Character("B", color="#000")\n'
        )
        result = fmt(src)
        assert '    $ a  = Character("A", color="#fff")\n' in result
        assert '    $ bb = Character("B", color="#000")\n' in result

    def test_keyword_argument_equals_loses_spaces(self) -> None:
        src = (
            "label start:\n"
            '    $ a = Character("A", color = "#fff")\n'
            '    $ bb = Character("B", color = "#000", what_color ="#111")\n'
        )
        result = fmt(src)
        assert '    $ a  = Character("A", color="#fff")\n' in result
        assert '    $ bb = Character("B", color="#000", what_color="#111")\n' in result

    def test_trailing_comment_is_kept(self) -> None:
        src = "label start:\n    $ a = 1  # one\n    $ longer = 2  # two\n"
        result = fmt(src)
        assert "    $ a      = 1  # one\n" in result
        assert "    $ longer = 2  # two\n" in result

    def test_different_indentation_levels_do_not_align(self) -> None:
        src = "label start:\n    $ a = 1\n    if x:\n        $ long = 2\n"
        result = fmt(src)
        assert "    $ a = 1\n" in result
        assert "        $ long = 2\n" in result

    def test_can_be_disabled(self) -> None:
        src = (
            "label start:\n"
            '    $ pv = Character("Pavlo")\n'
            '    $ doter_me = Character("Doter")\n'
        )
        result = fmt(src, FormatOptions(align_equals=False))
        assert result == (
            "label start:\n"
            '    $ pv = Character("Pavlo")\n'
            '    $ doter_me = Character("Doter")\n'
        )

    def test_existing_argument_padding_is_preserved(self) -> None:
        src = (
            "label start:\n"
            '    $ pv = Character (u"A",   color = "#fff")\n'
            '    $ doter_me = Character (u"B", color = "#000")\n'
        )
        result = fmt(src)
        assert result == (
            "label start:\n"
            '    $ pv       = Character (u"A",   color="#fff")\n'
            '    $ doter_me = Character (u"B", color="#000")\n'
        )

    def test_alignment_is_idempotent(self) -> None:
        src = (
            "label start:\n"
            '    $ pv = Character("Pavlo")\n'
            '    $ doter_me = Character("Doter")\n'
        )
        once = fmt(src)
        assert fmt(once) == once


class TestRealWorldRenPy:
    """Format a realistic Ren'Py script and verify it round-trips."""

    REALISTIC_SCRIPT: str = """\
init:
    $ e             = Character("Eileen", color="#c8ffc8")
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
    e "You finished the demonstration script successfully."
    hide screen choice_counter_overlay
    return
"""

    def test_already_formatted_is_idempotent(self) -> None:
        """Well-formatted code should not change at all."""
        result = fmt(self.REALISTIC_SCRIPT)
        assert result == self.REALISTIC_SCRIPT

    def test_format_is_idempotent(self) -> None:
        """Formatting twice should give the same result as formatting once."""
        first = fmt(self.REALISTIC_SCRIPT)
        second = fmt(first)
        assert first == second

    def test_messy_indentation_fixed(self) -> None:
        messy = """\
init:
  $ e = Character("Eileen", color="#c8ffc8")
  $ player_points = 0
transform bounce_in:
  alpha 0.0
  zoom 0.5
label start:
  scene solid "#333333"
  e "Hello!"
  menu:
    "Option A":
      jump a
    "Option B":
      jump b
label continuation:
  return
"""
        result = fmt(messy)
        # Verify correct indentation
        lines = result.strip().split("\n")
        for line in lines:
            if line.strip():
                # Leading spaces should be a multiple of 4
                stripped = line.lstrip(" ")
                indent_count = len(line) - len(stripped)
                assert indent_count % 4 == 0, (
                    f"Indent not a multiple of 4: {line!r} (indent={indent_count})"
                )

    def test_init_python_block(self) -> None:
        src = "init python:\n  import os\n  def my_func():\n    return 42\n"
        result = fmt(src)
        assert result.startswith("init python:\n")
        assert "    import os\n" in result

    def test_screen_with_if(self) -> None:
        src = (
            "screen inventory():\n"
            "  vbox:\n"
            "    for item in inventory_items:\n"
            "      if item.equipped:\n"
            '        text "{} [equipped]" % item.name\n'
            "      else:\n"
            "        text item.name\n"
        )
        result = fmt(src)
        assert "    vbox:\n" in result
        assert "        for item in inventory_items:\n" in result

    def test_define_and_default(self) -> None:
        src = (
            'define e = Character("Eileen")\n'
            "default points = 0\n"
            "label start:\n"
            "    return\n"
        )
        result = fmt(src)
        assert result.startswith('define e       = Character("Eileen")\n')
        assert "default points = 0\n" in result

    def test_python_inline(self) -> None:
        src = "label start:\n  $ renpy.pause(1.0)\n  $ result = max(a, b)\n"
        result = fmt(src)
        assert "    $ renpy.pause(1.0)\n" in result
        assert "    $ result = max(a, b)\n" in result


class TestEdgeCases:
    def test_empty_file(self) -> None:
        assert fmt("") == ""

    def test_blank_only_file(self) -> None:
        assert fmt("\n\n\n") == ""

    def test_single_line(self) -> None:
        assert fmt("label start:\n") == "label start:\n"

    def test_comment_only_file(self) -> None:
        result = fmt("# Just a comment\n")
        assert result == "# Just a comment\n"

    def test_backslash_continuation(self) -> None:
        src = "label start:\n    $ long_value = 1 + \\\n        2 + \\\n        3\n"
        result = fmt(src)
        # Should keep all three lines; continuation lines have shifted indent.
        assert "1 + \\\n" in result
        assert "3\n" in result

    def test_parenthesized_continuation(self) -> None:
        src = "label start:\n    $ value = (\n        1 +\n        2\n    )\n"
        result = fmt(src)
        assert "$ value = (\n" in result
        assert "    )\n" in result
