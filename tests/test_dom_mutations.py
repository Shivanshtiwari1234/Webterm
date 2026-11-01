import pytest

from webterm.dom import DOMDocument, DOMElement, DOMNode, ELEMENT_NODE, TEXT_NODE


@pytest.fixture
def document():
    return DOMDocument("<html><body><div id='root'><p id='a'>A</p><p id='b'>B</p></div></body></html>")


def test_create_element_and_text_node(document):
    div = document.create_element("div")
    text = document.create_text_node("hello")
    div.append_child(text)
    assert div.tag_name == "DIV"
    assert div.text_content == "hello"
    assert text.node_type == TEXT_NODE


def test_append_and_parent_relationship(document):
    root = document.get_element_by_id("root")
    child = document.create_element("span")
    root.append_child(child)
    assert child.parent_node == root
    assert root.last_child == child


def test_insert_before_and_sibling_order(document):
    root = document.get_element_by_id("root")
    a = document.get_element_by_id("a")
    b = document.get_element_by_id("b")
    inserted = document.create_element("em")
    root.insert_before(inserted, b)
    assert root.child_nodes == [a, inserted, b]
    assert inserted.next_sibling == b
    assert b.previous_sibling == inserted


def test_remove_child(document):
    root = document.get_element_by_id("root")
    a = document.get_element_by_id("a")
    removed = root.remove_child(a)
    assert removed == a
    assert a.parent_node is None
    assert document.get_element_by_id("a") is None


def test_replace_child(document):
    root = document.get_element_by_id("root")
    old = document.get_element_by_id("a")
    new = document.create_element("section")
    root.replace_child(new, old)
    assert root.child_nodes[0] == new
    assert document.get_element_by_id("a") is None


def test_text_content_setter(document):
    root = document.get_element_by_id("root")
    root.text_content = "replacement"
    assert root.text_content == "replacement"
    assert root.children == []
    assert root.inner_html == "replacement"


def test_attributes_and_id_class_properties(document):
    a = document.get_element_by_id("a")
    a.set_attribute("data-x", "1")
    a.id = "renamed"
    a.class_name = "active highlighted"
    assert a.get_attribute("data-x") == "1"
    assert a.id == "renamed"
    assert a.class_name == "active highlighted"
    assert document.get_element_by_id("renamed") == a
    a.remove_attribute("data-x")
    assert not a.has_attribute("data-x")


def test_inner_html_setter(document):
    a = document.get_element_by_id("a")
    a.inner_html = "<strong>changed</strong>"
    assert a.query_selector("strong") is not None
    assert a.text_content == "changed"


def test_outer_html_setter(document):
    a = document.get_element_by_id("a")
    a.outer_html = "<article id='replacement'>new</article>"
    assert document.get_element_by_id("replacement") is not None
    assert document.get_element_by_id("a") is None


def test_invalid_insert_reference_raises(document):
    root = document.get_element_by_id("root")
    foreign = document.create_element("i")
    with pytest.raises(ValueError):
        root.insert_before(foreign, document.create_element("b"))


def test_query_selector_all_after_mutation(document):
    root = document.get_element_by_id("root")
    root.append_child(document.create_element("p"))
    assert len(document.query_selector_all("#root p")) == 3
