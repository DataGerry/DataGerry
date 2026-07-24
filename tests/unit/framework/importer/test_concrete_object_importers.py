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
Unit tests for the concrete object importers (JsonObjectImporter / CsvObjectImporter)

DB-free: the ``generate_object`` / mapping helpers run on a MagicMock-typed ``self`` (config,
objects_manager, request_user mocked); ``start_import`` wiring and the CSV reference lookup are
exercised through the mocked ObjectsManager. Focus: object dicts are built with the right keys,
type-field validation/coercion, CSV reference resolution, and the ImportRuntimeError contract.
"""
from unittest.mock import MagicMock, patch

import pytest

from cmdb.framework.importer.importers.json_object_importer import JsonObjectImporter
from cmdb.framework.importer.importers.csv_object_importer import CsvObjectImporter
from cmdb.errors.importer import ImportRuntimeError, ParserRuntimeError
# -------------------------------------------------------------------------------------------------------------------- #
# The suite drives the class-under-test's methods directly on a MagicMock ``self`` (unbound calls)
# pylint: disable=protected-access,no-value-for-parameter

JSON_PATH: str = 'cmdb.framework.importer.importers.json_object_importer'
CSV_PATH: str = 'cmdb.framework.importer.importers.csv_object_importer'


def _mock_json_self(mapping: dict, type_id: int = 1, author_id: int = 7) -> MagicMock:
    """A MagicMock JsonObjectImporter self with config/request_user wired."""
    mock_self = MagicMock()
    mock_self.config.get_mapping.return_value = mapping
    mock_self.config.get_type_id.return_value = type_id
    mock_self.request_user.get_public_id.return_value = author_id
    return mock_self


# -------------------------------------------------------------------------------------------------------------------- #
#                                               JsonObjectImporter                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

class TestJsonGenerateObject:
    """Building a CmdbObject dict from a parsed JSON entry."""

    def test_builds_object_with_core_keys(self) -> None:
        """The generated object carries the type/author/version/creation-time metadata."""
        mock_self = _mock_json_self({'properties': {}})
        entry = {'fields': []}

        with patch(f'{JSON_PATH}.datetime') as dt:
            dt.now.return_value = 'NOW'
            result = JsonObjectImporter.generate_object(mock_self, entry, fields=[])

        assert result['type_id'] == 1
        assert result['author_id'] == 7
        assert result['version'] == '1.0.0'
        assert result['creation_time'] == 'NOW'
        assert result['fields'] == []

    def test_mapped_property_is_copied_from_entry(self) -> None:
        """A mapped property (e.g. active) is copied from the source entry onto the object."""
        mock_self = _mock_json_self({'properties': {'active': 'active'}})
        mock_self._map_element = JsonObjectImporter._map_element.__get__(mock_self)
        entry = {'active': True, 'fields': []}

        result = JsonObjectImporter.generate_object(mock_self, entry, fields=[])

        assert result['active'] is True

    def test_multi_data_sections_passed_through(self) -> None:
        """An entry's multi_data_sections are carried onto the object."""
        mock_self = _mock_json_self({'properties': {}})
        entry = {'fields': [], 'multi_data_sections': [{'section_id': 's1'}]}

        result = JsonObjectImporter.generate_object(mock_self, entry, fields=[])

        assert result['multi_data_sections'] == [{'section_id': 's1'}]

    def test_all_fields_kept_without_value_coercion(self) -> None:
        """Every field is kept as-is (unknown ones included); value coercion is the validator's job."""
        mock_self = _mock_json_self({'properties': {}})
        entry = {'fields': [
            {'name': 'flag', 'value': 'true'},
            {'name': 'ghost', 'value': 'x'},
        ]}

        result = JsonObjectImporter.generate_object(mock_self, entry, fields=[{'name': 'flag', 'type': 'checkbox'}])

        # both fields kept (unknown 'ghost' is rejected later by normalization, not dropped here);
        # 'flag' is NOT bool-coerced here - Rule 7 does that in the validator
        assert [field['name'] for field in result['fields']] == ['flag', 'ghost']
        flag = next(field for field in result['fields'] if field['name'] == 'flag')
        assert flag['value'] == 'true'

    def test_non_checkbox_known_field_is_kept_without_bool_coercion(self) -> None:
        """A non-checkbox field present on the type is kept as-is (only date coercion applies)."""
        mock_self = _mock_json_self({'properties': {}})
        entry = {'fields': [{'name': 'label', 'value': 'hello'}]}
        possible = [{'name': 'label', 'type': 'text'}]

        result = JsonObjectImporter.generate_object(mock_self, entry, fields=possible)

        assert result['fields'] == [{'name': 'label', 'value': 'hello'}]

    def test_construction_sets_file_type(self) -> None:
        """Constructing the importer wires the JSON file type via the content-type mixin."""
        importer = JsonObjectImporter()

        assert importer.get_file_type() == 'json'
        assert importer.get_config() is None

    def test_start_import_wraps_unexpected_error(self) -> None:
        """A non-parser error during start_import is also wrapped as ImportRuntimeError."""
        mock_self = MagicMock()
        mock_self.parser.parse.side_effect = RuntimeError("boom")

        with pytest.raises(ImportRuntimeError):
            JsonObjectImporter.start_import(mock_self)

    def test_map_element_copies_present_value(self) -> None:
        """_map_element copies the mapped source value onto the object."""
        result = JsonObjectImporter._map_element(
            MagicMock(), 'active', {'active': True}, {}, {'active': 'active'},
        )

        assert result['active'] is True

    def test_map_element_skips_missing_source_value(self) -> None:
        """_map_element leaves the object untouched when the mapped source value is absent."""
        result = JsonObjectImporter._map_element(
            MagicMock(), 'active', {}, {}, {'active': 'active'},
        )

        assert not result

    def test_map_element_empty_mapping_is_noop(self) -> None:
        """_map_element with no mapping returns the object unchanged."""
        result = JsonObjectImporter._map_element(MagicMock(), 'active', {'active': True}, {}, {})

        assert not result

    def test_map_element_unmapped_property_is_noop(self) -> None:
        """_map_element with no source key for the property returns the object unchanged."""
        result = JsonObjectImporter._map_element(
            MagicMock(), 'active', {'active': True}, {}, {'other': 'other'},
        )

        assert not result

    def test_start_import_wraps_parser_error(self) -> None:
        """A ParserRuntimeError during start_import is re-raised as ImportRuntimeError."""
        mock_self = MagicMock()
        mock_self.parser.parse.side_effect = ParserRuntimeError("bad json")

        with pytest.raises(ImportRuntimeError):
            JsonObjectImporter.start_import(mock_self)

    def test_start_import_wires_parse_generate_import(self) -> None:
        """start_import parses, generates from the type fields, and delegates to _import_for_type."""
        mock_self = MagicMock()
        mock_self.parser.parse.return_value = 'PARSED'
        type_instance = mock_self.objects_manager.get_object_type.return_value
        type_instance.get_fields.return_value = ['f']
        mock_self._generate_objects.return_value = ['cand']
        mock_self._import_for_type.return_value = 'RESULT'

        result = JsonObjectImporter.start_import(mock_self)

        mock_self._generate_objects.assert_called_once_with('PARSED', fields=['f'])
        mock_self._import_for_type.assert_called_once_with(['cand'], type_instance)
        assert result == 'RESULT'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                CsvObjectImporter                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def _mock_csv_self(property_entries=None, field_entries=None, foreign_entries=None,
                   type_id: int = 1, author_id: int = 7) -> MagicMock:
    """A MagicMock CsvObjectImporter self whose mapping returns the given entry lists by type."""
    mock_self = MagicMock()
    mock_self.get_config.return_value.get_type_id.return_value = type_id
    mock_self.request_user.get_public_id.return_value = author_id

    lists = {
        'property': property_entries or [],
        'field': field_entries or [],
        'ref': foreign_entries or [],
    }
    mock_self.get_config.return_value.get_mapping.return_value.get_entries_with_option.side_effect = (
        lambda query: lists[query['type']]
    )
    return mock_self


