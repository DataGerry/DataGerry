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
Unit tests for cmdb.framework.ipam.supernet_membership

Covers the pure helpers (normalize_subnet_id_list, diff_missing_ids), the DB-touching
single-step helpers (assert_supernet_exists, load_assigned_subnets, clear_supernet_ref),
and the unassign_subnets_from_supernet orchestrator. Mongo query shapes are pinned via
assert_called_once_with so any future relaxation fails loudly - the clear write filter is
checked in particular detail because it carries the TOCTOU-safety guarantee. Flask aborts
are exercised via pytest.raises(HTTPException) without needing a request context. The
orchestrator's helpers are patched at the module path so each orchestrator test verifies
orchestration in isolation; each helper has its own dedicated tests in this file
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException, NotFound

from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import SubnetField, IpamUnassignKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.ipam.supernet_membership import (
    assert_supernet_exists,
    clear_supernet_ref,
    diff_missing_ids,
    load_assigned_subnets,
    normalize_subnet_id_list,
    unassign_subnets_from_supernet,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUPERNET_TYPE_ID: int = 10
SUBNET_TYPE_ID: int = 11
SUPERNET_OBJECT_ID: int = 100
SUBNET_OBJECT_ID_A: int = 201
SUBNET_OBJECT_ID_B: int = 202
SUBNET_OBJECT_ID_C: int = 203

PATH: str = 'cmdb.framework.ipam.supernet_membership'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    FIXTURES                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_cmdb_object(public_id: int, type_id: int) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc with the given public_id and type_id."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: type_id,
        CmdbObjectKey.FIELDS: [],
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                            normalize_subnet_id_list                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_normalize_subnet_id_list_accepts_ordered_unique_int_list() -> None:
    """A clean integer list passes through unchanged in input order"""
    result = normalize_subnet_id_list([SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B, SUBNET_OBJECT_ID_C])

    assert result == [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B, SUBNET_OBJECT_ID_C]


def test_normalize_subnet_id_list_collapses_duplicates_preserving_first_occurrence_order() -> None:
    """Duplicate ids are dropped while the order of the first occurrence is preserved"""
    result = normalize_subnet_id_list([
        SUBNET_OBJECT_ID_B,
        SUBNET_OBJECT_ID_A,
        SUBNET_OBJECT_ID_B,
        SUBNET_OBJECT_ID_C,
        SUBNET_OBJECT_ID_A,
    ])

    assert result == [SUBNET_OBJECT_ID_B, SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_C]


@pytest.mark.parametrize('raw', [None, '', 'subnet-ids', 42, {'subnet_ids': [1]}])
def test_normalize_subnet_id_list_aborts_400_when_payload_is_not_a_list(raw: Any) -> None:
    """A non-list payload (None, str, int, dict) aborts 400 without further parsing"""
    with pytest.raises(HTTPException) as exc_info:
        normalize_subnet_id_list(raw)

    assert exc_info.value.code == 400


def test_normalize_subnet_id_list_aborts_400_for_empty_list() -> None:
    """An empty list is rejected: the route is a no-op if nothing is selected, so the caller is wrong"""
    with pytest.raises(HTTPException) as exc_info:
        normalize_subnet_id_list([])

    assert exc_info.value.code == 400


@pytest.mark.parametrize('entry', ['12', 1.5, None, [1], {'public_id': 1}])
def test_normalize_subnet_id_list_aborts_400_for_non_integer_entries(entry: Any) -> None:
    """A non-integer entry (str, float, None, list, dict) aborts 400"""
    with pytest.raises(HTTPException) as exc_info:
        normalize_subnet_id_list([SUBNET_OBJECT_ID_A, entry])

    assert exc_info.value.code == 400


@pytest.mark.parametrize('entry', [True, False])
def test_normalize_subnet_id_list_aborts_400_for_boolean_entries(entry: bool) -> None:
    """Booleans subclass int in Python but must be rejected so True does not silently target id 1"""
    with pytest.raises(HTTPException) as exc_info:
        normalize_subnet_id_list([entry])

    assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                               diff_missing_ids                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_diff_missing_ids_returns_empty_when_every_id_is_present() -> None:
    """When every requested id is present in the result set, nothing is missing"""
    requested = [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B]
    present = [
        _make_cmdb_object(SUBNET_OBJECT_ID_A, SUBNET_TYPE_ID),
        _make_cmdb_object(SUBNET_OBJECT_ID_B, SUBNET_TYPE_ID),
    ]

    assert diff_missing_ids(requested, present) == []


def test_diff_missing_ids_returns_full_request_when_present_is_empty() -> None:
    """An empty result set means every requested id is missing"""
    requested = [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B]

    assert diff_missing_ids(requested, []) == requested


def test_diff_missing_ids_returns_only_unmatched_ids_preserving_input_order() -> None:
    """Partial overlap: only the unmatched ids come back, in caller order"""
    requested = [SUBNET_OBJECT_ID_C, SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B]
    present = [_make_cmdb_object(SUBNET_OBJECT_ID_A, SUBNET_TYPE_ID)]

    assert diff_missing_ids(requested, present) == [SUBNET_OBJECT_ID_C, SUBNET_OBJECT_ID_B]


def test_diff_missing_ids_treats_docs_without_public_id_as_missing() -> None:
    """A doc missing its public_id cannot satisfy any requested id"""
    requested = [SUBNET_OBJECT_ID_A]
    present = [{CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID, CmdbObjectKey.FIELDS: []}]

    assert diff_missing_ids(requested, present) == [SUBNET_OBJECT_ID_A]


# -------------------------------------------------------------------------------------------------------------------- #
#                                            assert_supernet_exists                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_assert_supernet_exists_aborts_400_when_supernet_type_not_defined() -> None:
    """No SUPERNET CmdbType → HTTP 400; no object query is issued"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        assert_supernet_exists(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    assert exc_info.value.code == 400
    objects_manager.find_objects.assert_not_called()


def test_assert_supernet_exists_aborts_404_when_object_not_found() -> None:
    """find_objects returns empty → HTTP 404"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    with pytest.raises(HTTPException) as exc_info:
        assert_supernet_exists(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    assert exc_info.value.code == 404


def test_assert_supernet_exists_aborts_400_when_object_is_not_a_supernet() -> None:
    """Found object exists but has a different type_id → HTTP 400"""
    wrong_type_doc = _make_cmdb_object(SUPERNET_OBJECT_ID, type_id=SUPERNET_TYPE_ID + 1)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [wrong_type_doc]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    with pytest.raises(HTTPException) as exc_info:
        assert_supernet_exists(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    assert exc_info.value.code == 400


def test_assert_supernet_exists_returns_none_on_happy_path() -> None:
    """A correct SUPERNET object id returns None (no abort) and queries are well-shaped"""
    supernet_doc = _make_cmdb_object(SUPERNET_OBJECT_ID, SUPERNET_TYPE_ID)
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [supernet_doc]
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUPERNET_TYPE_ID}

    assert_supernet_exists(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    objects_manager.find_objects.assert_called_once_with(
        {CmdbObjectKey.PUBLIC_ID: SUPERNET_OBJECT_ID}, as_dict=True,
    )
    types_manager.get_one_by.assert_called_once_with({TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUPERNET})


# -------------------------------------------------------------------------------------------------------------------- #
#                                             load_assigned_subnets                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_assigned_subnets_returns_empty_when_subnet_type_not_defined() -> None:
    """No SUBNET CmdbType → empty list, no DB query for objects"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    result = load_assigned_subnets(
        objects_manager, types_manager, SUPERNET_OBJECT_ID, [SUBNET_OBJECT_ID_A],
    )

    assert result == []
    objects_manager.find_objects.assert_not_called()


def test_load_assigned_subnets_returns_manager_result_when_type_defined() -> None:
    """SUBNET type defined → result of objects_manager.find_objects is returned verbatim"""
    docs = [_make_cmdb_object(SUBNET_OBJECT_ID_A, SUBNET_TYPE_ID)]
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = docs
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    result = load_assigned_subnets(
        objects_manager, types_manager, SUPERNET_OBJECT_ID, [SUBNET_OBJECT_ID_A],
    )

    assert result is docs


def test_load_assigned_subnets_queries_with_public_id_type_and_supernet_ref_filter() -> None:
    """Mongo filter pins public_id $in, TYPE_ID, plus FIELDS $elemMatch on PARENT_SUPERNET/value"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    subnet_ids = [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B]
    load_assigned_subnets(objects_manager, types_manager, SUPERNET_OBJECT_ID, subnet_ids)

    objects_manager.find_objects.assert_called_once_with(
        {
            CmdbObjectKey.PUBLIC_ID: {'$in': subnet_ids},
            CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID,
            CmdbObjectKey.FIELDS: {
                '$elemMatch': {
                    CmdbObjectFieldKey.NAME: SubnetField.PARENT_SUPERNET,
                    CmdbObjectFieldKey.VALUE: SUPERNET_OBJECT_ID,
                },
            },
        },
        as_dict=True,
    )
    types_manager.get_one_by.assert_called_once_with({TypeSchemaKey.SPECIAL_TYPE: SpecialType.SUBNET})


# -------------------------------------------------------------------------------------------------------------------- #
#                                              clear_supernet_ref                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_clear_supernet_ref_issues_one_update_many_raw_call() -> None:
    """The clear is a single Mongo write, not one-update-per-id"""
    objects_manager = MagicMock()

    clear_supernet_ref(
        objects_manager,
        [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B],
        SUPERNET_OBJECT_ID,
    )

    assert objects_manager.update_many_raw.call_count == 1


def test_clear_supernet_ref_filter_pins_ids_and_current_supernet_value() -> None:
    """Doc filter requires public_id $in AND dg-supernet-ref currently equals supernet id (TOCTOU-safe)"""
    objects_manager = MagicMock()
    subnet_ids = [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B]

    clear_supernet_ref(objects_manager, subnet_ids, SUPERNET_OBJECT_ID)

    call_kwargs = objects_manager.update_many_raw.call_args.kwargs
    assert call_kwargs['filter_query'] == {
        CmdbObjectKey.PUBLIC_ID: {'$in': subnet_ids},
        CmdbObjectKey.FIELDS: {
            '$elemMatch': {
                CmdbObjectFieldKey.NAME: SubnetField.PARENT_SUPERNET,
                CmdbObjectFieldKey.VALUE: SUPERNET_OBJECT_ID,
            },
        },
    }


def test_clear_supernet_ref_update_sets_value_to_none() -> None:
    """The update sets the targeted field entry's value to None (not '' or missing)"""
    objects_manager = MagicMock()

    clear_supernet_ref(objects_manager, [SUBNET_OBJECT_ID_A], SUPERNET_OBJECT_ID)

    call_kwargs = objects_manager.update_many_raw.call_args.kwargs
    assert call_kwargs['update'] == {'$set': {'fields.$[f].value': None}}


def test_clear_supernet_ref_array_filter_restricts_to_supernet_ref_field_at_current_value() -> None:
    """Array filter pins both name and current value so only the dg-supernet-ref entry is cleared"""
    objects_manager = MagicMock()

    clear_supernet_ref(objects_manager, [SUBNET_OBJECT_ID_A], SUPERNET_OBJECT_ID)

    call_kwargs = objects_manager.update_many_raw.call_args.kwargs
    assert call_kwargs['array_filters'] == [{
        'f.name': SubnetField.PARENT_SUPERNET,
        'f.value': SUPERNET_OBJECT_ID,
    }]


# -------------------------------------------------------------------------------------------------------------------- #
#                                       unassign_subnets_from_supernet                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_unassign_subnets_from_supernet_returns_dedup_ids_and_count_on_happy_path() -> None:
    """Happy path returns the deduped subnet_ids and the matching unassigned_count"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    assigned_docs = [
        _make_cmdb_object(SUBNET_OBJECT_ID_A, SUBNET_TYPE_ID),
        _make_cmdb_object(SUBNET_OBJECT_ID_B, SUBNET_TYPE_ID),
    ]

    with patch(f'{PATH}.assert_supernet_exists') as assert_mock, \
         patch(f'{PATH}.load_assigned_subnets', return_value=assigned_docs) as load_mock, \
         patch(f'{PATH}.clear_supernet_ref') as clear_mock:
        result = unassign_subnets_from_supernet(
            objects_manager,
            types_manager,
            SUPERNET_OBJECT_ID,
            [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B, SUBNET_OBJECT_ID_A],
        )

    assert result == {
        IpamUnassignKey.SUBNET_IDS: [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B],
        IpamUnassignKey.UNASSIGNED_COUNT: 2,
    }
    assert_mock.assert_called_once_with(objects_manager, types_manager, SUPERNET_OBJECT_ID)
    load_mock.assert_called_once_with(
        objects_manager, types_manager, SUPERNET_OBJECT_ID,
        [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B],
    )
    clear_mock.assert_called_once_with(
        objects_manager, [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B], SUPERNET_OBJECT_ID,
    )


def test_unassign_subnets_from_supernet_propagates_payload_normalization_aborts() -> None:
    """An invalid payload aborts before any DB call (no supernet check, no load, no clear)"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    with patch(f'{PATH}.assert_supernet_exists') as assert_mock, \
         patch(f'{PATH}.load_assigned_subnets') as load_mock, \
         patch(f'{PATH}.clear_supernet_ref') as clear_mock, \
         pytest.raises(HTTPException) as exc_info:
        unassign_subnets_from_supernet(objects_manager, types_manager, SUPERNET_OBJECT_ID, None)

    assert exc_info.value.code == 400
    assert_mock.assert_not_called()
    load_mock.assert_not_called()
    clear_mock.assert_not_called()


def test_unassign_subnets_from_supernet_propagates_supernet_assertion_aborts() -> None:
    """A supernet-existence abort surfaces unchanged and no load / no clear is issued"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    with patch(f'{PATH}.assert_supernet_exists', side_effect=NotFound('not found')), \
         patch(f'{PATH}.load_assigned_subnets') as load_mock, \
         patch(f'{PATH}.clear_supernet_ref') as clear_mock, \
         pytest.raises(HTTPException) as exc_info:
        unassign_subnets_from_supernet(
            objects_manager, types_manager, SUPERNET_OBJECT_ID, [SUBNET_OBJECT_ID_A],
        )

    assert exc_info.value.code == 404
    load_mock.assert_not_called()
    clear_mock.assert_not_called()


def test_unassign_subnets_from_supernet_aborts_400_when_any_id_is_unassignable() -> None:
    """Validate-all-or-nothing: any unassignable id aborts 400 and clear_supernet_ref is NOT called"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    assigned_docs = [_make_cmdb_object(SUBNET_OBJECT_ID_A, SUBNET_TYPE_ID)]

    with patch(f'{PATH}.assert_supernet_exists'), \
         patch(f'{PATH}.load_assigned_subnets', return_value=assigned_docs), \
         patch(f'{PATH}.clear_supernet_ref') as clear_mock, \
         pytest.raises(HTTPException) as exc_info:
        unassign_subnets_from_supernet(
            objects_manager,
            types_manager,
            SUPERNET_OBJECT_ID,
            [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B],
        )

    assert exc_info.value.code == 400
    clear_mock.assert_not_called()
