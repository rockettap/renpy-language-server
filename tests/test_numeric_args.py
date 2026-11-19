"""Tests for numeric duration argument normalization."""

from renpy_language_server.formatter import FormatOptions, format_source
from renpy_language_server.numeric_args import ATL_WARPERS


def fmt(source: str, options: FormatOptions | None = None) -> str:
    return format_source(source, options or FormatOptions())


class TestPause:
    def test_bare_float_is_the_default(self) -> None:
        assert fmt("pause 1\n") == "pause 1.0\n"

    def test_parens_style(self) -> None:
        result = fmt("pause 1\n", FormatOptions(numeric_style="parens"))
        assert result == "pause (1.0)\n"

    def test_existing_parentheses_are_replaced_in_bare_style(self) -> None:
        assert fmt("pause (1)\n") == "pause 1.0\n"
        assert fmt("pause ((1.0))\n") == "pause 1.0\n"

    def test_parens_style_keeps_exactly_one_pair(self) -> None:
        result = fmt("pause ((1))\n", FormatOptions(numeric_style="parens"))
        assert result == "pause (1.0)\n"

    def test_float_conversion_can_be_disabled(self) -> None:
        options = FormatOptions(numeric_floats=False)
        assert fmt("pause 1\n", options) == "pause 1\n"

    def test_float_conversion_does_not_shrink_existing_floats(self) -> None:
        options = FormatOptions(numeric_floats=False)
        assert fmt("pause 1.0\n", options) == "pause 1.0\n"

    def test_already_normalized_is_stable(self) -> None:
        assert fmt("pause 1.0\n") == "pause 1.0\n"
        assert fmt("pause -0.5\n") == "pause -0.5\n"

    def test_complex_expressions_are_left_alone(self) -> None:
        for source in (
            "pause delay\n",
            "pause delay + 1\n",
            "pause max(1, 2)\n",
            "pause 1 if x else 2\n",
            "pause [1][0]\n",
        ):
            assert fmt(source) == source

    def test_comments_and_spacing_are_preserved(self) -> None:
        assert fmt("pause 1  # one second\n") == "pause 1.0  # one second\n"

    def test_no_argument_is_unchanged(self) -> None:
        assert fmt("pause\n") == "pause\n"


class TestAtl:
    def test_pause_in_a_transform(self) -> None:
        source = "transform f:\n    pause 1\n"
        assert "    pause 1.0\n" in fmt(source)

    def test_bare_number_statement(self) -> None:
        source = "transform f:\n    1\n"
        assert "    1.0\n" in fmt(source)

    def test_builtin_warper(self) -> None:
        source = "transform f:\n    linear 1 xpos 100\n"
        result = fmt(source)
        assert "    linear 1.0 xpos 100\n" in result
        assert "xpos 100" in result

    def test_easing_warper(self) -> None:
        source = "transform f:\n    easein_quad 2 yoffset -15\n"
        assert "    easein_quad 2.0 yoffset -15\n" in fmt(source)

    def test_warper_block_form(self) -> None:
        source = "transform f:\n    linear 1:\n        xpos 100\n"
        assert "    linear 1.0:\n" in fmt(source)

    def test_warp_function(self) -> None:
        source = "transform f:\n    warp my_warpers[0] 3 xpos 520\n"
        result = fmt(source)
        assert "    warp my_warpers[0] 3.0 xpos 520\n" in result

    def test_custom_warper(self) -> None:
        source = "transform f:\n    my_warper 1 xpos 100\n"
        assert "    my_warper 1 xpos 100\n" in fmt(source)
        result = fmt(
            source,
            FormatOptions(numeric_warpers=ATL_WARPERS | {"my_warper"}),
        )
        assert "    my_warper 1.0 xpos 100\n" in result

    def test_time_statement(self) -> None:
        source = "transform f:\n    time 1\n"
        assert "    time 1.0\n" in fmt(source)

    def test_delay_property(self) -> None:
        source = "transform f:\n    delay 2\n"
        assert "    delay 2.0\n" in fmt(source)

    def test_warper_outside_atl_is_untouched(self) -> None:
        source = "label start:\n    linear 1\n"
        assert "    linear 1\n" in fmt(source)

    def test_show_block_is_atl(self) -> None:
        source = "show logo:\n    linear 1 xpos 100\n"
        assert "    linear 1.0 xpos 100\n" in fmt(source)

    def test_show_screen_is_not_atl(self) -> None:
        source = "show screen overlay:\n    linear 1\n"
        assert "    linear 1\n" in fmt(source)

    def test_property_values_are_untouched(self) -> None:
        source = (
            "transform f:\n"
            "    alpha 0\n"
            "    xpos 100\n"
            "    yoffset -15\n"
            "    repeat 3\n"
            "    linear 1 xpos 100 yoffset -15\n"
        )
        result = fmt(source)
        assert "    alpha 0\n" in result
        assert "    xpos 100\n" in result
        assert "    yoffset -15\n" in result
        assert "    repeat 3\n" in result
        assert "    linear 1.0 xpos 100 yoffset -15\n" in result


