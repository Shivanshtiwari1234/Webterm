
from webterm.dom import DOMDocument, DOMElement


def test_element_interface_and_attributes():
    document = DOMDocument('<p id="intro" class="lead wide">Hello</p>')
    paragraph = document.get_element_by_id("intro")

    assert isinstance(paragraph, DOMElement)
    assert paragraph.tag_name == "P"
    assert paragraph.id == "intro"
    assert paragraph.class_name == "lead wide"
    assert paragraph.get_attribute("class") == "lead wide"
    assert paragraph.has_attribute("id")
    assert not paragraph.has_attribute("missing")


def test_element_attributes_are_copied():
    document = DOMDocument('<div id="original"></div>')
    element = document.get_element_by_id("original")

    attributes = element.attributes
    attributes["id"] = "changed"

    assert element.id == "original"


def test_element_inner_and_outer_html():
    document = DOMDocument('<section><b>Bold</b> text</section>')
    section = document.get_elements_by_tag_name("section")[0]

    assert section.inner_html == "<b>Bold</b> text"
    assert section.outer_html == "<section><b>Bold</b> text</section>"


def test_document_lookup_by_id():
    document = DOMDocument('<div id="one"></div><p id="two"></p>')

    assert document.get_element_by_id("one").tag_name == "DIV"
    assert document.get_element_by_id("missing") is None


def test_document_lookup_by_tag_name():
    document = DOMDocument("<ul><li>A</li><li>B</li></ul>")

    items = document.get_elements_by_tag_name("li")

    assert len(items) == 2
    assert [item.text_content for item in items] == ["A", "B"]


def test_document_create_element():
    document = DOMDocument()
    element = document.create_element("custom-widget")

    assert isinstance(element, DOMElement)
    assert element.tag_name == "CUSTOM-WIDGET"
    assert element.node_type == 1


def test_create_element_rejects_invalid_names():
    document = DOMDocument()

    for name in ("", "custom widget"):
        try:
            document.create_element(name)
        except ValueError:
            pass
        else:
            raise AssertionError("Expected ValueError")
