from webterm.canvas import CanvasRasterizer
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
            'document.querySelector("#paint").getContext("webgl") === null'
        ) == "True"
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
