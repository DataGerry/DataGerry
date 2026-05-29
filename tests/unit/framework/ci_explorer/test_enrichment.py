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
Unit tests for cmdb.framework.ci_explorer.enrichment

Trivial helper ``collect_ref_field_names`` (single comprehension) is skipped per
feedback_skip_trivial_methods. The two batched-lookup helpers are exercised with mock
managers so the unit tests stay fast and DB-independent
"""
from typing import Any
from unittest.mock import MagicMock

from cmdb.framework.ci_explorer.enrichment import (
    build_location_name_lookup,
    build_summary_lookup,
    collect_ref_and_location_ids,
    flatten_object_fields,
)
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_WITH_REF: int = 10
TYPE_WITH_LOCATION: int = 11
TYPE_NO_REFS: int = 12

TYPES_BY_ID: dict[int, dict[str, Any]] = {
    TYPE_WITH_REF: {
        'public_id': TYPE_WITH_REF,
        'fields': [
            {'name': 'owner', 'type': 'ref'},
            {'name': 'name', 'type': 'text'},
        ],
    },
    TYPE_WITH_LOCATION: {
        'public_id': TYPE_WITH_LOCATION,
        'fields': [
            {'name': 'dg_location', 'type': 'location'},
            {'name': 'name', 'type': 'text'},
        ],
    },
    TYPE_NO_REFS: {
        'public_id': TYPE_NO_REFS,
        'fields': [
            {'name': 'name', 'type': 'text'},
        ],
    },
}


# -------------------------------------------------------------------------------------------------------------------- #
#                                       collect_ref_and_location_ids                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_collect_ref_and_location_ids_returns_empty_for_empty_input() -> None:
    """No objects → no ids in either bucket"""
    ref_ids, loc_ids = collect_ref_and_location_ids([], TYPES_BY_ID)

    assert ref_ids == set()
    assert loc_ids == set()


def test_collect_ref_and_location_ids_skips_objects_with_unknown_type() -> None:
    """Objects whose type_id is absent from types_by_id contribute nothing"""
    objects = [{'type_id': 9999, 'fields': [{'name': 'owner', 'value': 42}]}]

    ref_ids, loc_ids = collect_ref_and_location_ids(objects, TYPES_BY_ID)

    assert ref_ids == set()
    assert loc_ids == set()


def test_collect_ref_and_location_ids_collects_int_ref_field_value() -> None:
    """A ref-typed field with an int value contributes to ref_ids"""
    objects = [{'type_id': TYPE_WITH_REF, 'fields': [{'name': 'owner', 'value': 42}]}]

    ref_ids, loc_ids = collect_ref_and_location_ids(objects, TYPES_BY_ID)

    assert ref_ids == {42}
    assert loc_ids == set()


def test_collect_ref_and_location_ids_collects_dg_location_value() -> None:
    """A dg_location field with an int value contributes to loc_ids"""
    objects = [{'type_id': TYPE_WITH_LOCATION, 'fields': [{'name': 'dg_location', 'value': 7}]}]

    ref_ids, loc_ids = collect_ref_and_location_ids(objects, TYPES_BY_ID)

    assert ref_ids == set()
    assert loc_ids == {7}


def test_collect_ref_and_location_ids_skips_non_int_values() -> None:
    """A ref-typed field whose value is a string (already flattened or invalid) is skipped"""
    objects = [{'type_id': TYPE_WITH_REF, 'fields': [{'name': 'owner', 'value': 'already-a-string'}]}]

    ref_ids, loc_ids = collect_ref_and_location_ids(objects, TYPES_BY_ID)

    assert ref_ids == set()
    assert loc_ids == set()


def test_collect_ref_and_location_ids_handles_mixed_objects_and_dedupes() -> None:
    """Mixed batch contributes both buckets; same id from multiple objects collapses to one"""
    objects = [
        {'type_id': TYPE_WITH_REF, 'fields': [{'name': 'owner', 'value': 42}]},
        {'type_id': TYPE_WITH_REF, 'fields': [{'name': 'owner', 'value': 42}]},
        {'type_id': TYPE_WITH_LOCATION, 'fields': [{'name': 'dg_location', 'value': 7}]},
        {'type_id': TYPE_NO_REFS, 'fields': [{'name': 'name', 'value': 'no-refs'}]},
    ]

    ref_ids, loc_ids = collect_ref_and_location_ids(objects, TYPES_BY_ID)

    assert ref_ids == {42}
    assert loc_ids == {7}


# -------------------------------------------------------------------------------------------------------------------- #
#                                              build_summary_lookup                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_summary_lookup_short_circuits_empty_set_without_db_call() -> None:
    """Empty input never touches the manager"""
    manager = MagicMock()

    assert build_summary_lookup(manager, set()) == {}
    manager.get_summary_lines_lookup.assert_not_called()


def test_build_summary_lookup_delegates_to_get_summary_lines_lookup() -> None:
    """Non-empty input is passed through as a list to the batched manager API"""
    manager = MagicMock()
    manager.get_summary_lines_lookup.return_value = {42: 'Server: srv-1', 43: 'Server: srv-2'}

    result = build_summary_lookup(manager, {42, 43})

    assert result == {42: 'Server: srv-1', 43: 'Server: srv-2'}
    manager.get_summary_lines_lookup.assert_called_once()
    passed = manager.get_summary_lines_lookup.call_args[0][0]
    assert set(passed) == {42, 43}


# -------------------------------------------------------------------------------------------------------------------- #
#                                          build_location_name_lookup                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_location_name_lookup_short_circuits_empty_set_without_db_call() -> None:
    """Empty input never touches the manager"""
    manager = MagicMock()

    assert build_location_name_lookup(manager, set()) == {}
    manager.find.assert_not_called()


def test_build_location_name_lookup_maps_public_id_to_name() -> None:
    """The result is a {public_id: name} dict built from the find() return"""
    manager = MagicMock()
    manager.find.return_value = [
        {'public_id': 1001, 'name': 'eu-west'},
        {'public_id': 1002, 'name': 'us-east'},
    ]

    result = build_location_name_lookup(manager, {1001, 1002})

    assert result == {1001: 'eu-west', 1002: 'us-east'}
    criteria = manager.find.call_args.kwargs['criteria']
    assert set(criteria['public_id']['$in']) == {1001, 1002}


def test_build_location_name_lookup_drops_documents_with_invalid_shape() -> None:
    """Docs missing a name or a non-int public_id are silently dropped"""
    manager = MagicMock()
    manager.find.return_value = [
        {'public_id': 1001, 'name': 'eu-west'},
        {'public_id': 'not-an-int', 'name': 'malformed'},
        {'public_id': 1003},  # no name
    ]

    result = build_location_name_lookup(manager, {1001, 1003})

    assert result == {1001: 'eu-west'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                             flatten_object_fields                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_flatten_object_fields_returns_copy_leaving_original_untouched() -> None:
    """The input object is not mutated; only the returned copy carries the flattened fields"""
    original = {'type_id': TYPE_WITH_REF, 'fields': [{'name': 'owner', 'value': 42}]}

    result = flatten_object_fields(original, TYPES_BY_ID, {42: 'Server: srv-1'}, {})

    assert original['fields'][0]['value'] == 42, "original must not be mutated"
    assert result['fields'][0]['value'] == 'Server: srv-1'
    assert result is not original


def test_flatten_object_fields_replaces_ref_value_with_summary_line() -> None:
    """A ref field whose target is in the summary lookup is replaced by the summary line"""
    obj = {'type_id': TYPE_WITH_REF, 'fields': [{'name': 'owner', 'value': 42}]}

    result = flatten_object_fields(obj, TYPES_BY_ID, {42: 'Server: srv-1'}, {})

    assert result['fields'][0]['value'] == 'Server: srv-1'


def test_flatten_object_fields_keeps_raw_int_when_summary_missing() -> None:
    """When the referenced object is unresolvable, the raw int passes through (no placeholder)"""
    obj = {'type_id': TYPE_WITH_REF, 'fields': [{'name': 'owner', 'value': 999}]}

    result = flatten_object_fields(obj, TYPES_BY_ID, {}, {})

    assert result['fields'][0]['value'] == 999


def test_flatten_object_fields_replaces_dg_location_with_name() -> None:
    """A dg_location field whose id is in the location lookup is replaced by the location name"""
    obj = {'type_id': TYPE_WITH_LOCATION, 'fields': [{'name': 'dg_location', 'value': 7}]}

    result = flatten_object_fields(obj, TYPES_BY_ID, {}, {7: 'eu-west'})

    assert result['fields'][0]['value'] == 'eu-west'


def test_flatten_object_fields_passes_through_non_int_values_unchanged() -> None:
    """A ref field whose value is already a string (or anything non-int) is not touched"""
    obj = {'type_id': TYPE_WITH_REF, 'fields': [{'name': 'owner', 'value': 'already-flat'}]}

    result = flatten_object_fields(obj, TYPES_BY_ID, {42: 'wrong'}, {})

    assert result['fields'][0]['value'] == 'already-flat'


def test_flatten_object_fields_handles_unknown_type_id_with_no_flattening() -> None:
    """Objects whose type isn't in types_by_id pass their fields through unchanged"""
    obj = {'type_id': 9999, 'fields': [{'name': 'owner', 'value': 42}]}

    result = flatten_object_fields(obj, TYPES_BY_ID, {42: 'Server: srv-1'}, {})

    assert result['fields'][0]['value'] == 42
