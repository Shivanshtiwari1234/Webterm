from __future__ import annotations

import json
import multiprocessing as mp
import time
from multiprocessing.connection import Connection


def _javascript_worker(
    conn: Connection,
    memory_limit_mb: int,
) -> None:
    """Execute JavaScript inside an isolated worker process."""
    try:
        import quickjs

        from .dom import DOMDocument, DOMElement, DOMNode

        context = quickjs.Context()
        context.set_memory_limit(memory_limit_mb * 1024 * 1024)

        document: DOMDocument | None = None
        nodes: dict[int, DOMNode] = {}
        node_ids: dict[int, int] = {}
        next_node_id = 1

        def log(level: str, message: str) -> None:
            try:
                conn.send(("log", level, message))
            except (BrokenPipeError, EOFError, OSError):
                pass

        def register(node: DOMNode | None) -> int | None:
            nonlocal next_node_id
            if node is None:
                return None

            identity = id(node._node)
            if identity in node_ids:
                return node_ids[identity]

            node_id = next_node_id
            next_node_id += 1
            node_ids[identity] = node_id
            nodes[node_id] = node
            return node_id

        def get_node(node_id: int) -> DOMNode | None:
            return nodes.get(int(node_id))

        def dom_call(operation: str, args_json: str) -> str:
            """Perform a read-only DOM operation and return JSON."""
            try:
                args = json.loads(args_json)
                node_id = args.get("node")
                node = get_node(node_id) if node_id is not None else None

                if operation == "document":
                    return json.dumps({
                        "node": register(document),
                        "title": document.title if document else "",
                        "documentElement": (
                            register(document.document_element) if document else None
                        ),
                    })

                if operation == "getElementById":
                    result = document.get_element_by_id(args["id"]) if document else None
                    return json.dumps(register(result))

                if operation == "getElementsByTagName":
                    results = (
                        document.get_elements_by_tag_name(args["tag"])
                        if document else []
                    )
                    return json.dumps([register(item) for item in results])

                if operation in {"querySelector", "querySelectorAll"}:
                    selector = args["selector"]
                    if isinstance(node, DOMElement):
                        first = node.query_selector(selector)
                        all_results = node.query_selector_all(selector)
                    elif document:
                        first = document.query_selector(selector)
                        all_results = document.query_selector_all(selector)
                    else:
                        first, all_results = None, []

                    if operation == "querySelector":
                        return json.dumps(register(first))
                    return json.dumps([register(item) for item in all_results])

                if node is None:
                    return json.dumps(None)

                if operation == "property":
                    name = args["name"]
                    properties = {
                        "nodeType": node.node_type,
                        "nodeName": node.node_name,
                        "nodeValue": node.node_value,
                        "textContent": node.text_content,
                        "parentNode": register(node.parent_node),
                        "childNodes": [register(child) for child in node.child_nodes],
                        "firstChild": register(node.first_child),
                        "lastChild": register(node.last_child),
                        "previousSibling": register(node.previous_sibling),
                        "nextSibling": register(node.next_sibling),
                    }

                    if isinstance(node, DOMElement):
                        properties.update({
                            "tagName": node.tag_name,
                            "id": node.id,
                            "className": node.class_name,
                            "innerHTML": node.inner_html,
                            "outerHTML": node.outer_html,
                            "children": [register(child) for child in node.children],
                            "firstElementChild": register(node.first_element_child),
                            "lastElementChild": register(node.last_element_child),
                            "childElementCount": node.child_element_count,
                        })

                    return json.dumps(properties.get(name))

                if operation == "getAttribute":
                    return json.dumps(
                        node.get_attribute(args["name"])
                        if isinstance(node, DOMElement) else None
                    )

                if operation == "hasAttribute":
                    return json.dumps(
                        node.has_attribute(args["name"])
                        if isinstance(node, DOMElement) else False
                    )

                if operation == "elementQuerySelector":
                    result = (
                        node.query_selector(args["selector"])
                        if isinstance(node, DOMElement) else None
                    )
                    return json.dumps(register(result))

                if operation == "elementQuerySelectorAll":
                    results = (
                        node.query_selector_all(args["selector"])
                        if isinstance(node, DOMElement) else []
                    )
                    return json.dumps([register(item) for item in results])

                return json.dumps(None)

            except Exception as exc:
                return json.dumps({"error": str(exc)})

        context.add_callable("__webterm_dom_call", dom_call)
        context.add_callable("__webterm_log", lambda message: log("log", message))
        context.add_callable("__webterm_warn", lambda message: log("warn", message))
        context.add_callable("__webterm_error", lambda message: log("error", message))

        context.eval("""
            globalThis.console = {
                log: (...args) => __webterm_log(args.map(String).join(" ")),
                info: (...args) => __webterm_log(args.map(String).join(" ")),
                warn: (...args) => __webterm_warn(args.map(String).join(" ")),
                error: (...args) => __webterm_error(args.map(String).join(" "))
            };

            const __domCall = (operation, args = {}) => {
                const result = JSON.parse(
                    __webterm_dom_call(operation, JSON.stringify(args))
                );
                if (result && typeof result === "object" && "error" in result) {
                    throw new Error(result.error);
                }
                return result;
            };

            const __nodeCache = new Map();

            function __wrapNode(id) {
                if (id === null || id === undefined) return null;
                if (__nodeCache.has(id)) return __nodeCache.get(id);

                const node = {};
                Object.defineProperty(node, "__id", { value: id });

                const property = name => __domCall("property", {
                    node: id, name
                });

                for (const name of [
                    "nodeType", "nodeName", "nodeValue", "textContent",
                    "tagName", "id", "className", "innerHTML", "outerHTML",
                    "childElementCount"
                ]) {
                    Object.defineProperty(node, name, {
                        get: () => property(name),
                        configurable: true
                    });
                }

                for (const name of [
                    "parentNode", "firstChild", "lastChild",
                    "previousSibling", "nextSibling",
                    "firstElementChild", "lastElementChild"
                ]) {
                    Object.defineProperty(node, name, {
                        get: () => __wrapNode(property(name)),
                        configurable: true
                    });
                }

                for (const name of ["childNodes", "children"]) {
                    Object.defineProperty(node, name, {
                        get: () => (property(name) || []).map(__wrapNode),
                        configurable: true
                    });
                }

                node.getAttribute = name =>
                    __domCall("getAttribute", { node: id, name: String(name) });
                node.hasAttribute = name =>
                    __domCall("hasAttribute", { node: id, name: String(name) });
                node.querySelector = selector =>
                    __wrapNode(__domCall("elementQuerySelector", {
                        node: id, selector: String(selector)
                    }));
                node.querySelectorAll = selector =>
                    __domCall("elementQuerySelectorAll", {
                        node: id, selector: String(selector)
                    }).map(__wrapNode);

                __nodeCache.set(id, node);
                return node;
            }

            globalThis.document = {
                get title() {
                    return __domCall("document").title;
                },
                get documentElement() {
                    return __wrapNode(__domCall("document").documentElement);
                },
                getElementById: id =>
                    __wrapNode(__domCall("getElementById", { id: String(id) })),
                getElementsByTagName: tag =>
                    __domCall("getElementsByTagName", { tag: String(tag) })
                        .map(__wrapNode),
                querySelector: selector =>
                    __wrapNode(__domCall("querySelector", {
                        selector: String(selector)
                    })),
                querySelectorAll: selector =>
                    __domCall("querySelectorAll", {
                        selector: String(selector)
                    }).map(__wrapNode)
            };
        """)

        conn.send(("ready", None))

        while True:
            try:
                message = conn.recv()
            except (EOFError, OSError):
                break

            command = message[0]

            if command == "close":
                break

            if command != "execute":
                continue

            source, html = message[1], message[2]

            document = DOMDocument(html) if html is not None else None
            nodes.clear()
            node_ids.clear()
            next_node_id = 1

            try:
                result = context.eval(source)
                result = None if result is None else str(result)
                conn.send(("result", result))
            except Exception as exc:
                conn.send(("error", str(exc)))

            conn.send(("done", None))

    except BaseException as exc:
        try:
            conn.send(("fatal", str(exc)))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        conn.close()


