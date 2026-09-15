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

from cmdb.errors.exporter import ExporterMetadataError

from cmdb.framework.exporter.format.base_exporter_format import (
    BaseExporterFormat,
    EMPTY_CELL,
    to_export_cell,
)
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


class TestMetadataOverrideIsValidated:
    """The render-view metadata override comes from the query string, so it is checked, not trusted."""

    @staticmethod
    def _args(metadata: str) -> tuple:
        """The export args of a render-view request carrying the given metadata."""
        return ({'view': 'render', 'metadata': metadata},)

    def test_a_usable_override_is_parsed(self) -> None:
        """A JSON object with list values is handed on to the format."""
        view, metadata = BaseExporterFormat.resolve_export_view(
            self._args('{"header": ["public_id"], "columns": ["dg-name"]}')
        )

        assert view == 'render'
        assert metadata == {'header': ['public_id'], 'columns': ['dg-name']}

    def test_an_unparsable_override_is_refused(self) -> None:
        """Reported as an ExporterError, which the route turns into a 400."""
        with pytest.raises(ExporterMetadataError):
            BaseExporterFormat.resolve_export_view(self._args('not-json'))

    @pytest.mark.parametrize('metadata', ['[1, 2]', '"a string"', '42'],
                             ids=['list', 'string', 'number'])
    def test_an_override_that_is_not_an_object_is_refused(self, metadata: str) -> None:
        """The override selects header and columns, so it has to be a mapping."""
        with pytest.raises(ExporterMetadataError):
            BaseExporterFormat.resolve_export_view(self._args(metadata))

    @pytest.mark.parametrize('key', ['header', 'columns'])
    def test_a_scalar_where_a_list_belongs_is_refused(self, key: str) -> None:
        """A string would be spread character by character into the exported header."""
        with pytest.raises(ExporterMetadataError):
            BaseExporterFormat.resolve_export_view(self._args(f'{{"{key}": "public_id"}}'))

    @pytest.mark.parametrize('key', ['header', 'columns'])
    def test_an_absent_key_is_allowed(self, key: str) -> None:
        """Only the keys the override actually carries are checked."""
        _, metadata = BaseExporterFormat.resolve_export_view(self._args(f'{{"{key}": []}}'))

        assert metadata == {key: []}

    def test_an_already_decoded_override_is_accepted(self) -> None:
        """A caller passing the parsed object (not the raw string) is not re-parsed."""
        _, metadata = BaseExporterFormat.resolve_export_view(
            ({'view': 'render', 'metadata': {'header': ['public_id']}},)
        )

        assert metadata == {'header': ['public_id']}

    def test_the_native_view_never_parses_the_override(self) -> None:
        """Outside the render view the override is not read at all, so it cannot fail."""
        view, metadata = BaseExporterFormat.resolve_export_view(({'metadata': 'not-json'},))

        assert view.upper() == 'NATIVE'
        assert metadata is None


class TestToExportCell:
    """An unfilled value becomes an empty cell instead of the literal text 'None'."""

    def test_none_becomes_an_empty_cell(self) -> None:
        """The absent value is what an unfilled field resolves to."""
        assert to_export_cell(None) == EMPTY_CELL

    def test_a_string_is_kept(self) -> None:
        """A present string passes through unchanged."""
        assert to_export_cell('host-1') == 'host-1'

    @pytest.mark.parametrize(
        'value, expected',
        [(0, '0'), (False, 'False'), ('', ''), (0.0, '0.0'), (42, '42')],
        ids=['zero', 'false', 'empty-string', 'zero-float', 'int'],
    )
    def test_present_values_are_stringified(self, value, expected: str) -> None:
        """Only None counts as absent - a falsy value still exports as its own text."""
        assert to_export_cell(value) == expected

    def test_the_literal_none_string_is_kept(self) -> None:
        """A value that genuinely reads 'None' is a value, and is not blanked."""
        assert to_export_cell('None') == 'None'


