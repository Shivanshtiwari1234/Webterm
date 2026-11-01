import pytest
from webterm.javascript import JavaScriptRuntime


@pytest.fixture
def runtime():
    rt = JavaScriptRuntime(timeout=5)
    try:
        yield rt
    finally:
        rt.close()


def test_javascript_can_create_and_append_element(runtime):
    html = "<html><body><div id='root'></div></body></html>"

    runtime.execute("""
        const node = document.createElement('p');
        node.textContent = 'hello from JS';
        document.getElementById('root').appendChild(node);
    """, document_html=html)

    assert runtime.document_html is not None, (
        f"document_html is None; runtime messages: {runtime.console_messages}"
    )
    assert "<p>hello from JS</p>" in runtime.document_html


def test_javascript_can_change_attributes(runtime):
    html = "<html><body><div id='root'></div></body></html>"
    runtime.execute("""
        const root = document.getElementById('root');
        root.setAttribute('data-state', 'ready');
        root.className = 'active';
    """, document_html=html)
    assert 'data-state="ready"' in runtime.document_html
    assert 'class="active"' in runtime.document_html


def test_javascript_can_remove_node(runtime):
    html = "<html><body><p id='remove'>bye</p><p>keep</p></body></html>"
    runtime.execute("document.getElementById('remove').remove();", document_html=html)
    assert 'id="remove"' not in runtime.document_html
    assert "<p>keep</p>" in runtime.document_html


def test_javascript_can_replace_inner_html(runtime):
    html = "<html><body><div id='root'>old</div></body></html>"
    runtime.execute("""
        document.getElementById('root').innerHTML = '<b>new</b>';
    """, document_html=html)
    assert "<b>new</b>" in runtime.document_html
    assert "old" not in runtime.document_html
