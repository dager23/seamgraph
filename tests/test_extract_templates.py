"""Tests for template extractor."""
from __future__ import annotations

from seamgraph.extract.templates import extract_template_file, extract_template_refs
from seamgraph.models import AnchorKind


class TestTemplateFile:
    def test_template_in_templates_dir(self) -> None:
        anchors = extract_template_file("templates/shop/order.html")
        assert len(anchors) == 1
        assert anchors[0].kind is AnchorKind.TEMPLATE_FILE
        assert anchors[0].key == "shop/order.html"

    def test_jinja_file(self) -> None:
        anchors = extract_template_file("templates/base.jinja2")
        assert len(anchors) == 1

    def test_non_template_python_file(self) -> None:
        anchors = extract_template_file("app/views.py")
        assert len(anchors) == 0

    def test_html_outside_templates_dir(self) -> None:
        # HTML not in templates/ dir should not be picked up
        anchors = extract_template_file("docs/guide.html")
        assert len(anchors) == 0


class TestTemplateRefs:
    def test_url_tag(self) -> None:
        text = """<a href="{% url 'order-detail' pk %}">View</a>"""
        anchors = extract_template_refs("templates/shop/list.html", text)
        url_refs = [a for a in anchors if a.kind is AnchorKind.URLNAME_REF]
        assert len(url_refs) == 1
        assert url_refs[0].key == "order-detail"

    def test_namespaced_url_tag(self) -> None:
        text = """{% url 'shop:order-detail' pk %}"""
        anchors = extract_template_refs("templates/base.html", text)
        url_refs = [a for a in anchors if a.kind is AnchorKind.URLNAME_REF]
        assert len(url_refs) == 1
        assert url_refs[0].key == "order-detail"

    def test_include_tag(self) -> None:
        text = """{% include "partials/header.html" %}"""
        anchors = extract_template_refs("templates/base.html", text)
        refs = [a for a in anchors if a.kind is AnchorKind.TEMPLATE_REF]
        assert len(refs) == 1
        assert refs[0].key == "partials/header.html"

    def test_extends_tag(self) -> None:
        text = """{% extends "base.html" %}"""
        anchors = extract_template_refs("templates/shop/detail.html", text)
        refs = [a for a in anchors if a.kind is AnchorKind.TEMPLATE_REF]
        assert len(refs) == 1
        assert refs[0].key == "base.html"

    def test_multiple_tags(self) -> None:
        text = """\
{% extends "base.html" %}
{% block content %}
<a href="{% url 'order-list' %}">Orders</a>
{% include "partials/footer.html" %}
{% endblock %}
"""
        anchors = extract_template_refs("templates/shop/page.html", text)
        assert len(anchors) == 3  # extends, url, include
