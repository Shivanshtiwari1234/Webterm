from webterm.javascript import JavaScriptRuntime


def test_document_query_selector_and_text_content():
    with JavaScriptRuntime() as runtime:
        result = runtime.execute(
            'document.querySelector("p.intro").textContent',
            document_html='<main><p class="intro">Hello</p></main>',
        )

    assert result == "Hello"


def test_document_query_selector_all():
    with JavaScriptRuntime() as runtime:
        result = runtime.execute(
            'document.querySelectorAll("li.item").length',
            document_html='<ul><li class="item">A</li><li class="item">B</li></ul>',
        )

    assert result == "2"


def test_get_element_by_id_and_attributes():
    with JavaScriptRuntime() as runtime:
        result = runtime.execute(
            """
            const el = document.getElementById("target");
            el.tagName + "|" + el.id + "|" + el.className + "|" +
            el.getAttribute("data-x") + "|" + el.hasAttribute("data-x")
            """,
            document_html='<div id="target" class="box" data-x="yes">Hi</div>',
        )

    assert result == "DIV|target|box|yes|true"


def test_element_tree_traversal():
    with JavaScriptRuntime() as runtime:
        result = runtime.execute(
            """
            const parent = document.querySelector("ul");
            parent.children.length + "|" +
            parent.firstElementChild.textContent + "|" +
            parent.lastElementChild.textContent
            """,
            document_html="<ul><li>A</li><li>B</li></ul>",
        )

    assert result == "2|A|B"


def test_document_title():
    with JavaScriptRuntime() as runtime:
        result = runtime.execute(
            "document.title",
            document_html="<html><head><title>Webterm</title></head><body></body></html>",
        )

    assert result == "Webterm"


def test_console_log_still_works_with_dom():
    with JavaScriptRuntime() as runtime:
        runtime.execute(
            'console.log(document.querySelector("p").textContent)',
            document_html="<p>Hello</p>",
        )

    assert "Hello" in runtime.console_messages