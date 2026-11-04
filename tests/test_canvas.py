from webterm.canvas import CanvasRasterizer
from webterm.canvas import parse_color
from webterm.core import parse_page
from webterm.javascript import JavaScriptRuntime


def test_rectangles_paths_and_text_render_with_ansi_colors():
    canvas = CanvasRasterizer(16, 8)
    canvas.fill_style = "#ff0000"
    canvas.fill_rect(0, 0, 8, 8)
    canvas.stroke_style = "rgb(0, 255, 0)"
    canvas.begin_path()
    canvas.move_to(9, 0)
    canvas.line_to(15, 0)
    canvas.line_to(12, 7)
    canvas.close_path()
    canvas.stroke()
    canvas.fill_style = "orange"
    canvas.begin_path()
    canvas.move_to(1, 1)
    canvas.line_to(7, 1)
    canvas.line_to(4, 6)
    canvas.close_path()
    canvas.fill()
    canvas.stroke_style = "white"
    canvas.stroke_rect(0, 0, 16, 8)
    canvas.fill_style = "blue"
    canvas.text_align = "center"
    canvas.text_baseline = "top"
    canvas.draw_text("OK", 8, 4)

    output = canvas.to_ansi()

    assert "\x1b[38;2;255;0;0m" in output
    assert "\x1b[38;2;0;255;0m" in output
    assert "\x1b[38;2;255;165;0m" in output
    assert "\x1b[38;2;255;255;255m" in output
    assert "\x1b[38;2;0;0;255m" in output
    assert "O" in output and "K" in output
    assert "\x1b[0m" in output
    assert not any(character in output for character in "█▀▄")


def test_clear_rect_and_arc():
    canvas = CanvasRasterizer(12, 12)
    canvas.fill_style = "white"
    canvas.fill_rect(0, 0, 12, 12)
    canvas.clear_rect(4, 4, 4, 4)
    canvas.stroke_style = "yellow"
    canvas.begin_path()
    canvas.arc(6, 6, 3, 0, 6.283185307179586)
    canvas.stroke()

    output = canvas.to_ansi()
    assert "\x1b[38;2;255;255;0m" in output
    assert "@" in output


def test_different_pixel_rows_use_ansi_foreground_and_background():
    canvas = CanvasRasterizer(1, 2)
    canvas.fill_style = "red"
    canvas.fill_rect(0, 0, 1, 1)
    canvas.fill_style = "blue"
    canvas.fill_rect(0, 1, 1, 1)

    output = canvas.to_ansi()

    assert "\x1b[38;2;255;0;0m" in output
    assert "\x1b[48;2;0;0;255m" in output


def test_stroke_clips_large_coordinates_to_canvas_bounds():
    canvas = CanvasRasterizer(10, 10)
    canvas.stroke_style = "green"
    canvas.begin_path()
    canvas.move_to(-1_000_000_000, -1_000_000_000)
    canvas.line_to(1_000_000_000, 1_000_000_000)
    canvas.stroke()

    assert "\x1b[38;2;0;128;0m" in canvas.to_ansi()


def test_stroke_rect_handles_zero_size_and_fully_offscreen_rectangles():
    canvas = CanvasRasterizer(5, 5)
    canvas.stroke_style = "red"
    canvas.stroke_rect(2, 1, 0, 3)
    painted = {
        (x, y)
        for y, row in enumerate(canvas._pixels)
        for x, color in enumerate(row)
        if color is not None
    }
    assert painted == {(2, y) for y in range(1, 5)}

    canvas.clear_rect(0, 0, 5, 5)
    canvas.stroke_rect(-5, 1, 2, 2)
    assert not any(color for row in canvas._pixels for color in row)


def test_negative_multi_turn_arc_is_a_full_circle():
    full_circle = CanvasRasterizer(20, 20)
    full_circle.stroke_style = "red"
    full_circle.begin_path()
    full_circle.arc(10, 10, 5, 0, 2 * 3.141592653589793)
    full_circle.stroke()

    multi_turn = CanvasRasterizer(20, 20)
    multi_turn.stroke_style = "red"
    multi_turn.begin_path()
    multi_turn.arc(10, 10, 5, 0, -4 * 3.141592653589793)
    multi_turn.stroke()

    assert multi_turn._pixels == full_circle._pixels