def _map_entry(name: str, value: str, **options) -> MagicMock:
    """A MagicMock MapEntry with get_name/get_value/get_options."""
    entry = MagicMock()
    entry.get_name.return_value = name
    entry.get_value.return_value = value
    entry.get_options.return_value = options
    return entry


class TestCsvGenerateObject:
    """Building a CmdbObject dict from a CSV row + mapping."""

    def test_missing_fields_kwarg_raises_import_runtime_error(self) -> None:
        """Omitting the required 'fields' kwarg raises ImportRuntimeError."""
        with pytest.raises(ImportRuntimeError):
            CsvObjectImporter.generate_object(MagicMock(), {})

    def test_property_and_known_field_are_written(self) -> None:
        """A mapped property is set on the object; a known mapped field is added to fields."""
        mock_self = _mock_csv_self(
            property_entries=[_map_entry('active', 'col_active')],
            field_entries=[_map_entry('label', 'col_label')],
        )
        mock_self._build_object_fields = CsvObjectImporter._build_object_fields.__get__(mock_self)
        entry = {'col_active': True, 'col_label': 'hello'}
        possible = [{'name': 'label', 'type': 'text'}]

        with patch(f'{CSV_PATH}.ImproveObject') as improve:
            improve.return_value.improve_entry.return_value = entry
            with patch(f'{CSV_PATH}.datetime'):
                result = CsvObjectImporter.generate_object(mock_self, entry, fields=possible)

        assert result['active'] is True
        assert result['fields'] == [{'name': 'label', 'value': 'hello'}]

    def test_unknown_field_is_kept_for_validation(self) -> None:
        """A mapped field is added regardless of the type; unknown fields are rejected in validation."""
        entry = {'col_ghost': 'x'}
        field_entries = [_map_entry('ghost', 'col_ghost')]

        result = CsvObjectImporter._build_object_fields(MagicMock(), field_entries, [], entry, set())

        assert result == [{'name': 'ghost', 'value': 'x'}]

    def test_mds_field_is_skipped_from_flat_fields(self) -> None:
        """A mapped field whose name belongs to an MDS section is not added as a flat field."""
        entry = {'col_nic': 'eth0'}
        field_entries = [_map_entry('nic_name', 'col_nic')]

        result = CsvObjectImporter._build_object_fields(MagicMock(), field_entries, [], entry, {'nic_name'})

        assert not result

    def test_reference_field_is_appended_cleared(self) -> None:
        """A reference mapping entry is added with a cleared (None) value - no ref_name lookup."""
        mock_self = MagicMock()
        foreign = _map_entry('owner', 'col_owner', type_id=2, ref_name='name')

        result = CsvObjectImporter._build_object_fields(mock_self, [], [foreign], {'col_owner': 'bob'}, set())

        assert result == [{'name': 'owner', 'value': None}]
        # the retired ref_name lookup must not touch the database
        mock_self.objects_manager.get_objects_by.assert_not_called()

    def test_construction_sets_file_type(self) -> None:
        """Constructing the importer wires the CSV file type via the content-type mixin."""
        importer = CsvObjectImporter()

        assert importer.get_file_type() == 'csv'
        assert importer.get_config() is None


