from webterm.dom import DOMDocument

def test_document_query_selector():
    document = DOMDocument(
        '<main><p class="intro">Hello</p><p>World</p></main>'
    )

    result = document.query_selector("p.intro")

    assert result is not None
    assert result.tag_name == "P"
    assert result.text_content == "Hello"


def test_document_query_selector_all():
    document = DOMDocument(
        '<ul><li class="item">A</li><li class="item">B</li></ul>'
    )

    results = document.query_selector_all("li.item")

    assert len(results) == 2
    assert [item.text_content for item in results] == ["A", "B"]


def test_element_query_selector_is_scoped_to_descendants():
    document = DOMDocument(
        '<section id="first"><p>Inside</p></section>'
        '<section id="second"><p>Outside</p></section>'
    )
    section = document.get_element_by_id("first")

    result = section.query_selector("p")

    assert result is not None
    assert result.text_content == "Inside"
    assert section.query_selector("#second") is None


def test_query_selector_returns_none_when_no_match():
    document = DOMDocument("<p>Hello</p>")

    assert document.query_selector(".missing") is None


def test_query_selector_all_returns_empty_list_when_no_match():
    document = DOMDocument("<p>Hello</p>")

    assert document.query_selector_all(".missing") == []
