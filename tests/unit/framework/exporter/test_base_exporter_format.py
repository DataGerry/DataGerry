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

    def test_render_view_reference_uses_the_referenced_objects_info(self) -> None:
        """A reference renders the REFERENCED object's '<type_label> #<object_id> | <summary values>'."""
        field = {'type': 'ref', 'value': 3,
                 'reference': {'object_id': 3, 'type_label': 'User',
                               'summaries': [{'value': 'web01'}, {'value': 'prod'}]}}
        # the referenced object's type/id (User #3), NOT the exporting object's (Server #5)
        assert BaseExporterFormat.summary_renderer(_obj(), field, 'render') == 'User #3 | web01 | prod'

    def test_render_view_reference_without_summaries(self) -> None:
        """A reference with no summaries renders just the referenced type header."""
        field = {'type': 'ref', 'value': 3, 'reference': {'object_id': 3, 'type_label': 'User'}}
        assert BaseExporterFormat.summary_renderer(_obj(), field, 'render') == 'User #3'

    def test_render_view_unresolved_reference_returns_empty(self) -> None:
        """A reference with no resolved object (empty reference) yields an empty string."""
        assert BaseExporterFormat.summary_renderer(_obj(), {'type': 'ref', 'reference': None}, 'render') == ''

    def test_view_is_case_insensitive(self) -> None:
        """The view comparison is case-insensitive (RENDER == render)."""
        field = {'type': 'ref', 'value': 3, 'reference': {'object_id': 3, 'type_label': 'User',
                                                          'summaries': [{'value': 'x'}]}}
        assert BaseExporterFormat.summary_renderer(_obj(), field, 'RENDER') == 'User #3 | x'


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


class TestSerializeMultiDataSections:
    """serialize_multi_data_sections normalizes MDS to the shared {name,value} shape."""

    def test_none_and_empty_yield_empty_list(self) -> None:
        """None or an empty section list serialize to an empty list."""
        assert not BaseExporterFormat.serialize_multi_data_sections(None)
        assert not BaseExporterFormat.serialize_multi_data_sections([])

    def test_serializes_sections_rows_and_drops_field_type(self) -> None:
        """Each section/row is kept; each data entry is reduced to {name, value} (type dropped)."""
        mds = [{
            'section_id': 's1',
            'highest_id': 2,
            'values': [
                {'multi_data_id': 1, 'data': [{'name': 'f', 'value': 'v', 'type': 'text'}]},
                {'multi_data_id': 2, 'data': [{'name': 'f', 'value': 'w', 'type': 'text'}]},
            ],
        }]

        result = BaseExporterFormat.serialize_multi_data_sections(mds)

        assert result == [{
            'section_id': 's1',
            'highest_id': 2,
            'values': [
                {'multi_data_id': 1, 'data': [{'name': 'f', 'value': 'v'}]},
                {'multi_data_id': 2, 'data': [{'name': 'f', 'value': 'w'}]},
            ],
        }]

    def test_missing_keys_default_gracefully(self) -> None:
        """Absent section keys default (None / empty), never raising."""
        result = BaseExporterFormat.serialize_multi_data_sections([{}])

        assert result == [{'section_id': None, 'highest_id': None, 'values': []}]


class TestIsHumanReadable:
    """is_human_readable parses the human_readable option truthily."""

    @pytest.mark.parametrize('value', [True, 'true', 'True', '1', 'yes', 'YES'])
    def test_truthy_values(self, value) -> None:
        """Recognised truthy representations enable the presentation export."""
        assert BaseExporterFormat.is_human_readable({'human_readable': value}) is True

    @pytest.mark.parametrize('options', [None, {}, {'human_readable': False}, {'human_readable': 'false'},
                                         {'human_readable': '0'}, {'human_readable': 'off'}])
    def test_falsy_or_absent(self, options) -> None:
        """Absent / falsy values keep the default (raw) export."""
        assert BaseExporterFormat.is_human_readable(options) is False


