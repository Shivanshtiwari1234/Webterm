from __future__ import annotations

import json
import multiprocessing as mp
import time
from multiprocessing.connection import Connection


def _javascript_worker(
    conn: Connection,
    memory_limit_mb: int,
) -> None:
    """Run a persistent QuickJS context and DOM inside an isolated process."""
    try:
        import quickjs

        from .dom import DOMDocument, DOMElement, DOMNode

        context = quickjs.Context()
        context.set_memory_limit(memory_limit_mb * 1024 * 1024)

        document: DOMDocument | None = None
        nodes: dict[int, DOMNode] = {}
        node_ids: dict[int, int] = {}
        next_node_id = 1

        def send(message: tuple) -> None:
            try:
                conn.send(message)
            except (BrokenPipeError, EOFError, OSError):
                pass

        def log(level: str, message: str) -> None:
            send(("log", level, message))

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

        def get_node(node_id: int | None) -> DOMNode | None:
            if node_id is None:
                return None
            return nodes.get(int(node_id))

        def dom_call(operation: str, args_json: str) -> str:
            try:
                args = json.loads(args_json)
                node_id = args.get("node")
                node = get_node(node_id)

                if operation == "document":
                    return json.dumps({
                        "node": register(document),
                        "title": document.title if document else "",
                        "documentElement": (
                            register(document.document_element)
                            if document else None
                        ),
                    })

                if operation == "createElement":
                    if document is None:
                        return json.dumps(None)

                    return json.dumps(
                        register(document.create_element(args["tag"]))
                    )

                if operation == "createTextNode":
                    if document is None:
                        return json.dumps(None)

                    return json.dumps(
                        register(document.create_text_node(args["text"]))
                    )

                if operation == "appendChild":
                    if not isinstance(node, DOMNode):
                        raise TypeError("appendChild receiver is invalid")

                    child = get_node(args["child"])

                    if child is None:
                        raise TypeError("appendChild child is invalid")

                    node.append_child(child)
                    return json.dumps(register(child))

                if operation == "removeChild":
                    if not isinstance(node, DOMNode):
                        raise TypeError("removeChild receiver is invalid")

                    child = get_node(args["child"])

                    if child is None:
                        raise TypeError("removeChild child is invalid")

                    node.remove_child(child)
                    return json.dumps(register(child))

                if operation == "insertBefore":
                    if not isinstance(node, DOMNode):
                        raise TypeError("insertBefore receiver is invalid")

                    child = get_node(args["child"])
                    reference = get_node(args.get("reference"))

                    if child is None:
                        raise TypeError("insertBefore child is invalid")

                    node.insert_before(child, reference)
                    return json.dumps(register(child))

                if operation == "setProperty":
                    if node is None:
                        raise TypeError("Cannot set a property on null")

                    name = args["name"]
                    value = args.get("value")

                    if name == "textContent":
                        node.text_content = (
                            "" if value is None else str(value)
                        )

                    elif name == "nodeValue":
                        node.node_value = (
                            None if value is None else str(value)
                        )

                    elif isinstance(node, DOMElement):
                        if name == "id":
                            node.id = "" if value is None else str(value)
                        elif name == "className":
                            node.class_name = (
                                "" if value is None else str(value)
                            )
                        elif name == "innerHTML":
                            node.inner_html = (
                                "" if value is None else str(value)
                            )
                        elif name == "outerHTML":
                            node.outer_html = (
                                "" if value is None else str(value)
                            )
                        else:
                            raise AttributeError(
                                f"Unsupported DOM property: {name}"
                            )
                    else:
                        raise AttributeError(
                            f"Unsupported DOM property: {name}"
                        )

                    return json.dumps(True)

                if operation == "getElementById":
                    result = (
                        document.get_element_by_id(args["id"])
                        if document else None
                    )
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
                        results = node.query_selector_all(selector)
                    elif document:
                        first = document.query_selector(selector)
                        results = document.query_selector_all(selector)
                    else:
                        first, results = None, []

                    if operation == "querySelector":
                        return json.dumps(register(first))

                    return json.dumps([register(item) for item in results])

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
                        "childNodes": [
                            register(child) for child in node.child_nodes
                        ],
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
                            "children": [
                                register(child) for child in node.children
                            ],
                            "firstElementChild": register(
                                node.first_element_child
                            ),
                            "lastElementChild": register(
                                node.last_element_child
                            ),
                            "childElementCount": node.child_element_count,
                        })

                    return json.dumps(properties.get(name))

                if operation == "getAttribute":
                    return json.dumps(
                        node.get_attribute(args["name"])
                        if isinstance(node, DOMElement) else None
                    )

                if operation == "setAttribute":
                    if not isinstance(node, DOMElement):
                        raise TypeError("setAttribute requires an element")

                    node.set_attribute(
                        args["name"],
                        args.get("value", ""),
                    )
                    return json.dumps(True)

                if operation == "removeAttribute":
                    if not isinstance(node, DOMElement):
                        raise TypeError("removeAttribute requires an element")

                    node.remove_attribute(args["name"])
                    return json.dumps(True)

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
        context.add_callable(
            "__webterm_log",
            lambda message: log("log", message),
        )
        context.add_callable(
            "__webterm_warn",
            lambda message: log("warn", message),
        )
        context.add_callable(
            "__webterm_error",
            lambda message: log("error", message),
        )

        context.eval(r"""
            globalThis.console = {
                log: (...args) =>
                    __webterm_log(args.map(String).join(" ")),
                info: (...args) =>
                    __webterm_log(args.map(String).join(" ")),
                warn: (...args) =>
                    __webterm_warn(args.map(String).join(" ")),
                error: (...args) =>
                    __webterm_error(args.map(String).join(" "))
            };

            const __domCall = (operation, args = {}) => {
                const result = JSON.parse(
                    __webterm_dom_call(operation, JSON.stringify(args))
                );

                if (
                    result &&
                    typeof result === "object" &&
                    "error" in result
                ) {
                    throw new Error(result.error);
                }

                return result;
            };

            const __nodeCache = new Map();
            const __listeners = new Map();

            let __eventStopped = false;
            let __immediateStopped = false;

            function __listenerKey(id, type) {
                return `${id}:${type}`;
            }

            function __getListeners(id, type) {
                const key = __listenerKey(id, type);

                if (!__listeners.has(key)) {
                    __listeners.set(key, []);
                }

                return __listeners.get(key);
            }

            function __makeEvent(type, target, options = {}) {
                __eventStopped = false;
                __immediateStopped = false;

                return {
                    type: String(type),
                    target,
                    currentTarget: null,
                    bubbles: options.bubbles !== false,
                    cancelable: options.cancelable !== false,
                    defaultPrevented: false,
                    eventPhase: 0,

                    preventDefault() {
                        if (this.cancelable) {
                            this.defaultPrevented = true;
                        }
                    },

                    stopPropagation() {
                        __eventStopped = true;
                    },

                    stopImmediatePropagation() {
                        __eventStopped = true;
                        __immediateStopped = true;
                    },

                    composedPath() {
                        const path = [];
                        let current = this.target;

                        while (current) {
                            path.push(current);
                            current = current.parentNode;
                        }

                        return path;
                    }
                };
            }

            function __invokeListeners(node, event, capture) {
                const id = node.__id;
                const listeners = [...__getListeners(id, event.type)];

                event.currentTarget = node;
                __immediateStopped = false;

                for (const entry of listeners) {
                    if (entry.capture !== capture) continue;

                    if (entry.once) {
                        node.removeEventListener(
                            event.type,
                            entry.callback,
                            { capture: entry.capture }
                        );
                    }

                    try {
                        if (typeof entry.callback === "function") {
                            entry.callback.call(node, event);
                        } else if (
                            entry.callback &&
                            typeof entry.callback.handleEvent === "function"
                        ) {
                            entry.callback.handleEvent(event);
                        }
                    } catch (error) {
                        console.error(error);
                    }

                    if (__immediateStopped) break;
                }
            }

            function __dispatchEvent(target, event) {
                if (!target || target.__id === undefined) {
                    throw new TypeError("Invalid event target");
                }

                __eventStopped = false;
                __immediateStopped = false;

                const path = [];
                let current = target;

                while (current) {
                    path.push(current);
                    current = current.parentNode;
                }

                event.target = target;

                // Capture phase: ancestors only.
                for (let index = path.length - 1; index >= 1; index--) {
                    event.eventPhase = 1;
                    __invokeListeners(path[index], event, true);

                    if (__eventStopped) {
                        event.eventPhase = 0;
                        event.currentTarget = null;
                        return !event.defaultPrevented;
                    }
                }

                // Target phase.
                event.eventPhase = 2;
                __invokeListeners(target, event, true);

                if (!__immediateStopped) {
                    __invokeListeners(target, event, false);
                }

                if (__eventStopped) {
                    event.eventPhase = 0;
                    event.currentTarget = null;
                    return !event.defaultPrevented;
                }

                // Bubble phase.
                if (event.bubbles) {
                    event.eventPhase = 3;

                    for (let index = 1; index < path.length; index++) {
                        __invokeListeners(path[index], event, false);

                        if (__eventStopped) break;
                    }
                }

                event.eventPhase = 0;
                event.currentTarget = null;

                return !event.defaultPrevented;
            }

            function __wrapNode(id) {
                if (id === null || id === undefined) return null;
                if (__nodeCache.has(id)) return __nodeCache.get(id);

                const node = {};
                Object.defineProperty(node, "__id", { value: id });

                const property = name =>
                    __domCall("property", { node: id, name });

                for (const name of [
                    "nodeType", "nodeName", "nodeValue", "textContent",
                    "tagName", "id", "className", "innerHTML", "outerHTML",
                    "childElementCount"
                ]) {
                    Object.defineProperty(node, name, {
                        get: () => property(name),
                        set: value => __domCall(
                            "setProperty",
                            { node: id, name, value }
                        ),
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

                node.appendChild = child => {
                    if (!child || child.__id === undefined) {
                        throw new TypeError("appendChild expects a DOM node");
                    }

                    return __wrapNode(__domCall("appendChild", {
                        node: id,
                        child: child.__id
                    }));
                };

                node.removeChild = child => {
                    if (!child || child.__id === undefined) {
                        throw new TypeError("removeChild expects a DOM node");
                    }

                    return __wrapNode(__domCall("removeChild", {
                        node: id,
                        child: child.__id
                    }));
                };

                node.insertBefore = (child, reference) => {
                    if (!child || child.__id === undefined) {
                        throw new TypeError("insertBefore expects a DOM node");
                    }

                    return __wrapNode(__domCall("insertBefore", {
                        node: id,
                        child: child.__id,
                        reference: reference ? reference.__id : null
                    }));
                };

                node.getAttribute = name =>
                    __domCall("getAttribute", {
                        node: id,
                        name: String(name)
                    });

                node.setAttribute = (name, value) =>
                    __domCall("setAttribute", {
                        node: id,
                        name: String(name),
                        value: String(value)
                    });

                node.removeAttribute = name =>
                    __domCall("removeAttribute", {
                        node: id,
                        name: String(name)
                    });

                node.hasAttribute = name =>
                    __domCall("hasAttribute", {
                        node: id,
                        name: String(name)
                    });

                node.querySelector = selector =>
                    __wrapNode(__domCall("elementQuerySelector", {
                        node: id,
                        selector: String(selector)
                    }));

                node.querySelectorAll = selector =>
                    __domCall("elementQuerySelectorAll", {
                        node: id,
                        selector: String(selector)
                    }).map(__wrapNode);

                node.addEventListener = (type, callback, options = {}) => {
                    if (
                        typeof callback !== "function" &&
                        !(callback && typeof callback.handleEvent === "function")
                    ) {
                        return;
                    }

                    const normalized = typeof options === "boolean"
                        ? { capture: options }
                        : options || {};

                    const listeners = __getListeners(id, String(type));

                    if (listeners.some(entry =>
                        entry.callback === callback &&
                        entry.capture === Boolean(normalized.capture)
                    )) {
                        return;
                    }

                    listeners.push({
                        callback,
                        capture: Boolean(normalized.capture),
                        once: Boolean(normalized.once),
                        passive: Boolean(normalized.passive)
                    });
                };

                node.removeEventListener = (type, callback, options = {}) => {
                    const normalized = typeof options === "boolean"
                        ? { capture: options }
                        : options || {};

                    const listeners = __getListeners(id, String(type));

                    const index = listeners.findIndex(entry =>
                        entry.callback === callback &&
                        entry.capture === Boolean(normalized.capture)
                    );

                    if (index !== -1) listeners.splice(index, 1);
                };

                node.dispatchEvent = event => {
                    if (!event || !event.type) {
                        throw new TypeError("dispatchEvent expects an event");
                    }

                    return __dispatchEvent(node, event);
                };

                __nodeCache.set(id, node);
                return node;
            }

            class Event {
                constructor(type, options = {}) {
                    this.type = String(type);
                    this.bubbles = options.bubbles !== false;
                    this.cancelable = options.cancelable !== false;
                    this.defaultPrevented = false;
                    this.target = null;
                    this.currentTarget = null;
                    this.eventPhase = 0;
                }

                preventDefault() {
                    if (this.cancelable) this.defaultPrevented = true;
                }

                stopPropagation() {
                    __eventStopped = true;
                }

                stopImmediatePropagation() {
                    __eventStopped = true;
                    __immediateStopped = true;
                }
            }

            globalThis.Event = Event;

            globalThis.document = {
                get title() {
                    return __domCall("document").title;
                },

                get documentElement() {
                    return __wrapNode(
                        __domCall("document").documentElement
                    );
                },

                createElement: tag =>
                    __wrapNode(__domCall("createElement", {
                        tag: String(tag)
                    })),

                createTextNode: text =>
                    __wrapNode(__domCall("createTextNode", {
                        text: String(text)
                    })),

                getElementById: id =>
                    __wrapNode(__domCall("getElementById", {
                        id: String(id)
                    })),

                getElementsByTagName: tag =>
                    __domCall("getElementsByTagName", {
                        tag: String(tag)
                    }).map(__wrapNode),

                querySelector: selector =>
                    __wrapNode(__domCall("querySelector", {
                        selector: String(selector)
                    })),

                querySelectorAll: selector =>
                    __domCall("querySelectorAll", {
                        selector: String(selector)
                    }).map(__wrapNode),

                addEventListener(type, callback, options) {
                    const root = __wrapNode(
                        __domCall("document").node
                    );
                    root.addEventListener(type, callback, options);
                },

                removeEventListener(type, callback, options) {
                    const root = __wrapNode(
                        __domCall("document").node
                    );
                    root.removeEventListener(type, callback, options);
                }
            };

            globalThis.__webterm_dispatch = (selector, type) => {
                const target = document.querySelector(selector);

                if (!target) return false;

                const event = __makeEvent(type, target, {
                    bubbles: true,
                    cancelable: true
                });

                return __dispatchEvent(target, event);
            };
        """)

        send(("ready", None))

        while True:
            try:
                message = conn.recv()
            except (EOFError, OSError):
                break

            command = message[0]

            if command == "close":
                break

            if command == "reset":
                document = DOMDocument(message[1])
                nodes.clear()
                node_ids.clear()
                next_node_id = 1

                context.eval("""
                    __nodeCache.clear();
                    __listeners.clear();
                """)

                send(("document_html", document.serialize()))
                send(("done", None))
                continue

            if command == "execute":
                source = message[1]
                html = message[2] if len(message) > 2 else None

                if html is not None:
                    document = DOMDocument(html)
                    nodes.clear()
                    node_ids.clear()
                    next_node_id = 1

                    context.eval("""
                        __nodeCache.clear();
                        __listeners.clear();
                    """)

                try:
                    result = context.eval(source)
                    result = None if result is None else str(result)
                    send(("result", result))
                except Exception as exc:
                    send(("error", str(exc)))

                if document is not None:
                    try:
                        send(("document_html", document.serialize()))
                    except Exception as exc:
                        send(("error", f"Could not serialize DOM: {exc}"))

                send(("done", None))
                continue

            if command == "dispatch":
                selector, event_type = message[1], message[2]

                try:
                    result = context.eval(
                        "__webterm_dispatch("
                        + json.dumps(selector)
                        + ", "
                        + json.dumps(event_type)
                        + ")"
                    )

                    send(("dispatch_result", bool(result)))

                    if document is not None:
                        send(("document_html", document.serialize()))
                except Exception as exc:
                    send(("error", str(exc)))

                send(("done", None))

    except BaseException as exc:
        try:
            conn.send(("fatal", str(exc)))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        conn.close()