class TestObjectPrefixCellsEmptyValues:
    """The regular-field cells of an object's first row never carry the text 'None'."""

    @staticmethod
    def _obj_with(fields: list[dict]) -> SimpleNamespace:
        """A rendered object exposing the given fields and a minimal object_information."""
        return SimpleNamespace(
            fields=fields,
            object_information={'object_id': 1},
            type_information={'type_label': 'Server', 'type_id': 5},
        )

    def test_an_unfilled_field_exports_as_an_empty_cell(self) -> None:
        """A field whose value is None yields an empty cell, not 'None'."""
        obj = self._obj_with([{'type': 'text', 'name': 'note', 'value': None}])

        cells = BaseExporterFormat.object_prefix_cells(obj, [], ['note'], 'native')

        assert cells == [EMPTY_CELL]

    def test_a_column_the_object_lacks_exports_as_an_empty_cell(self) -> None:
        """A regular column with no matching field on the object yields an empty cell."""
        obj = self._obj_with([{'type': 'text', 'name': 'note', 'value': 'x'}])

        cells = BaseExporterFormat.object_prefix_cells(obj, [], ['absent'], 'native')

        assert cells == [EMPTY_CELL]

    def test_a_falsy_value_is_still_exported(self) -> None:
        """A zero is a value and must survive the export."""
        obj = self._obj_with([{'type': 'number', 'name': 'count', 'value': 0}])

        assert BaseExporterFormat.object_prefix_cells(obj, [], ['count'], 'native') == ['0']

    def test_an_identity_column_that_is_none_exports_as_an_empty_cell(self) -> None:
        """An object_information entry present but unset yields an empty cell."""
        obj = self._obj_with([])
        obj.object_information = {'object_id': None}

        assert BaseExporterFormat.object_prefix_cells(obj, ['public_id'], [], 'native') == [EMPTY_CELL]


class TestMdsCellsEmptyValues:
    """The multi-data-section cells never carry the text 'None' either."""

    LAYOUT: list[tuple[str, list[str]]] = [('sec', ['a', 'b'])]

    def test_an_unfilled_entry_field_exports_as_an_empty_cell(self) -> None:
        """A row whose field is present but unset yields an empty cell."""
        entries = {'sec': [{'a': 'filled', 'b': None}]}

        assert BaseExporterFormat.mds_cells_for_index(self.LAYOUT, entries, 0) == ['filled', EMPTY_CELL]

    def test_a_missing_entry_field_exports_as_an_empty_cell(self) -> None:
        """A row missing the field entirely behaves the same as an unset one."""
        entries = {'sec': [{'a': 'filled'}]}

        assert BaseExporterFormat.mds_cells_for_index(self.LAYOUT, entries, 0) == ['filled', EMPTY_CELL]

    def test_a_row_beyond_the_sections_entries_is_blank(self) -> None:
        """A section with fewer entries than the object's block leaves trailing cells empty."""
        entries = {'sec': [{'a': 'filled', 'b': 'x'}]}

        assert BaseExporterFormat.mds_cells_for_index(self.LAYOUT, entries, 1) == [EMPTY_CELL, EMPTY_CELL]


class TestSummaryLineEmptyValues:
    """A summary line skips unfilled parts without dropping a value that reads 'None'."""

    def test_reference_summary_skips_an_unfilled_summary_field(self) -> None:
        """An unset summary value is left out rather than rendered as 'None'."""
        field = {'type': 'ref', 'value': 3,
                 'reference': {'object_id': 3, 'type_label': 'Server',
                               'summaries': [{'value': 'web01'}, {'value': None}]}}

        assert BaseExporterFormat.resolve_export_value(_obj(), field, 'native', True) == 'Server #3 | web01'

    def test_ref_section_summary_skips_an_unfilled_pulled_field(self) -> None:
        """An unset pulled-in value is left out rather than rendered as 'None'."""
        field = {'type': 'ref-section-field', 'value': 7,
                 'references': {'type_label': 'Rack', 'fields': [{'value': 'R-12'}, {'value': None}]}}

        assert BaseExporterFormat.resolve_export_value(_obj(), field, 'native', True) == 'Rack #7 | R-12'

    def test_ref_section_summary_keeps_a_value_that_reads_none(self) -> None:
        """Regression: the old `!= 'None'` guard also dropped a legitimate value spelled 'None'."""
        field = {'type': 'ref-section-field', 'value': 7,
                 'references': {'type_label': 'Rack', 'fields': [{'value': 'None'}, {'value': 'DC1'}]}}

        assert BaseExporterFormat.resolve_export_value(_obj(), field, 'native', True) == 'Rack #7 | None | DC1'
