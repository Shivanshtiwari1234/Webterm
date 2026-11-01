from types import SimpleNamespace

from webterm.page_widget import ClickablePage


def test_wrap_line_keeps_combining_mark_with_base_character():
    assert ClickablePage._wrap_line("a\u0301b", 1) == [
        (0, "a\u0301"),
        (2, "b"),
    ]


def test_wrap_line_keeps_joined_emoji_together():
    family = "👨‍👩‍👧‍👦"

    assert ClickablePage._wrap_line(f"{family}x", 2) == [
        (0, family),
        (len(family), "x"),
    ]


def test_position_after_combining_mark_maps_to_visible_character():
    page = SimpleNamespace(
        content_region=SimpleNamespace(x=0, y=0),
        _visual_lines=lambda: [(10, 13, "a\u0301b")],
    )

    assert ClickablePage._position_at(page, 1, 0) == 12


def test_position_in_second_cell_of_wide_grapheme_maps_to_grapheme_start():
    family = "👨‍👩‍👧‍👦"
    page = SimpleNamespace(
        content_region=SimpleNamespace(x=0, y=0),
        _visual_lines=lambda: [(4, 4 + len(family), family)],
    )

    assert ClickablePage._position_at(page, 1, 0) == 4