class JavaScriptRuntime:
    """Persistent JavaScript runtime dedicated to one browser tab."""

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
        self.document_html: str | None = None
        self.last_dispatch_result: bool | None = None

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

    def _send_command(self, message: tuple) -> bool:
        if not self._ensure_worker():
            return False

        assert self._parent is not None

        try:
            self._parent.send(message)
            return True
        except (BrokenPipeError, EOFError, OSError) as exc:
            self.console_messages.append(
                f"[JavaScript worker error] Communication failed: {exc}"
            )
            self._stop_worker()
            return False

    def _receive_until_done(self) -> str | None:
        assert self._parent is not None
        assert self._process is not None

        deadline = time.monotonic() + self.timeout
        result: str | None = None

        self.document_html = None
        self.last_dispatch_result = None

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

                elif kind == "dispatch_result":
                    self.last_dispatch_result = values[0]

                elif kind == "document_html":
                    self.document_html = values[0]

                elif kind == "error":
                    self.console_messages.append(
                        f"[JavaScript error] {values[0]}"
                    )

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

    def execute(
        self,
        source: str,
        document_html: str | None = None,
    ) -> str | None:
        """Execute JavaScript, optionally loading a new document first."""
        if self._closed:
            raise RuntimeError("JavaScript runtime is closed")

        if not isinstance(source, str):
            raise TypeError("source must be a string")

        if document_html is not None and not isinstance(document_html, str):
            raise TypeError("document_html must be a string")

        if not self._send_command(("execute", source, document_html)):
            return None

        return self._receive_until_done()

    def reset_document(self, html: str) -> bool:
        """Replace the current DOM and clear listeners for a new page."""
        if not isinstance(html, str):
            raise TypeError("html must be a string")

        if not self._send_command(("reset", html)):
            return False

        self._receive_until_done()
        return self.document_html is not None

    def dispatch_event(
        self,
        selector: str,
        event_type: str = "click",
    ) -> bool:
        """Dispatch a bubbling event to the first element matching selector."""
        if not isinstance(selector, str) or not selector:
            raise ValueError("selector must be a non-empty string")

        if not isinstance(event_type, str) or not event_type:
            raise ValueError("event_type must be a non-empty string")

        if not self._send_command(("dispatch", selector, event_type)):
            return False

        self._receive_until_done()
        return bool(self.last_dispatch_result)

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True

        process = self._process
        parent = self._parent

        if parent is not None and process is not None and process.is_alive():
            try:
                parent.send(("close",))
            except (BrokenPipeError, EOFError, OSError):
                pass

            process.join(timeout=0.5)

        self._stop_worker()

    def __enter__(self) -> JavaScriptRuntime:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()