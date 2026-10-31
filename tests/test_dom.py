from webterm.dom import (
    COMMENT_NODE,
    DOCUMENT_NODE,
    ELEMENT_NODE,
    TEXT_NODE,
    DOMDocument,
)


def test_document_and_element_node_types():
    document = DOMDocument("<html><body><p>Hello</p></body></html>")

    html = document.document_element
    body = html.first_element_child
    paragraph = body.first_element_child
    text = paragraph.first_child

    assert document.node_type == DOCUMENT_NODE
    assert html.node_type == ELEMENT_NODE
    assert paragraph.node_type == ELEMENT_NODE
    assert text.node_type == TEXT_NODE


def test_parent_child_relationships():
    document = DOMDocument("<div><p>Text</p></div>")

    div = document.document_element.first_element_child
    paragraph = div.first_element_child

    assert paragraph.parent_node._node is div._node
    assert div.children == [paragraph]
    assert div.child_nodes == [paragraph]


def test_text_and_comment_nodes():
    document = DOMDocument("<p>Hello<!-- note -->world</p>")
    paragraph = document.document_element.first_element_child

    children = paragraph.child_nodes

    assert [node.node_type for node in children] == [
        TEXT_NODE,
        COMMENT_NODE,
        TEXT_NODE,
    ]
    assert children[0].node_value == "Hello"
    assert children[1].node_value == " note "
    assert paragraph.text_content == "Helloworld"


def test_sibling_navigation():
    document = DOMDocument("<ul><li>A</li> text <li>B</li></ul>")
    ul = document.document_element.first_element_child

    first_li = ul.first_element_child
    second_li = ul.last_element_child

    assert first_li.next_element_sibling._node is second_li._node
    assert second_li.previous_element_sibling._node is first_li._node
    assert first_li.previous_sibling is None


def test_depth_first_traversal():
    document = DOMDocument("<main><p>A</p><section><b>B</b></section></main>")

    names = [
        node.node_name
        for node in document.iter_nodes()
    ]

    assert names == [
        "#document",
        "HTML",
        "MAIN",
        "P",
        "#text",
        "SECTION",
        "B",
        "#text",
    ]


def test_iter_elements_excludes_text_nodes():
    document = DOMDocument("<div>Text <span>Nested</span></div>")

    names = [
        node.node_name
        for node in document.iter_elements()
    ]

    assert names == ["HTML", "DIV", "SPAN"]


def test_document_title_and_serialization():
    document = DOMDocument(
        "<!doctype html><html><head><title>Example</title></head>"
        "<body><p>Hello</p></body></html>"
    )

    assert document.title == "Example"
    assert document.doctype is not None
    assert "<p>Hello</p>" in document.serialize()