class TestResolveExportValue:
    """resolve_export_value resolves ref / ref-section / location values when human_readable."""

    def test_non_human_readable_falls_back_to_summary_renderer(self) -> None:
        """Without the flag it returns the raw value (native summary_renderer)."""
        field = {'type': 'ref', 'value': 3, 'reference': {'object_id': 3, 'type_label': 'Server'}}
        assert BaseExporterFormat.resolve_export_value(_obj(), field, 'native') == 3

    def test_reference_resolves_to_summary_line(self) -> None:
        """A reference field resolves to the referenced object's summary line."""
        field = {'type': 'ref', 'value': 3,
                 'reference': {'object_id': 3, 'type_label': 'Server',
                               'summaries': [{'value': 'web01'}, {'value': 'prod'}]}}
        assert BaseExporterFormat.resolve_export_value(_obj(), field, 'native', True) == 'Server #3 | web01 | prod'

    def test_empty_reference_returns_empty(self) -> None:
        """A reference with no resolved object yields an empty cell."""
        field = {'type': 'ref', 'value': '', 'reference': {}}
        assert BaseExporterFormat.resolve_export_value(_obj(), field, 'native', True) == ''

    def test_ref_section_resolves_to_constructed_summary_line(self) -> None:
        """A ref-section resolves to '<type_label> #<ref_id> | <pulled field values>'."""
        field = {'type': 'ref-section-field', 'value': 7,
                 'references': {'type_label': 'Rack', 'fields': [{'value': 'R-12'}, {'value': 'DC1'}]}}
        assert BaseExporterFormat.resolve_export_value(_obj(), field, 'native', True) == 'Rack #7 | R-12 | DC1'

    def test_ref_section_empty_value_returns_empty(self) -> None:
        """A ref-section with no value yields an empty cell."""
        field = {'type': 'ref-section-field', 'value': ''}
        assert BaseExporterFormat.resolve_export_value(_obj(), field, 'native', True) == ''

    def test_ref_section_without_pulled_values(self) -> None:
        """A ref-section whose pulled fields are all empty renders just the type header."""
        field = {'type': 'ref-section-field', 'value': 7, 'references': {'type_label': 'Rack', 'fields': []}}
        assert BaseExporterFormat.resolve_export_value(_obj(), field, 'native', True) == 'Rack #7'

    def test_location_resolves_to_name(self) -> None:
        """A location field resolves its public_id to the location's tree name."""
        field = {'type': 'location', 'value': 42}
        result = BaseExporterFormat.resolve_export_value(_obj(), field, 'native', True, {42: 'Berlin/Room-1'})
        assert result == 'Berlin/Room-1'

    def test_location_without_map_entry_falls_back_to_id(self) -> None:
        """An unresolved location id degrades to the raw id (never crashes)."""
        field = {'type': 'location', 'value': 42}
        assert BaseExporterFormat.resolve_export_value(_obj(), field, 'native', True, {}) == '42'

    def test_empty_location_returns_empty(self) -> None:
        """An empty location value yields an empty cell."""
        field = {'type': 'location', 'value': ''}
        assert BaseExporterFormat.resolve_export_value(_obj(), field, 'native', True, {}) == ''


class TestHeaderLabels:
    """build_field_label_map / label_for_column / relabel_header handle the human-readable header."""

    @staticmethod
    def _data():
        return [SimpleNamespace(fields=[
            {'name': 'dg-name', 'type': 'text', 'label': 'Hostname'},
            {'name': 'nolabel', 'type': 'text'},
        ])]

    def test_build_field_label_map_falls_back_to_name(self) -> None:
        """Fields without a label fall back to their own name."""
        assert BaseExporterFormat.build_field_label_map(self._data()) == {'dg-name': 'Hostname', 'nolabel': 'nolabel'}

    def test_build_field_label_map_empty_data(self) -> None:
        """An empty export yields an empty label map."""
        assert BaseExporterFormat.build_field_label_map([]) == {}

    def test_identity_columns_get_friendly_labels(self) -> None:
        """public_id / active map to their friendly labels."""
        assert BaseExporterFormat.label_for_column('public_id', {}) == 'Public ID'
        assert BaseExporterFormat.label_for_column('active', {}) == 'Active'

    def test_relabel_header_maps_identity_and_fields(self) -> None:
        """relabel_header swaps identity + field names for their labels, unknown names pass through."""
        header = ['public_id', 'active', 'dg-name', 'nolabel']
        assert BaseExporterFormat.relabel_header(header, self._data()) == \
            ['Public ID', 'Active', 'Hostname', 'nolabel']
