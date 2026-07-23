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
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
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

    def test_only_known_fields_are_kept_and_checkbox_coerced(self) -> None:
        """A field present on the type is kept; a checkbox value is coerced to bool."""
        mock_self = _mock_json_self({'properties': {}})
        entry = {'fields': [
            {'name': 'flag', 'value': 'true'},
            {'name': 'ghost', 'value': 'x'},
        ]}
        possible = [{'name': 'flag', 'type': 'checkbox'}]

        result = JsonObjectImporter.generate_object(mock_self, entry, fields=possible)

        assert len(result['fields']) == 1
        assert result['fields'][0]['name'] == 'flag'
        assert result['fields'][0]['value'] is True

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
        """start_import parses, generates from the type fields, and imports."""
        mock_self = MagicMock()
        mock_self.parser.parse.return_value = 'PARSED'
        mock_self.objects_manager.get_object_type.return_value.get_fields.return_value = ['f']
        mock_self._generate_objects.return_value = ['obj']
        mock_self._import.return_value = 'RESULT'

        result = JsonObjectImporter.start_import(mock_self)

        mock_self._generate_objects.assert_called_once_with('PARSED', fields=['f'])
        mock_self._import.assert_called_once_with(['obj'])
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
        mock_self._resolve_reference_field.return_value = None
        entry = {'col_active': True, 'col_label': 'hello'}
        possible = [{'name': 'label', 'type': 'text'}]

        with patch(f'{CSV_PATH}.ImproveObject') as improve:
            improve.return_value.improve_entry.return_value = entry
            with patch(f'{CSV_PATH}.datetime'):
                result = CsvObjectImporter.generate_object(mock_self, entry, fields=possible)

        assert result['active'] is True
        assert result['fields'] == [{'name': 'label', 'value': 'hello'}]

    def test_unknown_field_is_skipped(self) -> None:
        """A mapped field that is not defined on the type is not added."""
        entry = {'col_ghost': 'x'}
        possible: list = [{'name': 'real', 'type': 'text'}]
        field_entries = [_map_entry('ghost', 'col_ghost')]

        result = CsvObjectImporter._build_object_fields(MagicMock(), field_entries, [], entry, possible)

        assert not result

    def test_resolved_reference_is_appended(self) -> None:
        """A reference entry that resolves is appended to the object's fields."""
        mock_self = MagicMock()
        mock_self._resolve_reference_field.return_value = {'name': 'owner', 'value': 42}
        foreign = _map_entry('owner', 'col_owner', type_id=2, ref_name='name')

        result = CsvObjectImporter._build_object_fields(mock_self, [], [foreign], {}, [])

        assert result == [{'name': 'owner', 'value': 42}]

    def test_unresolved_reference_is_not_appended(self) -> None:
        """A reference entry that does not resolve is skipped."""
        mock_self = MagicMock()
        mock_self._resolve_reference_field.return_value = None
        foreign = _map_entry('owner', 'col_owner', type_id=2, ref_name='name')

        result = CsvObjectImporter._build_object_fields(mock_self, [], [foreign], {}, [])

        assert not result

    def test_construction_sets_file_type(self) -> None:
        """Constructing the importer wires the CSV file type via the content-type mixin."""
        importer = CsvObjectImporter()

        assert importer.get_file_type() == 'csv'
        assert importer.get_config() is None


class TestCsvResolveReferenceField:
    """Resolving a reference mapping entry to a {name, value} field."""

    def test_incomplete_options_return_none(self) -> None:
        """Missing ref options (type_id/ref_name) skip the reference."""
        mock_self = MagicMock()
        foreign = _map_entry('ref_field', 'col_ref')  # no options

        assert CsvObjectImporter._resolve_reference_field(mock_self, foreign, {}) is None

    def test_unique_match_returns_reference_field(self) -> None:
        """A single matching object yields a reference field with its public_id."""
        mock_self = MagicMock()
        found = MagicMock()
        found.get_public_id.return_value = 42
        mock_self.objects_manager.get_objects_by.return_value = [found]
        foreign = _map_entry('owner', 'col_owner', type_id=2, ref_name='name')

        result = CsvObjectImporter._resolve_reference_field(mock_self, foreign, {'col_owner': 'bob'})

        assert result == {'name': 'owner', 'value': 42}

    def test_non_unique_match_returns_none(self) -> None:
        """A reference that resolves to more than one object is skipped."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_objects_by.return_value = [MagicMock(), MagicMock()]
        foreign = _map_entry('owner', 'col_owner', type_id=2, ref_name='name')

        assert CsvObjectImporter._resolve_reference_field(mock_self, foreign, {'col_owner': 'bob'}) is None

    def test_lookup_error_returns_none(self) -> None:
        """A get error while resolving the reference is logged and skipped."""
        mock_self = MagicMock()
        mock_self.objects_manager.get_objects_by.side_effect = ObjectsManagerGetError("db down")
        foreign = _map_entry('owner', 'col_owner', type_id=2, ref_name='name')

        assert CsvObjectImporter._resolve_reference_field(mock_self, foreign, {'col_owner': 'bob'}) is None


class TestCsvStartImport:
    """The CSV import wiring and error contract."""

    def test_wires_parse_generate_import(self) -> None:
        """start_import parses, generates from the type fields, and imports."""
        mock_self = MagicMock()
        mock_self.parser.parse.return_value = 'PARSED'
        mock_self.objects_manager.get_object_type.return_value.get_fields.return_value = ['f']
        mock_self._generate_objects.return_value = ['obj']
        mock_self._import.return_value = 'RESULT'

        result = CsvObjectImporter.start_import(mock_self)

        mock_self._generate_objects.assert_called_once_with('PARSED', fields=['f'])
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