class TestCsvMultiDataSectionsImport:
    """CSV import reassembles multi-data sections from the flattened multi-row layout."""

    def test_is_blank(self) -> None:
        """A cell is blank only when it is None or an empty string (0/False are values)."""
        assert CsvObjectImporter._is_blank('') is True
        assert CsvObjectImporter._is_blank(None) is True
        assert CsvObjectImporter._is_blank(0) is False
        assert CsvObjectImporter._is_blank(False) is False
        assert CsvObjectImporter._is_blank('eth0') is False

    def test_build_mds_layout_extracts_only_mds_sections(self) -> None:
        """Only multi-data-sections contribute to the layout, in type order, with their field names."""
        regular = MagicMock()
        regular.type = 'section'
        mds = MagicMock()
        mds.type = 'multi-data-section'
        mds.name = 'nics'
        mds.get_fields.return_value = ['nic_name', 'mac']
        type_instance = MagicMock()
        type_instance.get_sections.return_value = [regular, mds]

        assert CsvObjectImporter._build_mds_layout(type_instance) == [('nics', ['nic_name', 'mac'])]

    def test_group_rows_by_public_id(self) -> None:
        """A blank public_id continues the previous object; a set public_id starts a new one."""
        header = ['public_id', 'active', 'nic_name']
        rows = [{0: 10, 1: True, 2: 'eth0'}, {0: '', 1: '', 2: 'eth1'}, {0: 11, 1: True, 2: 'eth0'}]

        groups = CsvObjectImporter._group_rows(rows, header)

        assert groups == [[rows[0], rows[1]], [rows[2]]]

    def test_group_rows_without_public_id_column_is_one_object_per_row(self) -> None:
        """With no public_id column there is no grouping signal, so each row is its own object."""
        header = ['active', 'nic_name']
        rows = [{0: True, 1: 'eth0'}, {0: '', 1: 'eth1'}]

        assert CsvObjectImporter._group_rows(rows, header) == [[rows[0]], [rows[1]]]

    def test_build_multi_data_sections_single_section_multi_row(self) -> None:
        """Each MDS field is read from its column; rows become 1-based, ordered entries."""
        header = ['public_id', 'active', 'nic_name', 'mac']
        layout = [('nics', ['nic_name', 'mac'])]
        group = [{0: 10, 1: True, 2: 'eth0', 3: 'm0'}, {0: '', 1: '', 2: 'eth1', 3: 'm1'}]

        result = CsvObjectImporter._build_multi_data_sections(group, header, layout)

        assert result == [{
            'section_id': 'nics',
            'highest_id': 2,
            'values': [
                {'multi_data_id': 1, 'data': [{'name': 'nic_name', 'value': 'eth0'},
                                              {'name': 'mac', 'value': 'm0'}]},
                {'multi_data_id': 2, 'data': [{'name': 'nic_name', 'value': 'eth1'},
                                              {'name': 'mac', 'value': 'm1'}]},
            ],
        }]

    def test_build_multi_data_sections_unequal_counts(self) -> None:
        """A section with fewer entries stops where its columns go blank (the 3-vs-2 case)."""
        header = ['public_id', 'nic_name', 'mac', 'disk_label', 'size_gb']
        layout = [('nics', ['nic_name', 'mac']), ('disks', ['disk_label', 'size_gb'])]
        group = [
            {0: 10, 1: 'eth0', 2: 'm0', 3: 'root', 4: 100},
            {0: '', 1: 'eth1', 2: 'm1', 3: 'data', 4: 500},
            {0: '', 1: 'eth2', 2: 'm2', 3: '', 4: ''},
        ]

        result = CsvObjectImporter._build_multi_data_sections(group, header, layout)
        by_id = {section['section_id']: section for section in result}

        assert by_id['nics']['highest_id'] == 3 and len(by_id['nics']['values']) == 3
        assert by_id['disks']['highest_id'] == 2 and len(by_id['disks']['values']) == 2

    def test_build_multi_data_sections_skips_section_without_columns(self) -> None:
        """A section whose fields are not columns in the CSV cannot be restored (skipped)."""
        header = ['public_id']
        layout = [('nics', ['nic_name'])]

        assert not CsvObjectImporter._build_multi_data_sections([{0: 10}], header, layout)

    def test_build_multi_data_sections_object_with_no_entries(self) -> None:
        """A type with an MDS section but an object with only blank MDS cells yields no section."""
        header = ['public_id', 'nic_name']
        layout = [('nics', ['nic_name'])]

        assert not CsvObjectImporter._build_multi_data_sections([{0: 10, 1: ''}], header, layout)

    def test_generate_objects_groups_rows_into_one_object_with_mds(self) -> None:
        """_generate_objects groups continuation rows and attaches the reassembled MDS."""
        mock_self = MagicMock()
        mock_self._group_rows = CsvObjectImporter._group_rows
        mock_self._build_multi_data_sections = CsvObjectImporter._build_multi_data_sections
        mock_self._to_provided_json.return_value = {'provided': True}
        mock_self.generate_object.return_value = {'fields': []}
        parsed = MagicMock()
        parsed.entries = [{0: 10, 1: 'eth0'}, {0: '', 1: 'eth1'}]

        result = CsvObjectImporter._generate_objects(
            mock_self, parsed, fields=[], header=['public_id', 'nic_name'], mds_layout=[('nics', ['nic_name'])])

        assert len(result) == 1  # two CSV rows collapsed into one object
        _, generated = result[0]
        assert generated['multi_data_sections'][0]['section_id'] == 'nics'
        assert len(generated['multi_data_sections'][0]['values']) == 2

    def test_generate_objects_without_mds_omits_the_key(self) -> None:
        """When no MDS is reconstructed the object has no multi_data_sections key."""
        mock_self = MagicMock()
        mock_self._group_rows = CsvObjectImporter._group_rows
        mock_self._build_multi_data_sections = CsvObjectImporter._build_multi_data_sections
        mock_self._to_provided_json.return_value = {}
        mock_self.generate_object.return_value = {'fields': []}
        parsed = MagicMock()
        parsed.entries = [{0: 10, 1: 'host'}]

        result = CsvObjectImporter._generate_objects(
            mock_self, parsed, fields=[], header=['public_id', 'dg-name'], mds_layout=[])

        _, generated = result[0]
        assert 'multi_data_sections' not in generated

    def test_export_import_roundtrip_via_new_layout(self) -> None:
        """A CSV MDS export parses back (index-keyed + auto_cast) into the same section entries."""
        # pylint: disable=import-outside-toplevel
        import csv as _csv
        from io import StringIO
        from types import SimpleNamespace
        from cmdb.utils.cast import auto_cast
        from cmdb.framework.exporter.format.csv_export_format import CsvExportFormat

        sections = [{'type': 'multi-data-section', 'name': 'nics', 'label': 'nics',
                     'fields': ['nic_name', 'mac']}]
        mds = [{'section_id': 'nics', 'highest_id': 2, 'values': [
            {'multi_data_id': 1, 'data': [{'name': 'nic_name', 'value': 'eth0'},
                                          {'name': 'mac', 'value': 'm0'}]},
            {'multi_data_id': 2, 'data': [{'name': 'nic_name', 'value': 'eth1'},
                                          {'name': 'mac', 'value': 'm1'}]},
        ]}]
        obj = SimpleNamespace(
            fields=[{'name': 'dg-name', 'type': 'text', 'value': 'host-1'}],
            sections=sections,
            multi_data_sections=mds,
            object_information={'object_id': 10, 'active': True},
            type_information={'type_id': 5, 'type_label': 'Server'},
        )

        # Export to CSV, then parse it back the way CsvObjectParser does (index-keyed rows + auto_cast)
        parsed_rows = list(_csv.reader(StringIO(CsvExportFormat().export([obj]).getvalue())))
        header = parsed_rows[0]
        rows = [dict(enumerate([auto_cast(cell) for cell in row])) for row in parsed_rows[1:]]

        type_instance = SimpleNamespace(get_sections=lambda: [
            SimpleNamespace(type='multi-data-section', name='nics', get_fields=lambda: ['nic_name', 'mac'])
        ])
        layout = CsvObjectImporter._build_mds_layout(type_instance)
        groups = CsvObjectImporter._group_rows(rows, header)

        assert len(groups) == 1  # the two exported rows are one object again
        assert CsvObjectImporter._build_multi_data_sections(groups[0], header, layout) == mds


