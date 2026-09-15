# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for cmdb.models.docapi_model.template_engine.TemplateEngine

Pure tests (no app context, no database). Covers variable substitution, HTML autoescaping of
field values, the blank rendering of None / empty / SafeNull / SafeObject via _finalize, the
object/root/report globals with their SafeObject fallbacks, and the raw-template error fallback.
"""
from markupsafe import Markup

from cmdb.models.docapi_model.template_engine import TemplateEngine, NBSP
from cmdb.models.docapi_model.safe_null import SafeNull
from cmdb.models.docapi_model.safe_object import SafeObject
# -------------------------------------------------------------------------------------------------------------------- #

# Keys the render globals recognise in the template data
OBJECTS_KEY: str = 'objects'
ROOT_KEY: str = 'root'
LABEL: str = 'label'


def _render(template: str, data: dict) -> str:
    """Renders `template` with `data` through the engine (thin wrapper for readability)."""
    return TemplateEngine.render_template_string(template, data)


# -------------------------------------------------------------------------------------------------------------------- #
#                                              render_template_string                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRenderSubstitution:
    """Basic substitution and HTML autoescaping."""

    def test_basic_substitution(self) -> None:
        """A variable is substituted into the template."""
        assert _render('Hi {{ name }}', {'name': 'Bob'}) == 'Hi Bob'

    def test_field_value_is_html_escaped(self) -> None:
        """A field value containing HTML is escaped (autoescape on)."""
        assert _render('{{ v }}', {'v': '<b>x</b>'}) == '&lt;b&gt;x&lt;/b&gt;'

    def test_template_markup_not_escaped(self) -> None:
        """The template's own HTML markup is rendered as-is; only values are escaped."""
        assert _render('<b>{{ v }}</b>', {'v': 'y'}) == '<b>y</b>'

    def test_markup_value_rendered_raw(self) -> None:
        """A Markup value (trusted HTML, e.g. a report table or PDF marker) is emitted verbatim."""
        assert _render('{{ v }}', {'v': Markup('<pdf:nextpage />')}) == '<pdf:nextpage />'


class TestRenderBlanks:
    """None / empty / missing / SafeNull / SafeObject render as a non-breaking space."""

    def test_none_renders_nbsp(self) -> None:
        """A None value renders as a non-breaking space."""
        assert _render('[{{ a }}]', {'a': None}) == f'[{NBSP}]'

    def test_empty_string_renders_nbsp(self) -> None:
        """An empty-string value renders as a non-breaking space."""
        assert _render('[{{ a }}]', {'a': ''}) == f'[{NBSP}]'

    def test_missing_top_level_var_renders_empty(self) -> None:
        """An undefined top-level variable chains to empty (ChainableUndefined), not NBSP."""
        assert _render('[{{ missing }}]', {}) == '[]'

    def test_missing_nested_attr_renders_nbsp(self) -> None:
        """A missing attribute on wrapped data resolves to a SafeNull -> NBSP."""
        assert _render('[{{ section.absent }}]', {'section': {'present': 1}}) == f'[{NBSP}]'


class TestRenderGlobals:
    """object(id) / root / report(id) resolve data or fall back to a blank SafeObject."""

    def test_object_present(self) -> None:
        """object(id) resolves a present object's field."""
        data = {OBJECTS_KEY: {1: {LABEL: 'srv'}}}

        assert _render('{{ object(1).' + LABEL + ' }}', data) == 'srv'

    def test_object_missing_renders_nbsp(self) -> None:
        """object(id) for an unknown id falls back to a SafeObject -> NBSP."""
        assert _render('[{{ object(999) }}]', {}) == f'[{NBSP}]'

    def test_object_missing_field_renders_nbsp(self) -> None:
        """A field on a missing object resolves through SafeObject -> SafeNull -> NBSP."""
        assert _render('[{{ object(999).field }}]', {}) == f'[{NBSP}]'

    def test_root_present(self) -> None:
        """root resolves a present value."""
        assert _render('{{ root.x }}', {ROOT_KEY: {'x': 'R'}}) == 'R'

    def test_root_missing_renders_nbsp(self) -> None:
        """root falls back to a SafeObject when absent -> NBSP."""
        assert _render('[{{ root }}]', {}) == f'[{NBSP}]'

    def test_report_missing_renders_nbsp(self) -> None:
        """report(id) for an unknown id falls back to a SafeObject -> NBSP."""
        assert _render('[{{ report(5) }}]', {}) == f'[{NBSP}]'


class TestRenderErrorFallback:
    """A fatal render error returns the raw template so the document is not empty."""

    def test_render_error_returns_raw_template(self) -> None:
        """A template that raises at render time yields the raw template string back."""
        raw = '{{ 1 / 0 }}'

        assert _render(raw, {}) == raw


# -------------------------------------------------------------------------------------------------------------------- #
#                                            TemplateEngine._finalize                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFinalize:
    """The finalize hook blanks None / empty / SafeNull / SafeObject and passes others through."""

    def test_none_to_nbsp(self) -> None:
        """None finalizes to a non-breaking space."""
        assert TemplateEngine._finalize(None) == NBSP

    def test_empty_string_to_nbsp(self) -> None:
        """An empty string finalizes to a non-breaking space."""
        assert TemplateEngine._finalize('') == NBSP

    def test_safenull_to_nbsp(self) -> None:
        """A SafeNull finalizes to a non-breaking space."""
        assert TemplateEngine._finalize(SafeNull()) == NBSP

    def test_safeobject_to_nbsp(self) -> None:
        """A SafeObject finalizes to a non-breaking space."""
        assert TemplateEngine._finalize(SafeObject()) == NBSP

    def test_scalar_passthrough(self) -> None:
        """A non-empty scalar is returned unchanged."""
        assert TemplateEngine._finalize(0) == 0
        assert TemplateEngine._finalize('text') == 'text'
