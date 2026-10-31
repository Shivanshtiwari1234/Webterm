
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
    """Wrapper around a BeautifulSoup node with DOM-style properties."""

    __slots__ = ("_node", "_document")

    def __init__(self, node: Any, document: DOMDocument) -> None:
        self._node = node
        self._document = document
    
    def __eq__(self, other):
        if not isinstance(other, DOMNode):
            return NotImplemented
        return self._node is other._node

    def __hash__(self):
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
        node_type = self.node_type
        if node_type == DOCUMENT_NODE:
            return "#document"
        if node_type == TEXT_NODE:
            return "#text"
        if node_type == COMMENT_NODE:
            return "#comment"
        if node_type == DOCUMENT_TYPE_NODE:
            return "html"
        return str(self._node.name).upper()

    @property
    def tag_name(self) -> str | None:
        return self.node_name if self.node_type == ELEMENT_NODE else None

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
    def children(self) -> list[DOMNode]:
        return [child for child in self.child_nodes if child.is_element]

    @property
    def first_child(self) -> DOMNode | None:
        return self.child_nodes[0] if self.child_nodes else None

    @property
    def last_child(self) -> DOMNode | None:
        return self.child_nodes[-1] if self.child_nodes else None

    @property
    def first_element_child(self) -> DOMNode | None:
        return self.children[0] if self.children else None

    @property
    def last_element_child(self) -> DOMNode | None:
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
    def previous_element_sibling(self) -> DOMNode | None:
        sibling = getattr(self._node, "previous_sibling", None)
        while sibling is not None:
            if isinstance(sibling, Tag):
                return self._document._wrap(sibling)
            sibling = sibling.previous_sibling
        return None

    @property
    def next_element_sibling(self) -> DOMNode | None:
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

    def iter_elements(self) -> Iterator[DOMNode]:
        for node in self.iter_nodes(include_self=False):
            if node.is_element:
                yield node

    def iter_nodes(self, *, include_self: bool = True) -> Iterator[DOMNode]:
        if include_self:
            yield self
        for child in self.child_nodes:
            yield from child.iter_nodes()

    def __repr__(self) -> str:
        return f"DOMNode(node_name={self.node_name!r}, node_type={self.node_type})"


class DOMDocument(DOMNode):
    """Parsed document with a predictable lightweight HTML tree."""

    __slots__ = ("_soup",)

    def __init__(self, html: str = "") -> None:
        self._soup = BeautifulSoup(html, "html.parser")

        # Preserve existing <html> documents. For fragments, place the
        # fragment nodes directly under a synthetic <html> element.
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
        return DOMNode(node, self)

    @property
    def document_element(self) -> DOMNode | None:
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

    def serialize(self) -> str:
        return str(self._soup)

    def __repr__(self) -> str:
        return "DOMDocument()"