def test_move_to_starts_an_independent_subpath():
    canvas = CanvasRasterizer(10, 10)
    canvas.stroke_style = "red"
    canvas.begin_path()
    canvas.move_to(1, 1)
    canvas.line_to(3, 1)
    canvas.move_to(6, 6)
    canvas.line_to(8, 6)
    canvas.stroke()

    painted = {
        (x, y)
        for y, row in enumerate(canvas._pixels)
        for x, color in enumerate(row)
        if color is not None
    }
    assert painted == {
        (1, 1), (2, 1), (3, 1),
        (6, 6), (7, 6), (8, 6),
    }


def test_transparent_and_percentage_css_colors():
    assert parse_color("rgba(255, 0, 0, 0)") is None
    assert parse_color("#f000") is None
    assert parse_color("#ff000000") is None
    assert parse_color("rgb(50%, 50%, 50%)") == (128, 128, 128)


def test_partial_alpha_colors_composite_into_existing_pixels():
    assert parse_color("#f008") == (255, 0, 0, 136)
    canvas = CanvasRasterizer(1, 1)
    canvas.fill_style = "rgba(255, 0, 0, 0.5)"
    canvas.fill_rect(0, 0, 1, 1)
    assert canvas._pixels[0][0] == (128, 0, 0)

    canvas.fill_style = "rgba(0, 0, 255, 50%)"
    canvas.fill_rect(0, 0, 1, 1)
    assert canvas._pixels[0][0] == (64, 0, 128)


def test_javascript_canvas_persists_into_serialized_dom():
    runtime = JavaScriptRuntime()
    try:
        runtime.reset_document('<canvas id="paint" width="12" height="8"></canvas>')
        runtime.execute("""
            const canvas = document.querySelector("#paint");
            const context = canvas.getContext("2d");
            context.fillStyle = "#12ab34";
            context.fillRect(0, 0, canvas.width, canvas.height);
        """)

        assert 'data-webterm-canvas="' in (runtime.document_html or "")
        assert "\x1b[38;2;18;171;52m" in (runtime.document_html or "")
        assert runtime.execute(
            'document.querySelector("#paint").getContext("2d") === '
            'document.querySelector("#paint").getContext("2d")'
        ) == "True"
        assert runtime.execute(
            'document.querySelector("#paint").getContext("webgl") === null'
        ) == "True"
    finally:
        runtime.close()


def test_canvas_dimension_changes_reset_state_and_follow_attributes():
    runtime = JavaScriptRuntime()
    try:
        runtime.reset_document(
            '<canvas id="paint" width="8" height="8"></canvas>'
        )
        runtime.execute("""
            const canvas = document.querySelector("#paint");
            const context = canvas.getContext("2d");
            context.fillStyle = "red";
            context.fillRect(0, 0, 8, 8);
        """)
        result = runtime.execute("""
            canvas.setAttribute("width", "20");
            String(canvas.width) + ":" + context.fillStyle;
        """)

        assert result == "20:#000000"
        assert 'width="20"' in (runtime.document_html or "")
        assert "\x1b[38;2;255;0;0m" not in (runtime.document_html or "")

        result = runtime.execute("""
            canvas.removeAttribute("width");
            String(canvas.width);
        """)
        assert result == "300"

        result = runtime.execute("""
            canvas.width = 12;
            String(canvas.width) + ":" + context.fillStyle;
        """)
        assert result == "12:#000000"
    finally:
        runtime.close()


def test_parse_page_renders_canvas_ansi_as_rich_styles():
    html = (
        '<body><canvas data-webterm-canvas="'
        '\x1b[38;2;12;34;56mX\x1b[0m"></canvas>'
        '</body>'
    )

    rendered, _, _ = parse_page(html, "https://example.test/")

    assert rendered.plain == "X"
    assert rendered.spans
    color = rendered.spans[0].style.color.get_truecolor()
    assert (color.red, color.green, color.blue) == (12, 34, 56)


def test_parse_page_sanitizes_invalid_canvas_ansi_colors():
    sequences = (
        "\x1b[38;2;999;0;0mX\x1b[0m",
        "\x1b[38;2;-1;0;0mX\x1b[0m",
        "\x1b[" + "9" * 5000 + "mX",
    )

    for sequence in sequences:
        html = (
            '<body><canvas data-webterm-canvas="'
            + sequence
            + '"></canvas></body>'
        )
        rendered, _, _ = parse_page(html, "https://example.test/")
        assert "X" in rendered.plain
        assert "\x1b" not in rendered.plain