class JavaScriptRuntime:
    """A persistent JavaScript worker dedicated to one browser tab."""

    def __init__(
        self,
        timeout: float = 2.0,
        memory_limit_mb: int = 32,
        startup_timeout: float = 10.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if memory_limit_mb < 8:
            raise ValueError("memory_limit_mb must be at least 8")
        if startup_timeout <= 0:
            raise ValueError("startup_timeout must be greater than zero")

        self.timeout = timeout
        self.memory_limit_mb = memory_limit_mb
        self.startup_timeout = startup_timeout
        self.console_messages: list[str] = []
        self._closed = False

        self._ctx = mp.get_context("spawn")
        self._parent: Connection | None = None
        self._process: mp.Process | None = None
        self._start_worker()

    def _start_worker(self) -> None:
        if self._closed:
            raise RuntimeError("JavaScript runtime is closed")

        parent, child = self._ctx.Pipe(duplex=True)
        process = self._ctx.Process(
            target=_javascript_worker,
            args=(child, self.memory_limit_mb),
            name="Webterm-JavaScript",
            daemon=True,
        )

        try:
            process.start()
        except Exception:
            parent.close()
            child.close()
            raise
        finally:
            child.close()

        self._parent = parent
        self._process = process
        deadline = time.monotonic() + self.startup_timeout

        while time.monotonic() < deadline:
            if parent.poll(0.05):
                try:
                    message = parent.recv()
                except (EOFError, OSError):
                    break

                kind, *values = message
                if kind == "ready":
                    return
                if kind == "fatal":
                    error = values[0] if values else "Unknown worker error"
                    self._stop_worker()
                    raise RuntimeError(
                        f"JavaScript worker failed to initialize: {error}"
                    )

            if not process.is_alive():
                break

        self._stop_worker()
        raise RuntimeError("JavaScript worker failed to start")

    def _stop_worker(self) -> None:
        process, parent = self._process, self._parent
        self._process = None
        self._parent = None

        if parent is not None:
            try:
                parent.close()
            except OSError:
                pass

        if process is None:
            return

        try:
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.5)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
        finally:
            if not process.is_alive():
                process.close()

    def _ensure_worker(self) -> bool:
        if self._closed:
            raise RuntimeError("JavaScript runtime is closed")
        if self._process is not None and self._process.is_alive():
            return True

        self._stop_worker()
        try:
            self._start_worker()
            return True
        except (OSError, RuntimeError) as exc:
            self.console_messages.append(
                f"[JavaScript worker error] Could not start worker: {exc}"
            )
            return False

    def execute(
        self,
        source: str,
        document_html: str | None = None,
    ) -> str | None:
        """Execute JavaScript, optionally binding it to an HTML document snapshot."""
        if self._closed:
            raise RuntimeError("JavaScript runtime is closed")
        if not isinstance(source, str):
            raise TypeError("source must be a string")
        if document_html is not None and not isinstance(document_html, str):
            raise TypeError("document_html must be a string")

        if not self._ensure_worker():
            return None

        assert self._parent is not None
        assert self._process is not None

        try:
            self._parent.send(("execute", source, document_html))
        except (BrokenPipeError, EOFError, OSError) as exc:
            self.console_messages.append(
                f"[JavaScript worker error] Communication failed: {exc}"
            )
            self._stop_worker()
            return None

        deadline = time.monotonic() + self.timeout
        result: str | None = None

        while time.monotonic() < deadline:
            if self._parent.poll(0.05):
                try:
                    message = self._parent.recv()
                except (EOFError, OSError):
                    break

                kind, *values = message

                if kind == "log":
                    level, text = values
                    prefix = "" if level == "log" else f"[{level}] "
                    self.console_messages.append(prefix + text)
                elif kind == "result":
                    result = values[0]
                elif kind == "error":
                    self.console_messages.append(f"[JavaScript error] {values[0]}")
                elif kind == "fatal":
                    self.console_messages.append(
                        f"[JavaScript worker error] {values[0]}"
                    )
                    break
                elif kind == "done":
                    return result

            if not self._process.is_alive():
                break

        self._stop_worker()
        self.console_messages.append(
            f"[JavaScript error] Execution exceeded the "
            f"{self.timeout:g}-second timeout or the worker exited. "
            "The worker will restart on the next execution."
        )
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process, parent = self._process, self._parent
        if parent is not None and process is not None and process.is_alive():
            try:
                parent.send(("close", None))
            except (BrokenPipeError, EOFError, OSError):
                pass
            process.join(timeout=0.5)
        self._stop_worker()

    def __enter__(self) -> JavaScriptRuntime:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()