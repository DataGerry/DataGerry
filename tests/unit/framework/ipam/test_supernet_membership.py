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
from werkzeug.exceptions import Forbidden, HTTPException, NotFound

from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    IpamUnassignKey,
    IpamUnassignLimits,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.acl_constants import AclKey
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.ipam.supernet_membership import (
    assert_supernet_exists,
    clear_supernet_ref,
    diff_missing_ids,
    load_assigned_subnets,
    normalize_subnet_id_list,
    unassign_subnets_from_supernet,
    verify_subnet_write_access,
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


# -------------------------------------------------------------------------------------------------------------------- #
#                                            verify_subnet_write_access                                                #
# -------------------------------------------------------------------------------------------------------------------- #
GROUP_ID: int = 7


def _subnet_type_doc(acl: dict[str, Any] | None = None) -> dict[str, Any]:
    """The SUBNET CmdbType document as the resolver hands it over, optionally carrying an ACL."""
    doc: dict[str, Any] = {CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}

    if acl is not None:
        doc[TypeSchemaKey.ACL.value] = acl

    return doc


def _acl(permissions: list[str], activated: bool = True) -> dict[str, Any]:
    """An ACL granting GROUP_ID exactly `permissions`."""
    return {
        AclKey.ACTIVATED.value: activated,
        AclKey.GROUPS.value: {AclKey.INCLUDES.value: {str(GROUP_ID): permissions}},
    }


def _user() -> MagicMock:
    """A CmdbUser stand-in - only `group_id` is read by the ACL decision."""
    user = MagicMock()
    user.group_id = GROUP_ID

    return user


def test_verify_subnet_write_access_without_a_user_asks_nothing() -> None:
    """
    An internal caller with no request context skips the check

    Not merely "is permitted": no type is read either, because there is no group to decide against.
    """
    types_manager = MagicMock()

    with patch(f'{PATH}.resolve_special_type_document') as resolve_mock:
        verify_subnet_write_access(types_manager, None)

    resolve_mock.assert_not_called()


def test_verify_subnet_write_access_permits_when_the_acl_grants_update() -> None:
    """The ordinary case: the caller's group holds UPDATE on the SUBNET type."""
    types_manager = MagicMock()
    doc = _subnet_type_doc(_acl([AccessControlPermission.UPDATE.value]))

    with patch(f'{PATH}.resolve_special_type_document', return_value=doc):
        verify_subnet_write_access(types_manager, _user())


def test_verify_subnet_write_access_aborts_403_when_the_acl_denies_update() -> None:
    """
    The finding this closes

    READ alone is not enough - the detach is a write, so the question asked must be UPDATE.
    """
    types_manager = MagicMock()
    doc = _subnet_type_doc(_acl([AccessControlPermission.READ.value]))

    with patch(f'{PATH}.resolve_special_type_document', return_value=doc), \
         pytest.raises(HTTPException) as exc_info:
        verify_subnet_write_access(types_manager, _user())

    assert exc_info.value.code == 403


def test_verify_subnet_write_access_permits_when_the_acl_is_deactivated() -> None:
    """Access control is opt-in: a stored but switched-off ACL permits everything."""
    types_manager = MagicMock()
    doc = _subnet_type_doc(_acl([], activated=False))

    with patch(f'{PATH}.resolve_special_type_document', return_value=doc):
        verify_subnet_write_access(types_manager, _user())


def test_verify_subnet_write_access_permits_a_type_without_an_acl() -> None:
    """Most installations activate an ACL on few types or none."""
    types_manager = MagicMock()

    with patch(f'{PATH}.resolve_special_type_document', return_value=_subnet_type_doc()):
        verify_subnet_write_access(types_manager, _user())


def test_verify_subnet_write_access_permits_when_no_subnet_type_exists() -> None:
    """
    A virgin install has nothing to check against

    The downstream membership query returns nothing in that case, so the request fails on its own
    terms (400, ids not assignable) rather than being reported as a permission problem.
    """
    types_manager = MagicMock()

    with patch(f'{PATH}.resolve_special_type_document', return_value=None):
        verify_subnet_write_access(types_manager, _user())


# -------------------------------------------------------------------------------------------------------------------- #
#                                    the orchestrator's ACL check and batch cap                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_unassign_checks_access_before_touching_the_membership_query() -> None:
    """
    Order matters: a refused caller must not learn which ids are assigned

    The ACL check also has to run before `clear_supernet_ref`, which is the whole point.
    """
    objects_manager = MagicMock()
    types_manager = MagicMock()
    user = _user()

    with patch(f'{PATH}.assert_supernet_exists'), \
         patch(f'{PATH}.verify_subnet_write_access', side_effect=Forbidden('denied')) as verify_mock, \
         patch(f'{PATH}.load_assigned_subnets') as load_mock, \
         patch(f'{PATH}.clear_supernet_ref') as clear_mock, \
         pytest.raises(HTTPException) as exc_info:
        unassign_subnets_from_supernet(
            objects_manager, types_manager, SUPERNET_OBJECT_ID, [SUBNET_OBJECT_ID_A], request_user=user,
        )

    assert exc_info.value.code == 403
    verify_mock.assert_called_once_with(types_manager, user)
    load_mock.assert_not_called()
    clear_mock.assert_not_called()


def test_unassign_forwards_the_request_user_to_the_access_check() -> None:
    """A permitted caller still reaches the write, and the user is the one that was passed in."""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    user = _user()
    assigned_docs = [_make_cmdb_object(SUBNET_OBJECT_ID_A, SUBNET_TYPE_ID)]

    with patch(f'{PATH}.assert_supernet_exists'), \
         patch(f'{PATH}.verify_subnet_write_access') as verify_mock, \
         patch(f'{PATH}.load_assigned_subnets', return_value=assigned_docs), \
         patch(f'{PATH}.clear_supernet_ref') as clear_mock:
        unassign_subnets_from_supernet(
            objects_manager, types_manager, SUPERNET_OBJECT_ID, [SUBNET_OBJECT_ID_A], request_user=user,
        )

    verify_mock.assert_called_once_with(types_manager, user)
    clear_mock.assert_called_once()


def test_unassign_accepts_a_request_exactly_at_the_cap() -> None:
    """The bound is inclusive - a full page of selected rows is a legal request."""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    ids = list(range(1, IpamUnassignLimits.MAX_SUBNET_IDS + 1))
    assigned_docs = [_make_cmdb_object(subnet_id, SUBNET_TYPE_ID) for subnet_id in ids]

    with patch(f'{PATH}.assert_supernet_exists'), \
         patch(f'{PATH}.verify_subnet_write_access'), \
         patch(f'{PATH}.load_assigned_subnets', return_value=assigned_docs), \
         patch(f'{PATH}.clear_supernet_ref') as clear_mock:
        result = unassign_subnets_from_supernet(objects_manager, types_manager, SUPERNET_OBJECT_ID, ids)

    assert result[IpamUnassignKey.UNASSIGNED_COUNT] == IpamUnassignLimits.MAX_SUBNET_IDS
    clear_mock.assert_called_once()


def test_unassign_aborts_400_one_id_over_the_cap_before_any_db_call() -> None:
    """
    The cap is checked on the coerced list, before anything is read

    A request that is refused for its size must not have cost a type read, a membership query or a
    write first.
    """
    objects_manager = MagicMock()
    types_manager = MagicMock()
    ids = list(range(1, IpamUnassignLimits.MAX_SUBNET_IDS + 2))

    with patch(f'{PATH}.assert_supernet_exists') as assert_mock, \
         patch(f'{PATH}.verify_subnet_write_access') as verify_mock, \
         patch(f'{PATH}.load_assigned_subnets') as load_mock, \
         patch(f'{PATH}.clear_supernet_ref') as clear_mock, \
         pytest.raises(HTTPException) as exc_info:
        unassign_subnets_from_supernet(objects_manager, types_manager, SUPERNET_OBJECT_ID, ids)

    assert exc_info.value.code == 400
    assert_mock.assert_not_called()
    verify_mock.assert_not_called()
    load_mock.assert_not_called()
    clear_mock.assert_not_called()


def test_the_cap_counts_deduplicated_ids() -> None:
    """
    Duplicates are collapsed first, so they cannot push a legal request over the bound

    The write and the `$in` are sized by the deduplicated list, which is what the cap exists to
    bound - counting the raw payload instead would refuse requests that cost nothing extra.
    """
    objects_manager = MagicMock()
    types_manager = MagicMock()
    ids = list(range(1, IpamUnassignLimits.MAX_SUBNET_IDS + 1)) * 2
    assigned_docs = [
        _make_cmdb_object(subnet_id, SUBNET_TYPE_ID)
        for subnet_id in range(1, IpamUnassignLimits.MAX_SUBNET_IDS + 1)
    ]

    with patch(f'{PATH}.assert_supernet_exists'), \
         patch(f'{PATH}.verify_subnet_write_access'), \
         patch(f'{PATH}.load_assigned_subnets', return_value=assigned_docs), \
         patch(f'{PATH}.clear_supernet_ref'):
        result = unassign_subnets_from_supernet(objects_manager, types_manager, SUPERNET_OBJECT_ID, ids)

    assert result[IpamUnassignKey.UNASSIGNED_COUNT] == IpamUnassignLimits.MAX_SUBNET_IDS