class TestCsvStartImport:
    """The CSV import wiring and error contract."""

    def test_wires_parse_generate_import(self) -> None:
        """start_import parses, builds the MDS layout, generates, and delegates to _import_for_type."""
        parsed = MagicMock()
        mock_self = MagicMock()
        mock_self.parser.parse.return_value = parsed
        type_instance = mock_self.objects_manager.get_object_type.return_value
        type_instance.get_fields.return_value = ['f']
        mock_self._build_mds_layout.return_value = [('nics', ['nic_name'])]
        mock_self._generate_objects.return_value = ['cand']
        mock_self._import_for_type.return_value = 'RESULT'

        result = CsvObjectImporter.start_import(mock_self)

        header = parsed.get_header_list.return_value
        mock_self._build_mds_layout.assert_called_once_with(type_instance)
        mock_self._generate_objects.assert_called_once_with(
            parsed, fields=['f'], header=header, mds_layout=[('nics', ['nic_name'])])
        mock_self._import_for_type.assert_called_once_with(['cand'], type_instance)
        assert result == 'RESULT'

    def test_parser_error_becomes_import_runtime_error(self) -> None:
        """A ParserRuntimeError is re-raised as ImportRuntimeError."""
        mock_self = MagicMock()
        mock_self.parser.parse.side_effect = ParserRuntimeError("bad csv")

        with pytest.raises(ImportRuntimeError):
            CsvObjectImporter.start_import(mock_self)

    def test_unexpected_error_becomes_import_runtime_error(self) -> None:
        """Any other error is wrapped as ImportRuntimeError."""
        mock_self = MagicMock()
        mock_self.parser.parse.side_effect = RuntimeError("boom")

        with pytest.raises(ImportRuntimeError):
            CsvObjectImporter.start_import(mock_self)


class TestCsvProvidedJson:
    """The CSV row -> provided-object (header-keyed JSON) transform used for the failure report."""

    def test_maps_row_to_header_keyed_dict(self) -> None:
        """An index-keyed row is mapped to a {column: value} object via the header."""
        entry = {0: 10, 1: True, 2: 'host'}

        result = CsvObjectImporter._to_provided_json(
            MagicMock(), entry, header=['public_id', 'active', 'dg-name'])

        assert result == {'public_id': 10, 'active': True, 'dg-name': 'host'}

    def test_empty_without_header(self) -> None:
        """With no header there is nothing to key by, so the provided object is empty."""
        assert CsvObjectImporter._to_provided_json(MagicMock(), {0: 'x'}) == {}
