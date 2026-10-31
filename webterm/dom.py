
"""Lightweight DOM tree and traversal layer for Webterm."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from bs4 import BeautifulSoup, Comment, Doctype, NavigableString, Tag


ELEMENT_NODE = 1
TEXT_NODE = 3
COMMENT_NODE = 8
DOCUMENT_NODE = 9
DOCUMENT_TYPE_NODE = 10


class DOMNode:
    """Base wrapper around a BeautifulSoup node."""

    __slots__ = ("_node", "_document")

    def __init__(self, node: Any, document: DOMDocument) -> None:
        self._node = node
        self._document = document

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DOMNode):
            return NotImplemented
        return self._node is other._node

    def __hash__(self) -> int:
        return hash(id(self._node))

    @property
    def node_type(self) -> int:
        if isinstance(self._node, BeautifulSoup):
            return DOCUMENT_NODE
        if isinstance(self._node, Doctype):
            return DOCUMENT_TYPE_NODE
        if isinstance(self._node, Comment):
            return COMMENT_NODE
        if isinstance(self._node, Tag):
            return ELEMENT_NODE
        if isinstance(self._node, NavigableString):
            return TEXT_NODE
        raise TypeError(f"Unsupported DOM node: {type(self._node).__name__}")

    @property
    def node_name(self) -> str:
        if self.node_type == DOCUMENT_NODE:
            return "#document"
        if self.node_type == TEXT_NODE:
            return "#text"
        if self.node_type == COMMENT_NODE:
            return "#comment"
        if self.node_type == DOCUMENT_TYPE_NODE:
            return "html"
        return str(self._node.name).upper()

    @property
    def node_value(self) -> str | None:
        if self.node_type in {TEXT_NODE, COMMENT_NODE}:
            return str(self._node)
        return None

    @property
    def text_content(self) -> str:
        if self.node_type in {TEXT_NODE, COMMENT_NODE}:
            return str(self._node)
        if self.node_type == DOCUMENT_TYPE_NODE:
            return ""
        return self._node.get_text()

    @property
    def parent_node(self) -> DOMNode | None:
        parent = getattr(self._node, "parent", None)
        return self._document._wrap(parent) if parent is not None else None

    @property
    def child_nodes(self) -> list[DOMNode]:
        if self.node_type not in {DOCUMENT_NODE, ELEMENT_NODE}:
            return []
        return [self._document._wrap(child) for child in self._node.contents]

    @property
    def children(self) -> list[DOMElement]:
        return [child for child in self.child_nodes if isinstance(child, DOMElement)]

    @property
    def first_child(self) -> DOMNode | None:
        children = self.child_nodes
        return children[0] if children else None

    @property
    def last_child(self) -> DOMNode | None:
        children = self.child_nodes
        return children[-1] if children else None

    @property
    def first_element_child(self) -> DOMElement | None:
        return self.children[0] if self.children else None

    @property
    def last_element_child(self) -> DOMElement | None:
        return self.children[-1] if self.children else None

    @property
    def child_element_count(self) -> int:
        return len(self.children)

    @property
    def previous_sibling(self) -> DOMNode | None:
        sibling = getattr(self._node, "previous_sibling", None)
        return self._document._wrap(sibling) if sibling is not None else None

    @property
    def next_sibling(self) -> DOMNode | None:
        sibling = getattr(self._node, "next_sibling", None)
        return self._document._wrap(sibling) if sibling is not None else None

    @property
    def previous_element_sibling(self) -> DOMElement | None:
        sibling = getattr(self._node, "previous_sibling", None)
        while sibling is not None:
            if isinstance(sibling, Tag):
                return self._document._wrap(sibling)
            sibling = sibling.previous_sibling
        return None

    @property
    def next_element_sibling(self) -> DOMElement | None:
        sibling = getattr(self._node, "next_sibling", None)
        while sibling is not None:
            if isinstance(sibling, Tag):
                return self._document._wrap(sibling)
            sibling = sibling.next_sibling
        return None

    @property
    def is_element(self) -> bool:
        return self.node_type == ELEMENT_NODE

    @property
    def is_text(self) -> bool:
        return self.node_type == TEXT_NODE

    def iter_children(self) -> Iterator[DOMNode]:
        yield from self.child_nodes

    def iter_elements(self) -> Iterator[DOMElement]:
        for node in self.iter_nodes(include_self=False):
            if isinstance(node, DOMElement):
                yield node

    def iter_nodes(self, *, include_self: bool = True) -> Iterator[DOMNode]:
        if include_self:
            yield self
        for child in self.child_nodes:
            yield from child.iter_nodes()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(node_name={self.node_name!r})"


class DOMElement(DOMNode):
    """DOM-style interface for HTML elements."""

    __slots__ = ()

    @property
    def tag_name(self) -> str:
        return str(self._node.name).upper()

    @property
    def attributes(self) -> dict[str, Any]:
        return dict(self._node.attrs)

    def get_attribute(self, name: str) -> str | None:
        value = self._node.attrs.get(name.lower())
        if value is None:
            return None
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        return str(value)

    def has_attribute(self, name: str) -> bool:
        return name.lower() in self._node.attrs

    @property
    def id(self) -> str:
        return self.get_attribute("id") or ""

    @property
    def class_name(self) -> str:
        return self.get_attribute("class") or ""

    @property
    def inner_html(self) -> str:
        return self._node.decode_contents()

    @property
    def outer_html(self) -> str:
        return str(self._node)

    def query_selector(self, selector: str) -> DOMElement | None:
        """Return the first descendant matching a CSS selector."""
        match = self._node.select_one(selector)
        return self._document._wrap(match) if isinstance(match, Tag) else None

    def query_selector_all(self, selector: str) -> list[DOMElement]:
        """Return all descendants matching a CSS selector."""
        return [
            self._document._wrap(match)
            for match in self._node.select(selector)
        ]


class DOMDocument(DOMNode):
    """Parsed document with Document-style lookup and selector interfaces."""

    __slots__ = ("_soup",)

    def __init__(self, html: str = "") -> None:
        self._soup = BeautifulSoup(html, "html.parser")

        html_element = self._soup.find("html")
        if html_element is None:
            html_element = self._soup.new_tag("html")
            original_contents = list(self._soup.contents)
            for node in original_contents:
                node.extract()
                html_element.append(node)
            self._soup.append(html_element)

        super().__init__(self._soup, self)

    def _wrap(self, node: Any) -> DOMNode:
        if node is self._soup:
            return self
        if isinstance(node, Tag):
            return DOMElement(node, self)
        return DOMNode(node, self)

    @property
    def document_element(self) -> DOMElement | None:
        element = self._soup.find("html")
        return self._wrap(element) if element is not None else None

    @property
    def doctype(self) -> DOMNode | None:
        node = next(
            (item for item in self._soup.contents if isinstance(item, Doctype)),
            None,
        )
        return self._wrap(node) if node is not None else None

    @property
    def title(self) -> str:
        title = self._soup.find("title")
        return title.get_text(strip=True) if title else ""

    def get_element_by_id(self, element_id: str) -> DOMElement | None:
        element = self._soup.find(id=element_id)
        return self._wrap(element) if isinstance(element, Tag) else None

    def get_elements_by_tag_name(self, tag_name: str) -> list[DOMElement]:
        return [
            self._wrap(element)
            for element in self._soup.find_all(tag_name)
        ]

    def query_selector(self, selector: str) -> DOMElement | None:
        """Return the first element matching a CSS selector."""
        match = self._soup.select_one(selector)
        return self._wrap(match) if isinstance(match, Tag) else None

    def query_selector_all(self, selector: str) -> list[DOMElement]:
        """Return all elements matching a CSS selector."""
        return [
            self._wrap(match)
            for match in self._soup.select(selector)
        ]

    def create_element(self, tag_name: str) -> DOMElement:
        if not tag_name or any(char.isspace() for char in tag_name):
            raise ValueError("tag_name must be a non-empty tag name")
        return self._wrap(self._soup.new_tag(tag_name.lower()))

    def serialize(self) -> str:
        return str(self._soup)

    def __repr__(self) -> str:
        return "DOMDocument()"
