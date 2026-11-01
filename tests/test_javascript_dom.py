
from webterm.javascript import JavaScriptRuntime


def test_runtime_loads_document():
    runtime = JavaScriptRuntime()
    try:
        runtime.reset_document(
            '<html><body><p id="message">Hello</p></body></html>'
        )

        assert "Hello" in runtime.document_html
    finally:
        runtime.close()


def test_click_event_fires_once():
    runtime = JavaScriptRuntime()
    try:
        runtime.reset_document("""
            <button id="button">Click</button>
            <p id="result">0</p>
            <script>
                let count = 0;
                document.querySelector("#button").addEventListener(
                    "click",
                    () => {
                        count++;
                        document.querySelector("#result").textContent = count;
                    }
                );
            </script>
        """)

        runtime.execute("""
            let count = 0;
            document.querySelector("#button").addEventListener(
                "click",
                () => {
                    count++;
                    document.querySelector("#result").textContent = count;
                }
            );
        """)

        runtime.dispatch_event('#button', 'click')

        assert ">1<" in runtime.document_html
    finally:
        runtime.close()


def test_prevent_default_cancels_navigation():
    runtime = JavaScriptRuntime()
    try:
        runtime.reset_document("""
            <a id="link" href="/next">Next</a>
            <p id="result">Before</p>
        """)

        runtime.execute("""
            document.querySelector("#link").addEventListener(
                "click",
                event => {
                    event.preventDefault();
                    document.querySelector("#result").textContent = "Canceled";
                }
            );
        """)

        allowed = runtime.dispatch_event('#link', 'click')

        assert allowed is False
        assert "Canceled" in runtime.document_html
    finally:
        runtime.close()


def test_reset_document_clears_previous_page():
    runtime = JavaScriptRuntime()
    try:
        runtime.reset_document('<p id="old">Old page</p>')
        runtime.reset_document('<p id="new">New page</p>')

        assert "New page" in runtime.document_html
        assert "Old page" not in runtime.document_html
    finally:
        runtime.close()
