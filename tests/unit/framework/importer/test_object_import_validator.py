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
Unit tests for cmdb.framework.importer.helper.object_import_validator

DB-free. Covers the strict import-bool parser and the per-object normalization+validation: forced
lifecycle fields, type-derived special_type, defaulted optional fields, and the active validation
(default when absent/empty, reject when an unrecognised value is provided).
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from cmdb.framework.importer.helper.object_import_validator import (
    parse_import_bool,
    normalize_and_validate_object,
    reference_field_names,
    clear_reference_values,
    build_field_type_map,
    build_import_type_context,
    apply_new_select_options,
    ImportTypeContext,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #


def _ctx(clearable=None, type_map=None, required_top=None, required_mds=None,
         top_defaults=None, mds_defaults=None, field_options=None, new_select_options=None) -> ImportTypeContext:
    """Builds an ImportTypeContext with only the parts a test needs (others default empty)."""
    return ImportTypeContext(
        clearable_reference_fields=clearable or set(),
        field_type_map=type_map or {},
        required_top_level=required_top or set(),
        required_mds_by_section=required_mds or {},
        top_level_field_defaults=top_defaults or {},
        mds_field_defaults_by_section=mds_defaults or {},
        field_options=field_options if field_options is not None else {},
        new_select_options=new_select_options if new_select_options is not None else {},
    )


class TestParseImportBool:
    """The strict import-bool parser."""

    @pytest.mark.parametrize('value', [True, 1, '1', 'true', 'True', 'TRUE', 'yes', 'Yes', ' yes '])
    def test_truthy(self, value) -> None:
        """Accepted truthy forms parse to True."""
        assert parse_import_bool(value) is True

    @pytest.mark.parametrize('value', [False, 0, '0', 'false', 'False', 'FALSE', 'no', 'No', ' NO '])
    def test_falsy(self, value) -> None:
        """Accepted falsy forms parse to False."""
        assert parse_import_bool(value) is False

    @pytest.mark.parametrize('value', ['maybe', 2, '2', -1, None, '', 'y', 'n', [], {}])
    def test_invalid_returns_none(self, value) -> None:
        """Any unrecognised value returns None (rejected)."""
        assert parse_import_bool(value) is None


class TestNormalizeAndValidateObject:
    """Per-object normalization + validation."""

    def test_forces_lifecycle_fields(self) -> None:
        """version/creation_time/last_edit_time/editor_id are forced, ignoring provided values."""
        obj = {'version': '9.9', 'last_edit_time': 'x', 'editor_id': 42, 'creation_time': 'old'}

        errors = normalize_and_validate_object(obj, None)

        assert not errors
        assert obj['version'] == '1.0.0'
        assert obj['last_edit_time'] is None
        assert obj['editor_id'] is None
        assert isinstance(obj['creation_time'], datetime)

    def test_special_type_is_taken_from_the_type(self) -> None:
        """special_type is set from the target type, ignoring any provided value."""
        obj = {'special_type': 'SUPERNET'}

        normalize_and_validate_object(obj, SpecialType.SUBNET)

        assert obj['special_type'] == SpecialType.SUBNET

    def test_special_type_none_when_type_has_none(self) -> None:
        """special_type defaults to None when the type has no special type."""
        obj: dict = {}

        normalize_and_validate_object(obj, None)

        assert obj['special_type'] is None

    def test_ci_explorer_tooltip_kept_or_defaulted(self) -> None:
        """A provided ci_explorer_tooltip is kept; an absent one defaults to None."""
        provided = {'ci_explorer_tooltip': 'hover me'}
        absent: dict = {}

        normalize_and_validate_object(provided, None)
        normalize_and_validate_object(absent, None)

        assert provided['ci_explorer_tooltip'] == 'hover me'
        assert absent['ci_explorer_tooltip'] is None

    def test_active_defaults_true_when_absent_or_empty(self) -> None:
        """active defaults to True when absent, None, or an empty string."""
        for obj in ({}, {'active': None}, {'active': ''}):
            assert not normalize_and_validate_object(obj, None)
            assert obj['active'] is True

    def test_active_valid_value_is_coerced(self) -> None:
        """A recognised active value is coerced to a real bool."""
        obj = {'active': 'no'}

        assert not normalize_and_validate_object(obj, None)
        assert obj['active'] is False

    def test_active_invalid_value_is_rejected(self) -> None:
        """An unrecognised active value produces an error (and the object is a reject)."""
        obj = {'active': 'maybe'}

        errors = normalize_and_validate_object(obj, None)

        assert errors == ["Invalid value for 'active': 'maybe'"]


class TestLocationFieldRule:
    """Rule 3: the location field (dg_location) at most once and never inside a multi-data section."""

    def test_single_top_level_location_is_valid(self) -> None:
        """A single dg_location top-level field is accepted."""
        obj = {'fields': [{'name': 'dg_location', 'value': 3}, {'name': 'dg-name', 'value': 'h'}]}

        assert not normalize_and_validate_object(obj, None)

    def test_location_assigned_twice_is_rejected(self) -> None:
        """dg_location appearing twice in the top-level fields is rejected."""
        obj = {'fields': [{'name': 'dg_location', 'value': 3}, {'name': 'dg_location', 'value': 4}]}

        errors = normalize_and_validate_object(obj, None)

        assert "The location field 'dg_location' can only be assigned once" in errors

    def test_location_inside_mds_is_rejected(self) -> None:
        """dg_location appearing inside a multi-data-section row is rejected."""
        obj = {
            'fields': [],
            'multi_data_sections': [
                {'section_id': 's1', 'values': [{'multi_data_id': 1, 'data': [{'name': 'dg_location', 'value': 3}]}]}
            ],
        }

        errors = normalize_and_validate_object(obj, None)

        assert "The location field 'dg_location' is not allowed inside a multi-data section" in errors

    def test_no_location_field_is_valid(self) -> None:
        """An object without any location field passes the location rule."""
        obj = {'fields': [{'name': 'dg-name', 'value': 'h'}]}

        assert not normalize_and_validate_object(obj, None)


class TestUniqueFieldNamesRule:
    """Rule 4: field names (identifiers) are unique in the flat fields and within each MDS row."""

    def test_unique_top_level_fields_are_valid(self) -> None:
        """Distinct top-level field names are accepted."""
        obj = {'fields': [{'name': 'a', 'value': 1}, {'name': 'b', 'value': 2}]}

        assert not normalize_and_validate_object(obj, None)

    def test_duplicate_top_level_field_is_rejected(self) -> None:
        """A repeated top-level field name is rejected."""
        obj = {'fields': [{'name': 'a', 'value': 1}, {'name': 'a', 'value': 2}]}

        errors = normalize_and_validate_object(obj, None)

        assert "Duplicate field name(s) in the object fields: ['a']" in errors

    def test_duplicate_within_one_mds_row_is_rejected(self) -> None:
        """A field name repeated within a single MDS row is rejected."""
        obj = {
            'fields': [],
            'multi_data_sections': [
                {'section_id': 's1',
                 'values': [{'multi_data_id': 1, 'data': [{'name': 'x', 'value': 1}, {'name': 'x', 'value': 2}]}]}
            ],
        }

        errors = normalize_and_validate_object(obj, None)

        assert "Duplicate field name(s) in multi-data section 's1': ['x']" in errors

    def test_same_names_across_mds_rows_are_allowed(self) -> None:
        """The same field names repeating across different MDS rows is allowed (by design)."""
        obj = {
            'fields': [],
            'multi_data_sections': [
                {'section_id': 's1', 'values': [
                    {'multi_data_id': 1, 'data': [{'name': 'nic', 'value': 'eth0'}]},
                    {'multi_data_id': 2, 'data': [{'name': 'nic', 'value': 'eth1'}]},
                ]}
            ],
        }

        assert not normalize_and_validate_object(obj, None)


class TestReferenceFieldNames:
    """reference_field_names collects the ref / ref-section / location field names of a type."""

    def test_collects_only_clearable_types(self) -> None:
        """Only ref, ref-section-field and location fields are collected; others are ignored."""
        type_fields = [
            {'name': 'owner', 'type': 'ref'},
            {'name': 'rack-field', 'type': 'ref-section-field'},
            {'name': 'dg_location', 'type': 'location'},
            {'name': 'hostname', 'type': 'text'},
        ]

        assert reference_field_names(type_fields) == {'owner', 'rack-field', 'dg_location'}

    def test_empty_or_none_is_empty_set(self) -> None:
        """No fields yields an empty set."""
        assert reference_field_names([]) == set()
        assert reference_field_names(None) == set()


class TestClearReferenceValues:
    """clear_reference_values nulls ref/ref-section/location values, top-level and in MDS rows."""

    def test_clears_top_level_and_mds_values(self) -> None:
        """Matching field values are set to None in both the flat fields and MDS rows."""
        obj = {
            'fields': [{'name': 'owner', 'value': 3}, {'name': 'hostname', 'value': 'h'}],
            'multi_data_sections': [
                {'section_id': 's1', 'values': [
                    {'multi_data_id': 1, 'data': [{'name': 'ref_in_mds', 'value': 9},
                                                  {'name': 'plain', 'value': 'keep'}]},
                ]}
            ],
        }

        clear_reference_values(obj, {'owner', 'ref_in_mds'})

        assert obj['fields'] == [{'name': 'owner', 'value': None}, {'name': 'hostname', 'value': 'h'}]
        mds_data = obj['multi_data_sections'][0]['values'][0]['data']
        assert mds_data == [{'name': 'ref_in_mds', 'value': None}, {'name': 'plain', 'value': 'keep'}]

    def test_empty_clearable_set_is_a_noop(self) -> None:
        """With no clearable field names nothing is changed."""
        obj = {'fields': [{'name': 'owner', 'value': 3}]}

        clear_reference_values(obj, set())

        assert obj['fields'] == [{'name': 'owner', 'value': 3}]

    def test_normalize_clears_via_context(self) -> None:
        """normalize_and_validate_object clears the context's reference fields end-to-end."""
        obj = {'fields': [{'name': 'owner', 'value': 3}, {'name': 'dg_location', 'value': 42}]}

        errors = normalize_and_validate_object(obj, None, _ctx(clearable={'owner', 'dg_location'}))

        assert not errors
        assert obj['fields'] == [{'name': 'owner', 'value': None}, {'name': 'dg_location', 'value': None}]


class TestFieldTypeStamping:
    """The field `type` is stamped from the target type; fields the type doesn't define are rejected."""

    def test_build_field_type_map(self) -> None:
        """The map is {field name: field type} over the type's fields."""
        type_fields = [{'name': 'host', 'type': 'text'}, {'name': 'owner', 'type': 'ref'}]

        assert build_field_type_map(type_fields) == {'host': 'text', 'owner': 'ref'}

    def test_types_stamped_top_level_and_mds_overwriting_provided(self) -> None:
        """Each field's type is set from the map, overwriting any provided type, top-level and in MDS."""
        obj = {
            'fields': [{'name': 'host', 'value': 'h', 'type': 'WRONG'}],
            'multi_data_sections': [
                {'section_id': 's1', 'values': [{'multi_data_id': 1, 'data': [{'name': 'nic', 'value': 'eth0'}]}]}
            ],
        }
        errors = normalize_and_validate_object(obj, None, _ctx(type_map={'host': 'text', 'nic': 'text'}))

        assert not errors
        assert obj['fields'][0]['type'] == 'text'  # overwrote 'WRONG'
        assert obj['multi_data_sections'][0]['values'][0]['data'][0]['type'] == 'text'

    def test_unknown_top_level_field_is_rejected(self) -> None:
        """A top-level field not defined on the type rejects the object."""
        obj = {'fields': [{'name': 'ghost', 'value': 'x'}]}

        errors = normalize_and_validate_object(obj, None, _ctx(type_map={'host': 'text'}))

        assert "Field name(s) not defined on the type: ['ghost']" in errors

    def test_duplicate_unknown_field_reported_once(self) -> None:
        """The same unknown field name appearing twice is reported once (deduplicated)."""
        obj = {'fields': [{'name': 'ghost', 'value': 'x'}, {'name': 'ghost', 'value': 'y'}]}

        errors = normalize_and_validate_object(obj, None, _ctx(type_map={'host': 'text'}))

        assert errors.count("Field name(s) not defined on the type: ['ghost']") == 1

    def test_unknown_mds_field_is_rejected(self) -> None:
        """A field inside an MDS row not defined on the type rejects the object."""
        obj = {
            'fields': [],
            'multi_data_sections': [
                {'section_id': 's1', 'values': [{'multi_data_id': 1, 'data': [{'name': 'ghost', 'value': 'x'}]}]}
            ],
        }

        errors = normalize_and_validate_object(obj, None, _ctx(type_map={'host': 'text'}))

        assert "Field name(s) not defined on the type: ['ghost']" in errors

    def test_no_context_skips_stamping_and_rejection(self) -> None:
        """Without a type_context, types are not stamped and unknown fields are not rejected."""
        obj = {'fields': [{'name': 'ghost', 'value': 'x'}]}

        errors = normalize_and_validate_object(obj, None)

        assert not errors
        assert 'type' not in obj['fields'][0]


class TestBuildImportTypeContext:
    """build_import_type_context derives the clearable / type-map / required sets from a type."""

    @staticmethod
    def _type_instance():
        """A fake CmdbType with a ref, a required text field, a required MDS field and a plain field."""
        mds_section = MagicMock()
        mds_section.type = 'multi-data-section'
        mds_section.name = 'nics'
        mds_section.get_fields.return_value = ['nic']
        regular_section = MagicMock()
        regular_section.type = 'section'

        type_instance = MagicMock()
        type_instance.get_fields.return_value = [
            {'name': 'host', 'type': 'text', 'required': True},
            {'name': 'owner', 'type': 'ref', 'required': True},   # required ref -> exempt
            {'name': 'nic', 'type': 'text', 'required': True},    # required MDS field
            {'name': 'note', 'type': 'text', 'value': 'n/a'},     # default value under 'value'
        ]
        type_instance.get_sections.return_value = [regular_section, mds_section]
        return type_instance

    def test_splits_required_and_excludes_reference(self) -> None:
        """A required ref is excluded; a required MDS field lands under its section, not top-level."""
        context = build_import_type_context(self._type_instance())

        assert context.clearable_reference_fields == {'owner'}
        assert context.field_type_map == {'host': 'text', 'owner': 'ref', 'nic': 'text', 'note': 'text'}
        assert context.required_top_level == {'host'}
        assert context.required_mds_by_section == {'nics': {'nic'}}

    def test_collects_field_defaults_split_top_level_and_mds(self) -> None:
        """Defaults come from the field's `value`; MDS fields are grouped per section, not top-level."""
        context = build_import_type_context(self._type_instance())

        # nic is an MDS field -> not a top-level default
        assert context.top_level_field_defaults == {'host': None, 'owner': None, 'note': 'n/a'}
        assert context.mds_field_defaults_by_section == {'nics': {'nic': None}}

    def test_collects_select_and_radio_options(self) -> None:
        """Select and radio option names are collected; new_select_options starts empty."""
        type_instance = MagicMock()
        type_instance.get_fields.return_value = [
            {'name': 'kind', 'type': 'select', 'extras': {'options': [{'name': 'a'}, {'name': 'b'}]}},
            {'name': 'mode', 'type': 'radio', 'extras': {'options': [{'name': 'on'}]}},
            {'name': 'host', 'type': 'text'},
        ]
        type_instance.get_sections.return_value = []

        context = build_import_type_context(type_instance)

        assert context.field_options == {'kind': {'a', 'b'}, 'mode': {'on'}}
        assert context.new_select_options == {}


class TestValueSuitabilityRule:
    """Rule 7: a value must be suitable for its field type or the object is rejected."""

    def test_number_coerces_numeric_string(self) -> None:
        """A numeric string in a number field is coerced; the coerced value is written back."""
        obj = {'fields': [{'name': 'port', 'value': '42'}]}

        assert not normalize_and_validate_object(obj, None, _ctx(type_map={'port': 'number'}))
        assert obj['fields'][0]['value'] == 42

    def test_number_rejects_non_numeric(self) -> None:
        """A non-numeric value in a number field rejects the object."""
        errors = normalize_and_validate_object(
            {'fields': [{'name': 'port', 'value': 'abc'}]}, None, _ctx(type_map={'port': 'number'}))

        assert any("not a valid number" in error for error in errors)

    def test_reference_rejects_non_integer(self) -> None:
        """A non-integer reference value rejects the object (validated before it is cleared)."""
        errors = normalize_and_validate_object(
            {'fields': [{'name': 'owner', 'value': 'abc'}]}, None,
            _ctx(type_map={'owner': 'ref'}, clearable={'owner'}))

        assert any("not a valid reference id" in error for error in errors)

    def test_reference_integer_is_validated_then_cleared(self) -> None:
        """A valid integer reference passes the check and is then cleared to None."""
        obj = {'fields': [{'name': 'owner', 'value': '7'}]}

        assert not normalize_and_validate_object(
            obj, None, _ctx(type_map={'owner': 'ref'}, clearable={'owner'}))
        assert obj['fields'][0]['value'] is None  # cleared after validation

    def test_date_rejects_unparseable(self) -> None:
        """An unparseable date value rejects the object."""
        errors = normalize_and_validate_object(
            {'fields': [{'name': 'when', 'value': 'not-a-date'}]}, None, _ctx(type_map={'when': 'date'}))

        assert any("not a valid date" in error for error in errors)

    def test_radio_rejects_unknown_option(self) -> None:
        """An unknown radio value rejects the object; options are not extended."""
        errors = normalize_and_validate_object(
            {'fields': [{'name': 'mode', 'value': 'off'}]}, None,
            _ctx(type_map={'mode': 'radio'}, field_options={'mode': {'on'}}))

        assert any("not an allowed option" in error for error in errors)

    def test_select_unknown_value_extends_the_options(self) -> None:
        """An unknown select value is accepted and recorded as a new option to persist."""
        options = {'kind': {'a'}}
        new_options: dict = {}
        obj = {'fields': [{'name': 'kind', 'value': 'c'}]}

        errors = normalize_and_validate_object(
            obj, None, _ctx(type_map={'kind': 'select'}, field_options=options, new_select_options=new_options))

        assert not errors
        assert 'c' in options['kind']          # recognised for the rest of the batch
        assert new_options == {'kind': ['c']}   # recorded for persistence

    def test_empty_value_is_not_type_checked(self) -> None:
        """An empty value is skipped by the suitability check (handled by the required rule)."""
        obj = {'fields': [{'name': 'port', 'value': ''}]}

        assert not normalize_and_validate_object(obj, None, _ctx(type_map={'port': 'number'}))

    def test_number_rejects_non_scalar_value(self) -> None:
        """A non-scalar (e.g. list) value in a number field is rejected."""
        errors = normalize_and_validate_object(
            {'fields': [{'name': 'port', 'value': [1, 2]}]}, None, _ctx(type_map={'port': 'number'}))

        assert any("not a valid number" in error for error in errors)

    def test_reference_rejects_float(self) -> None:
        """A non-integer (float) reference value is rejected (ids must be integers)."""
        errors = normalize_and_validate_object(
            {'fields': [{'name': 'owner', 'value': 3.14}]}, None,
            _ctx(type_map={'owner': 'ref'}, clearable={'owner'}))

        assert any("not a valid reference id" in error for error in errors)

    def test_number_rejects_boolean(self) -> None:
        """A boolean is not a valid number (bool is excluded)."""
        errors = normalize_and_validate_object(
            {'fields': [{'name': 'port', 'value': True}]}, None, _ctx(type_map={'port': 'number'}))

        assert any("not a valid number" in error for error in errors)

    def test_reference_rejects_boolean(self) -> None:
        """A boolean is not a valid reference id (bool is excluded)."""
        errors = normalize_and_validate_object(
            {'fields': [{'name': 'owner', 'value': True}]}, None,
            _ctx(type_map={'owner': 'ref'}, clearable={'owner'}))

        assert any("not a valid reference id" in error for error in errors)

    def test_reference_accepts_integer_value_then_clears(self) -> None:
        """An integer (not string) reference value is valid and then cleared."""
        obj = {'fields': [{'name': 'owner', 'value': 7}]}

        assert not normalize_and_validate_object(
            obj, None, _ctx(type_map={'owner': 'ref'}, clearable={'owner'}))
        assert obj['fields'][0]['value'] is None

    def test_text_value_is_kept_unchanged(self) -> None:
        """A text field's value passes the suitability check unchanged."""
        obj = {'fields': [{'name': 'label', 'value': 'hello'}]}

        assert not normalize_and_validate_object(obj, None, _ctx(type_map={'label': 'text'}))
        assert obj['fields'][0]['value'] == 'hello'

    def test_checkbox_coerced_and_invalid_rejected(self) -> None:
        """A checkbox value is coerced to bool; an unrecognised one is rejected."""
        obj = {'fields': [{'name': 'flag', 'value': 'yes'}]}
        assert not normalize_and_validate_object(obj, None, _ctx(type_map={'flag': 'checkbox'}))
        assert obj['fields'][0]['value'] is True

        errors = normalize_and_validate_object(
            {'fields': [{'name': 'flag', 'value': 'maybe'}]}, None, _ctx(type_map={'flag': 'checkbox'}))
        assert any("not a valid boolean" in error for error in errors)

    def test_select_known_value_is_not_added(self) -> None:
        """A select value already in the options is accepted without extending the type."""
        options = {'kind': {'a', 'b'}}
        new_options: dict = {}
        obj = {'fields': [{'name': 'kind', 'value': 'a'}]}

        assert not normalize_and_validate_object(
            obj, None, _ctx(type_map={'kind': 'select'}, field_options=options, new_select_options=new_options))
        assert not new_options  # nothing new to persist

    def test_radio_known_value_is_allowed(self) -> None:
        """A radio value that matches an option is accepted."""
        obj = {'fields': [{'name': 'mode', 'value': 'on'}]}

        assert not normalize_and_validate_object(
            obj, None, _ctx(type_map={'mode': 'radio'}, field_options={'mode': {'on', 'off'}}))


class TestApplyNewSelectOptions:
    """apply_new_select_options extends the type's select fields with the imported values."""

    def test_adds_missing_options_only(self) -> None:
        """Only values not already present are appended; fields with no new values are skipped."""
        kind = {'name': 'kind', 'type': 'select', 'extras': {'options': [{'name': 'a', 'label': 'a'}]}}
        other = {'name': 'other', 'type': 'select', 'extras': {'options': [{'name': 'z', 'label': 'z'}]}}
        type_instance = MagicMock()
        type_instance.get_fields.return_value = [kind, other]

        # only 'kind' has new values; 'other' is skipped (no entry in the map)
        apply_new_select_options(type_instance, {'kind': ['a', 'b']})

        assert kind['extras']['options'] == [{'name': 'a', 'label': 'a'}, {'name': 'b', 'label': 'b'}]
        assert other['extras']['options'] == [{'name': 'z', 'label': 'z'}]  # untouched


class TestBackfillFromType:
    """Non-provided fields are backfilled from the type default (top-level + within provided MDS rows)."""

    def test_backfills_missing_top_level_field_with_default(self) -> None:
        """A top-level type field the object did not provide is added with its default + stamped type."""
        obj = {'fields': [{'name': 'host', 'value': 'h'}]}
        context = _ctx(type_map={'host': 'text', 'note': 'text'}, top_defaults={'host': '', 'note': 'n/a'})

        assert not normalize_and_validate_object(obj, None, context)
        by_name = {field['name']: field for field in obj['fields']}
        assert by_name['note']['value'] == 'n/a'      # backfilled from the default
        assert by_name['note']['type'] == 'text'      # and its type was stamped
        assert by_name['host']['value'] == 'h'         # provided value untouched

    def test_backfills_missing_mds_row_field(self) -> None:
        """A section field absent from a provided MDS row is backfilled from the type default."""
        obj = {'fields': [], 'multi_data_sections': [
            {'section_id': 'nics', 'values': [{'multi_data_id': 1, 'data': [{'name': 'nic', 'value': 'eth0'}]}]},
        ]}
        context = _ctx(type_map={'nic': 'text', 'speed': 'text'},
                       mds_defaults={'nics': {'nic': None, 'speed': '1G'}})

        assert not normalize_and_validate_object(obj, None, context)
        row = {entry['name']: entry['value'] for entry in obj['multi_data_sections'][0]['values'][0]['data']}
        assert row == {'nic': 'eth0', 'speed': '1G'}

    def test_backfilled_required_with_empty_default_is_rejected(self) -> None:
        """A required field not provided and backfilled with an empty default fails the required check."""
        context = _ctx(type_map={'host': 'text'}, required_top={'host'}, top_defaults={'host': ''})

        errors = normalize_and_validate_object({'fields': []}, None, context)

        assert "Missing value for required field(s): ['host']" in errors

    def test_backfilled_required_with_nonempty_default_passes(self) -> None:
        """A required field not provided but with a non-empty type default is satisfied by the backfill."""
        context = _ctx(type_map={'host': 'text'}, required_top={'host'}, top_defaults={'host': 'default-host'})

        assert not normalize_and_validate_object({'fields': []}, None, context)


class TestRequiredFieldsRule:
    """A required field left without a value rejects the object (top-level and per MDS row)."""

    def test_missing_top_level_required_value_is_rejected(self) -> None:
        """A required top-level field with an empty value is rejected."""
        obj = {'fields': [{'name': 'host', 'value': ''}]}

        errors = normalize_and_validate_object(obj, None, _ctx(type_map={'host': 'text'}, required_top={'host'}))

        assert "Missing value for required field(s): ['host']" in errors

    def test_absent_top_level_required_field_is_rejected(self) -> None:
        """A required top-level field not present at all is rejected."""
        errors = normalize_and_validate_object({'fields': []}, None, _ctx(required_top={'host'}))

        assert "Missing value for required field(s): ['host']" in errors

    def test_required_value_present_passes(self) -> None:
        """A required field with a value passes; 0 counts as a value."""
        obj = {'fields': [{'name': 'host', 'value': 'h'}, {'name': 'port', 'value': 0}]}
        context = _ctx(type_map={'host': 'text', 'port': 'number'}, required_top={'host', 'port'})

        assert not normalize_and_validate_object(obj, None, context)

    def test_missing_required_mds_value_in_a_row_is_rejected(self) -> None:
        """An empty required field in any MDS row rejects the object."""
        obj = {'fields': [], 'multi_data_sections': [
            {'section_id': 'nics', 'values': [
                {'multi_data_id': 1, 'data': [{'name': 'nic', 'value': 'eth0'}]},
                {'multi_data_id': 2, 'data': [{'name': 'nic', 'value': ''}]},
            ]},
        ]}

        errors = normalize_and_validate_object(
            obj, None, _ctx(type_map={'nic': 'text'}, required_mds={'nics': {'nic'}}))

        assert "Missing value for required field(s) ['nic'] in multi-data section 'nics'" in errors

    def test_all_mds_rows_with_values_pass(self) -> None:
        """When every row has the required value the object passes."""
        obj = {'fields': [], 'multi_data_sections': [
            {'section_id': 'nics', 'values': [
                {'multi_data_id': 1, 'data': [{'name': 'nic', 'value': 'eth0'}]},
            ]},
        ]}

        assert not normalize_and_validate_object(
            obj, None, _ctx(type_map={'nic': 'text'}, required_mds={'nics': {'nic'}}))