class TestScreenTimer:
    def test_timer_in_a_screen(self) -> None:
        source = (
            'screen s():\n    timer 1 action Function(refresh)\n    text "x" size 20\n'
        )
        result = fmt(source)
        assert "    timer 1.0 action Function(refresh)\n" in result
        assert '    text "x" size 20\n' in result

    def test_timer_in_nested_screen_block(self) -> None:
        source = "screen s():\n    frame:\n        timer 1 action NullAction()\n"
        assert "        timer 1.0 action NullAction()\n" in fmt(source)

    def test_timer_outside_a_screen_is_untouched(self) -> None:
        source = "label start:\n    timer 1\n"
        assert "    timer 1\n" in fmt(source)

    def test_parens_style_in_a_screen(self) -> None:
        source = "screen s():\n    timer 1\n"
        result = fmt(source, FormatOptions(numeric_style="parens"))
        assert "    timer (1.0)\n" in result


class TestAudio:
    def test_fadein_and_fadeout(self) -> None:
        source = 'play music "theme.ogg" fadein 1 fadeout 2 volume 0.5\n'
        result = fmt(source)
        assert "fadein 1.0 fadeout 2.0 volume 0.5" in result

    def test_queue_and_stop(self) -> None:
        source = 'queue music "next.ogg" fadein 1\nstop music fadeout 2\n'
        result = fmt(source)
        assert 'queue music "next.ogg" fadein 1.0\n' in result
        assert "stop music fadeout 2.0\n" in result

    def test_fade_text_inside_a_string_is_untouched(self) -> None:
        source = 'play music "fadein 2.ogg" fadein 1\n'
        result = fmt(source)
        assert 'play music "fadein 2.ogg" fadein 1.0\n' in result

    def test_complex_fade_expression_is_untouched(self) -> None:
        source = 'play music "theme.ogg" fadein 1 + 2\n'
        assert fmt(source) == source


class TestTestcase:
    def test_pause_and_timeout(self) -> None:
        source = "testcase run:\n    pause 1\n    timeout 5\n    pause 2\n"
        result = fmt(source)
        assert "    pause 1.0\n" in result
        assert "    timeout 5.0\n" in result
        assert "    pause 2.0\n" in result

    def test_timeout_outside_a_testcase_is_untouched(self) -> None:
        source = "label start:\n    timeout 5\n"
        assert "    timeout 5\n" in fmt(source)

    def test_testsuite_setup_and_teardown(self) -> None:
        source = (
            "testsuite suite:\n"
            "    setup:\n"
            "        timeout 1\n"
            "    testcase run:\n"
            "        pause 2\n"
            "    teardown:\n"
            "        timeout 3\n"
        )
        result = fmt(source)
        assert "        timeout 1.0\n" in result
        assert "        pause 2.0\n" in result
        assert "        timeout 3.0\n" in result


class TestConfiguration:
    def test_numeric_normalization_can_be_disabled(self) -> None:
        source = "label start:\n    pause 1\n    linear 1\n"
        result = fmt(source, FormatOptions(normalize_numeric_args=False))
        assert "    pause 1\n" in result
        assert "    linear 1\n" in result

    def test_families_can_be_selected(self) -> None:
        source = "label start:\n    pause 1\n\ntransform f:\n    linear 1\n"
        result = fmt(source, FormatOptions(numeric_families=frozenset({"atl"})))
        assert "    pause 1\n" in result
        assert "    linear 1.0\n" in result

    def test_formatting_is_idempotent(self) -> None:
        source = (
            "label start:\n"
            "    pause 1\n"
            '    play music "x.ogg" fadein 1\n'
            "\n"
            "transform f:\n"
            "    linear 1 xpos 100\n"
            "\n"
            "screen s():\n"
            "    timer 1\n"
            "\n"
            "testcase t:\n"
            "    timeout 5\n"
        )
        for options in (
            FormatOptions(),
            FormatOptions(numeric_style="parens"),
            FormatOptions(numeric_floats=False),
        ):
            once = fmt(source, options)
            assert fmt(once, options) == once
