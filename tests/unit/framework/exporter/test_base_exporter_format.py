# DataGerry - OpenSource Enterprise CMDB
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
Unit tests for cmdb.framework.exporter.format.base_exporter_format
"""
from types import SimpleNamespace

import pytest

from cmdb.framework.exporter.format.base_exporter_format import BaseExporterFormat
# -------------------------------------------------------------------------------------------------------------------- #


def _obj() -> SimpleNamespace:
    """A stand-in rendered object exposing the type_information the reference summary needs."""
    return SimpleNamespace(type_information={'type_label': 'Server', 'type_id': 5})


class TestSummaryRenderer:
    """summary_renderer returns the raw value (NATIVE) or a reference summary line (RENDER)."""

    def test_non_dict_field_returns_empty_string(self) -> None:
        """A non-dict field yields an empty string."""
        assert BaseExporterFormat.summary_renderer(_obj(), 'not-a-dict') == ""

    def test_native_view_returns_raw_value(self) -> None:
        """The default (native) view returns the field's raw value."""
        assert BaseExporterFormat.summary_renderer(_obj(), {'type': 'text', 'value': 'host-1'}) == 'host-1'

    def test_native_view_missing_value_returns_none(self) -> None:
        """A field without a value returns None in the native view."""
        assert BaseExporterFormat.summary_renderer(_obj(), {'type': 'text'}) is None

    def test_render_view_non_reference_returns_raw_value(self) -> None:
        """In the render view a non-reference field still returns its raw value."""
        field = {'type': 'text', 'value': 'host-1'}
        assert BaseExporterFormat.summary_renderer(_obj(), field, 'render') == 'host-1'

    def test_render_view_reference_builds_summary_line(self) -> None:
        """A reference field renders to '<type_label> #<type_id> | <summary values>'."""
        field = {'type': 'ref', 'value': 3, 'reference': {'summaries': [{'value': 'web01'}, {'value': 'prod'}]}}
        assert BaseExporterFormat.summary_renderer(_obj(), field, 'render') == 'Server #5 | web01 | prod'

    def test_render_view_reference_without_summaries(self) -> None:
        """A reference field with no reference block renders just the type header."""
        assert BaseExporterFormat.summary_renderer(_obj(), {'type': 'ref', 'reference': None}, 'render') == 'Server #5'

    def test_render_view_reference_empty_summaries(self) -> None:
        """A reference field with an empty summaries list renders just the type header."""
        field = {'type': 'ref', 'reference': {'summaries': []}}
        assert BaseExporterFormat.summary_renderer(_obj(), field, 'render') == 'Server #5'

    def test_view_is_case_insensitive(self) -> None:
        """The view comparison is case-insensitive (RENDER == render)."""
        field = {'type': 'ref', 'reference': {'summaries': [{'value': 'x'}]}}
        assert BaseExporterFormat.summary_renderer(_obj(), field, 'RENDER') == 'Server #5 | x'


class TestExport:
    """The base export() is abstract."""

    def test_export_raises_not_implemented(self) -> None:
        """The base class does not implement export()."""
        with pytest.raises(NotImplementedError):
            BaseExporterFormat().export([])


class TestResolveExportView:
    """resolve_export_view returns the requested view + the render metadata (only when render + supplied)."""

    def test_no_args_is_native_without_metadata(self) -> None:
        """No export args -> the default (native) view, no metadata."""
        assert BaseExporterFormat.resolve_export_view(()) == ('NATIVE', None)

    def test_render_view_without_metadata_returns_view_without_metadata(self) -> None:
        """A render view but no metadata -> the requested view, no metadata (column overrides need it)."""
        assert BaseExporterFormat.resolve_export_view(({'view': 'render'},)) == ('render', None)

    def test_metadata_without_render_view_is_ignored(self) -> None:
        """Metadata outside the render view is ignored -> the requested view, no metadata."""
        args = ({'view': 'native', 'metadata': '{"header": ["public_id"]}'},)
        assert BaseExporterFormat.resolve_export_view(args) == ('native', None)

    def test_render_view_with_metadata_parses_it(self) -> None:
        """A render view with metadata -> the requested view and the parsed metadata dict."""
        args = ({'view': 'render', 'metadata': '{"header": ["public_id"], "columns": ["name"]}'},)
        view, metadata = BaseExporterFormat.resolve_export_view(args)
        assert view == 'render'
        assert metadata == {'header': ['public_id'], 'columns': ['name']}
