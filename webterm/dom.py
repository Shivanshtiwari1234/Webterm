
"""Lightweight DOM tree and traversal/mutation layer for Webterm."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from bs4 import (
    BeautifulSoup,
    Comment,
    Doctype,
    NavigableString,
    Tag,
)

ELEMENT_NODE = 1
TEXT_NODE = 3
COMMENT_NODE = 8
DOCUMENT_NODE = 9
DOCUMENT_TYPE_NODE = 10


class DOMNode:
    __slots__ = ("_node", "_document")

    def __init__(self, node: Any, document: DOMDocument) -> None:
        self._node = node
        self._document = document

    def __eq__(self, other: object) -> bool:
        return isinstance(other, DOMNode) and self._node is other._node

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

    @node_value.setter
    def node_value(self, value: str | None) -> None:
        if self.node_type not in {TEXT_NODE, COMMENT_NODE}:
            return

        replacement_text = "" if value is None else str(value)

        if self.node_type == COMMENT_NODE:
            replacement = Comment(replacement_text)
        else:
            replacement = NavigableString(replacement_text)

        self._node.replace_with(replacement)
        self._node = replacement

    @property
    def text_content(self) -> str:
        if self.node_type in {TEXT_NODE, COMMENT_NODE}:
            return str(self._node)
        if self.node_type == DOCUMENT_TYPE_NODE:
            return ""
        return self._node.get_text()

    @text_content.setter
    def text_content(self, value: str | None) -> None:
        if self.node_type in {DOCUMENT_NODE, ELEMENT_NODE}:
            self._node.clear()

            if value is not None and str(value):
                self._node.append(NavigableString(str(value)))

        elif self.node_type in {TEXT_NODE, COMMENT_NODE}:
            self.node_value = value

    @property
    def parent_node(self) -> DOMNode | None:
        parent = getattr(self._node, "parent", None)
        return self._document._wrap(parent) if parent is not None else None

    @property
    def child_nodes(self) -> list[DOMNode]:
        if self.node_type not in {DOCUMENT_NODE, ELEMENT_NODE}:
            return []

        return [
            self._document._wrap(child)
            for child in self._node.contents
        ]

    @property
    def children(self) -> list[DOMElement]:
        return [
            child
            for child in self.child_nodes
            if isinstance(child, DOMElement)
        ]

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
        children = self.children
        return children[0] if children else None

    @property
    def last_element_child(self) -> DOMElement | None:
        children = self.children
        return children[-1] if children else None

    @property
    def child_element_count(self) -> int:
        return len(self.children)

    @property
    def previous_sibling(self) -> DOMNode | None:
        node = getattr(self._node, "previous_sibling", None)
        return self._document._wrap(node) if node is not None else None

    @property
    def next_sibling(self) -> DOMNode | None:
        node = getattr(self._node, "next_sibling", None)
        return self._document._wrap(node) if node is not None else None

    @property
    def previous_element_sibling(self) -> DOMElement | None:
        node = getattr(self._node, "previous_sibling", None)

        while node is not None:
            if isinstance(node, Tag):
                return self._document._wrap(node)
            node = node.previous_sibling

        return None

    @property
    def next_element_sibling(self) -> DOMElement | None:
        node = getattr(self._node, "next_sibling", None)

        while node is not None:
            if isinstance(node, Tag):
                return self._document._wrap(node)
            node = node.next_sibling

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

    def _validate_child(self, child: DOMNode) -> None:
        if not isinstance(child, DOMNode):
            raise TypeError("child must be a DOMNode")

        if child._document is not self._document:
            raise ValueError("Cannot insert a node from another document")

        if child._node is self._node:
            raise ValueError("A node cannot contain itself")

        if child.node_type == DOCUMENT_NODE:
            raise TypeError("A document node cannot be inserted as a child")

        # Prevent inserting an ancestor into one of its descendants.
        ancestor = self._node

        while ancestor is not None:
            if ancestor is child._node:
                raise ValueError(
                    "Cannot insert an ancestor into its descendant"
                )
            ancestor = getattr(ancestor, "parent", None)

        if self.node_type not in {DOCUMENT_NODE, ELEMENT_NODE}:
            raise TypeError("This node cannot have children")

    def append_child(self, child: DOMNode) -> DOMNode:
        self._validate_child(child)
        child._node.extract()
        self._node.append(child._node)
        return child

    def insert_before(
        self,
        child: DOMNode,
        reference: DOMNode | None,
    ) -> DOMNode:
        self._validate_child(child)

        if reference is None:
            return self.append_child(child)

        if (
            reference._document is not self._document
            or reference._node.parent is not self._node
        ):
            raise ValueError("Reference node is not a child")

        child._node.extract()
        reference._node.insert_before(child._node)
        return child

    def remove_child(self, child: DOMNode) -> DOMNode:
        if (
            child._document is not self._document
            or child._node.parent is not self._node
        ):
            raise ValueError("Node is not a child")

        child._node.extract()
        return child

    def replace_child(
        self,
        new_child: DOMNode,
        old_child: DOMNode,
    ) -> DOMNode:
        if (
            old_child._document is not self._document
            or old_child._node.parent is not self._node
        ):
            raise ValueError("Old node is not a child")

        self._validate_child(new_child)

        if new_child._node is old_child._node:
            return old_child

        replacement = new_child._node.extract()
        old_child._node.replace_with(replacement)
        return old_child

    def __repr__(self) -> str:
        return f"{type(self).__name__}(node_name={self.node_name!r})"


class DOMElement(DOMNode):
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
            return " ".join(map(str, value))

        return str(value)

    def set_attribute(self, name: str, value: Any) -> None:
        if not name or any(character.isspace() for character in name):
            raise ValueError("Invalid attribute name")

        self._node.attrs[name.lower()] = str(value)

    def remove_attribute(self, name: str) -> None:
        self._node.attrs.pop(name.lower(), None)

    def has_attribute(self, name: str) -> bool:
        return name.lower() in self._node.attrs

    @property
    def id(self) -> str:
        return self.get_attribute("id") or ""

    @id.setter
    def id(self, value: str) -> None:
        self.set_attribute("id", value)

    @property
    def class_name(self) -> str:
        return self.get_attribute("class") or ""

    @class_name.setter
    def class_name(self, value: str) -> None:
        self.set_attribute("class", value)

    @property
    def inner_html(self) -> str:
        return self._node.decode_contents()

    @inner_html.setter
    def inner_html(self, value: str) -> None:
        self._node.clear()
        fragment = BeautifulSoup(str(value), "html.parser")

        for child in list(fragment.contents):
            self._node.append(child.extract())

    @property
    def outer_html(self) -> str:
        return str(self._node)

    @outer_html.setter
    def outer_html(self, value: str) -> None:
        fragment = BeautifulSoup(str(value), "html.parser")
        replacement = fragment.find()

        if replacement is None:
            self._node.decompose()
            return

        self._node.replace_with(replacement.extract())

    def query_selector(self, selector: str) -> DOMElement | None:
        match = self._node.select_one(selector)
        return self._document._wrap(match) if isinstance(match, Tag) else None

    def query_selector_all(self, selector: str) -> list[DOMElement]:
        return [
            self._document._wrap(match)
            for match in self._node.select(selector)
        ]


class DOMDocument(DOMNode):
    __slots__ = ("_soup",)

    def __init__(self, html: str = "") -> None:
        self._soup = BeautifulSoup(html, "html.parser")

        html_element = self._soup.find("html")

        if html_element is None:
            html_element = self._soup.new_tag("html")

            for node in list(self._soup.contents):
                html_element.append(node.extract())

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
            (
                item
                for item in self._soup.contents
                if isinstance(item, Doctype)
            ),
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
        match = self._soup.select_one(selector)
        return self._wrap(match) if isinstance(match, Tag) else None

    def query_selector_all(self, selector: str) -> list[DOMElement]:
        return [
            self._wrap(match)
            for match in self._soup.select(selector)
        ]

    def create_element(self, tag_name: str) -> DOMElement:
        if not tag_name or any(character.isspace() for character in tag_name):
            raise ValueError("tag_name must be a non-empty tag name")

        return self._wrap(self._soup.new_tag(tag_name.lower()))

    def create_text_node(self, text: str) -> DOMNode:
        return self._wrap(NavigableString(str(text)))

    def create_comment(self, text: str) -> DOMNode:
        return self._wrap(Comment(str(text)))

    def serialize(self) -> str:
        return str(self._soup)

    def __repr__(self) -> str:
        return "DOMDocument()"
