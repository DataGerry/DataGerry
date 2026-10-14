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
Unit tests for cmdb.manager.types_manager.TypesManager

The manager is never constructed (its __init__ would build a real DB connection); every method is
exercised on a MagicMock-typed ``self``, and schema dict keys are referenced through the model key
enums per the no-magic-values rule.

What a type edit changes in its objects is not the manager's business - the plan and the statements
are pure (`types_mds_helper`, `objects_propagation_helper`) and have their own tests.
"""
import datetime
from types import SimpleNamespace
from typing import Any
from functools import partial
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.type_model import CmdbType, FieldKey, FieldType, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.manager.types_manager import TypesManager
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerInitError,
    BaseManagerInsertError,
    BaseManagerIterationError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.types_manager import (
    TypesManagerInsertError,
    TypesManagerUpdateError,
    TypesManagerGetError,
    TypesManagerDeleteError,
    TypesManagerIterationError,
)
from cmdb.errors.models.cmdb_type import CmdbTypeInitFromDataError, CmdbTypeToJsonError
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=protected-access

MGR_PATH: str = 'cmdb.manager.types_manager'

TYPE_ID: int = 42

# A wrapper value object_hook cannot decode - the caller's error, not a bug
UNDECODABLE_OID: dict[str, str] = {'$oid': 'not-an-object-id'}


def _manager() -> MagicMock:
    """A MagicMock-typed TypesManager whose private helpers are the real ones, bound to it"""
    mgr = MagicMock(spec=TypesManager)
    mgr._special_type_value = TypesManager._special_type_value
    mgr._as_stored_type_dict = TypesManager._as_stored_type_dict
    mgr._stored_type_dict_or_raise = partial(TypesManager._stored_type_dict_or_raise, mgr)
    mgr._distinct_type_ids = partial(TypesManager._distinct_type_ids, mgr)
    mgr.get_types_by = partial(TypesManager.get_types_by, mgr)

    return mgr


# ------------------------------------------------- the type reads --------------------------------------------------- #

def test_iterate_binds_the_rows_to_an_iteration_result() -> None:
    """The paged read hands its rows to IterationResult with the CmdbType class."""
    mgr = _manager()
    mgr.iterate_query.return_value = ([{TypeSchemaKey.PUBLIC_ID.value: 1}], 1)

    with patch(f'{MGR_PATH}.IterationResult') as iteration_result:
        result = TypesManager.iterate(mgr, MagicMock())

    assert result is iteration_result.return_value
    assert iteration_result.call_args.args[2] is CmdbType


def test_iterate_without_a_user_adds_no_access_control_criteria() -> None:
    """The callers that have already checked access get the unfiltered listing they rely on."""
    mgr = _manager()
    mgr.iterate_query.return_value = ([], 0)
    builder_params = MagicMock()

    with patch(f'{MGR_PATH}.IterationResult'):
        TypesManager.iterate(mgr, builder_params)

    builder_params.add_criteria.assert_not_called()


def test_iterate_without_a_permission_adds_no_access_control_criteria() -> None:
    """A user alone does not restrict anything - both halves of the pair are required."""
    mgr = _manager()
    mgr.iterate_query.return_value = ([], 0)
    builder_params = MagicMock()

    with patch(f'{MGR_PATH}.IterationResult'):
        TypesManager.iterate(mgr, builder_params, SimpleNamespace(group_id=3))

    builder_params.add_criteria.assert_not_called()


def test_iterate_with_a_user_and_permission_restricts_to_the_permitted_types() -> None:
    """The group's permitted-types criteria is merged in before the query runs."""
    mgr = _manager()
    mgr.iterate_query.return_value = ([], 0)
    builder_params = MagicMock()

    with patch(f'{MGR_PATH}.IterationResult'), \
         patch(f'{MGR_PATH}.build_permitted_types_criteria', return_value={'acl': 'criteria'}) as criteria:
        TypesManager.iterate(mgr, builder_params, SimpleNamespace(group_id=3), AccessControlPermission.READ)

    criteria.assert_called_once_with(3, AccessControlPermission.READ)
    builder_params.add_criteria.assert_called_once_with({'acl': 'criteria'})


def test_iterate_passes_several_permissions_through_to_the_criteria() -> None:
    """A caller can ask for more than READ; the manager hands the list on untouched."""
    mgr = _manager()
    mgr.iterate_query.return_value = ([], 0)
    builder_params = MagicMock()
    asked = [AccessControlPermission.READ, AccessControlPermission.CREATE]

    with patch(f'{MGR_PATH}.IterationResult'), \
         patch(f'{MGR_PATH}.build_permitted_types_criteria', return_value={'acl': 'criteria'}) as criteria:
        TypesManager.iterate(mgr, builder_params, SimpleNamespace(group_id=3), asked)

    criteria.assert_called_once_with(3, asked)


def test_iterate_applies_the_access_control_to_the_criteria_not_the_pipeline() -> None:
    """
    The rule goes into the criteria both aggregations read

    ``iterate_query`` builds its total from the criteria alone, so an access rule that lived only in
    the data pipeline would filter the rows and leave the count beside them unfiltered - the bug
    the object listing records separately.
    """
    mgr = _manager()
    mgr.iterate_query.return_value = ([], 0)
    builder_params = MagicMock()

    with patch(f'{MGR_PATH}.IterationResult'):
        TypesManager.iterate(mgr, builder_params, SimpleNamespace(group_id=3), AccessControlPermission.READ)

    builder_params.add_criteria.assert_called_once()
    assert mgr.iterate_query.call_args.args == (builder_params,)


def test_find_types_hydrates_every_match() -> None:
    """A criteria read answers with CmdbTypes, not documents - read through get_types_by, its one implementation"""
    mgr = _manager()
    mgr.get_many.return_value = [{TypeSchemaKey.PUBLIC_ID.value: 1}, {TypeSchemaKey.PUBLIC_ID.value: 2}]

    with patch.object(CmdbType, 'from_data', side_effect=lambda doc: f'type-{doc["public_id"]}'):
        assert TypesManager.find_types(mgr, {'active': True}) == ['type-1', 'type-2']

    assert mgr.get_many.call_args.kwargs['criteria'] == {'active': True}


def test_get_types_lookup_skips_the_query_for_an_empty_list() -> None:
    """Nothing to resolve means no database round trip at all"""
    mgr = _manager()

    assert TypesManager.get_types_lookup(mgr, []) == {}
    mgr.find_types.assert_not_called()


def test_get_types_lookup_keys_the_types_by_public_id() -> None:
    """One bulk read, so a caller resolving many type references pays for one round trip."""
    mgr = _manager()
    mgr.find_types.return_value = [SimpleNamespace(public_id=7), SimpleNamespace(public_id=8)]

    result = TypesManager.get_types_lookup(mgr, [7, 8])

    assert sorted(result) == [7, 8]
    assert mgr.find_types.call_args.kwargs['criteria'] == {
        TypeSchemaKey.PUBLIC_ID.value: {'$in': [7, 8]},
    }


def test_delete_type_reports_the_acknowledgement() -> None:
    """
    A caller can tell a deletion from a no-op

    Returning None would make "deleted" and "no such type" the same answer - while update_type
    deliberately returns its UpdateResult for exactly that reason.
    """
    mgr = _manager()
    mgr.delete.return_value = True

    assert TypesManager.delete_type(mgr, 7) is True
    assert mgr.delete.call_args.args[0] == {TypeSchemaKey.PUBLIC_ID.value: 7}

    mgr.delete.return_value = False
    assert TypesManager.delete_type(mgr, 7) is False


def test_as_stored_type_dict_keeps_a_timestamp_through_the_bson_round_trip() -> None:
    """
    The round trip a raw dict takes on its way into the collection

    It decodes with the shared json_codec, whose ISO branch must not read a naive timestamp as the
    HOST's local time - so a type's creation_time moved by the server's UTC offset on every update
    that went through this path.
    """
    created = datetime.datetime(2026, 9, 9, 10, 0, 0, tzinfo=datetime.timezone.utc)

    stored = TypesManager._as_stored_type_dict({
        TypeSchemaKey.PUBLIC_ID.value: TYPE_ID, 'creation_time': created,
    })

    assert stored['creation_time'] == created


# ------------------------------------------------- check_special_type_exists ---------------------------------------- #

def test_check_special_type_exists_reflects_lookup() -> None:
    """Returns True when a type with the special_type marker exists, False otherwise."""
    mgr = _manager()

    mgr.count_documents.return_value = 1
    assert TypesManager.check_special_type_exists(mgr, SpecialType.SUBNET) is True

    mgr.count_documents.return_value = 0
    assert TypesManager.check_special_type_exists(mgr, SpecialType.SUBNET) is False


def test_check_special_type_exists_is_an_existence_check() -> None:
    """The server may stop at the first match: no type document is loaded to answer a yes or no"""
    mgr = _manager()
    mgr.count_documents.return_value = 0

    TypesManager.check_special_type_exists(mgr, SpecialType.SUBNET)

    assert mgr.count_documents.call_args.kwargs == {'limit': 1}
    mgr.get_one_by.assert_not_called()


def test_check_special_type_exists_queries_the_marker_by_value() -> None:
    """The criteria carry plain strings, like every other query in this manager."""
    mgr = _manager()
    mgr.count_documents.return_value = 0

    TypesManager.check_special_type_exists(mgr, SpecialType.SUBNET)

    assert mgr.count_documents.call_args.args[0] == {
        TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.SUBNET.value,
    }


@pytest.mark.parametrize('marker', [SpecialType.SUBNET, SpecialType.SUBNET.value],
                         ids=['member', 'string'])
def test_check_special_type_exists_accepts_a_member_or_a_string(marker: Any) -> None:
    """
    Both shapes reach this manager, and both have to answer the same query

    The marker comes as a member from code that knows which one it wants, and as a **string** from a
    payload - the special-type route's query parameter, a type-import entry and the type-create guard
    all pass the value they validated. Reading `.value` off the string form raised an AttributeError
    that every caller swallowed into its own error message.
    """
    mgr = _manager()
    mgr.count_documents.return_value = 0

    TypesManager.check_special_type_exists(mgr, marker)

    assert mgr.count_documents.call_args.args[0] == {
        TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.SUBNET.value,
    }


@pytest.mark.parametrize('marker', [SpecialType.RACK, SpecialType.RACK.value],
                         ids=['member', 'string'])
def test_get_type_ids_of_special_type_accepts_a_member_or_a_string(marker: Any) -> None:
    """Same two shapes, same query - the id read is used by the Rack and Cable paths"""
    mgr = _manager()
    mgr.get_distinct.return_value = []

    TypesManager.get_type_ids_of_special_type(mgr, marker)

    assert mgr.get_distinct.call_args.args[1] == {
        TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.RACK.value,
    }


def test_check_special_type_exists_wraps_a_failing_lookup() -> None:
    """
    It must not leak the BaseManager error

    The class promises that every public method answers with a TypesManager* error, and a caller
    handling only those would have seen an unhandled BaseManagerGetError.
    """
    mgr = _manager()
    mgr.count_documents.side_effect = BaseManagerGetError('db down')

    with pytest.raises(TypesManagerGetError):
        TypesManager.check_special_type_exists(mgr, SpecialType.SUBNET)


# ------------------------------------------------------ read helpers ------------------------------------------------ #







def test_get_types_by_forwards_sort_direction_and_filter() -> None:
    """direction binds to the sort order instead of being swallowed as a query filter field."""
    mgr = _manager()
    mgr.get_many.return_value = []
    criteria = {'public_id': {'$in': [1, 2]}}  # the shape the type-export route sends

    TypesManager.get_types_by(mgr, sort='public_id', direction=CmdbDAO.DAO_ASCENDING, criteria=criteria)

    mgr.get_many.assert_called_once_with(
        sort='public_id', direction=CmdbDAO.DAO_ASCENDING, criteria=criteria
    )


def test_get_types_by_defaults_to_descending() -> None:
    """Without an explicit direction the BaseManager default (-1) is forwarded."""
    mgr = _manager()
    mgr.get_many.return_value = []

    TypesManager.get_types_by(mgr)

    mgr.get_many.assert_called_once_with(sort='public_id', direction=CmdbDAO.DAO_DESCENDING, criteria=None)


# ----------------------------------------------------- error wrapping ----------------------------------------------- #

def test_insert_type_wraps_a_failed_insert() -> None:
    """A failure in the underlying insert surfaces as TypesManagerInsertError."""
    mgr = _manager()
    mgr.insert.side_effect = BaseManagerInsertError('boom')

    with pytest.raises(TypesManagerInsertError):
        TypesManager.insert_type(mgr, {TypeSchemaKey.NAME.value: 'x'})


def test_update_type_wraps_a_failed_update() -> None:
    """A failure in the underlying update surfaces as TypesManagerUpdateError."""
    mgr = _manager()
    mgr.update.side_effect = BaseManagerUpdateError('boom')

    with pytest.raises(TypesManagerUpdateError):
        TypesManager.update_type(mgr, 1, {TypeSchemaKey.NAME.value: 'x'})


def test_update_type_pins_the_document_identity() -> None:
    """A payload carrying a different public_id cannot rewrite the stored id."""
    mgr = _manager()

    TypesManager.update_type(mgr, 7, {TypeSchemaKey.PUBLIC_ID.value: 99, TypeSchemaKey.NAME.value: 'x'})

    _, kwargs = mgr.update.call_args
    assert kwargs['criteria'] == {TypeSchemaKey.PUBLIC_ID.value: 7}
    assert kwargs['data'][TypeSchemaKey.PUBLIC_ID.value] == 7


def test_update_type_returns_the_update_result() -> None:
    """The UpdateResult is passed through so callers can read matched_count."""
    mgr = _manager()
    update_result = SimpleNamespace(matched_count=0, modified_count=0)
    mgr.update.return_value = update_result

    assert TypesManager.update_type(mgr, 7, {}) is update_result


def test_update_type_field_sets_only_that_key() -> None:
    """A single-field update $sets one key and leaves the rest of the document alone."""
    mgr = _manager()

    TypesManager.update_type_field(mgr, 7, TypeSchemaKey.CI_EXPLORER_LABEL.value, 'name')

    _, kwargs = mgr.update.call_args
    assert kwargs['criteria'] == {TypeSchemaKey.PUBLIC_ID.value: 7}
    assert kwargs['data'] == {TypeSchemaKey.CI_EXPLORER_LABEL.value: 'name'}


def test_update_type_field_wraps_a_failed_update() -> None:
    """A failure in the underlying update surfaces as TypesManagerUpdateError."""
    mgr = _manager()
    mgr.update.side_effect = BaseManagerUpdateError('boom')

    with pytest.raises(TypesManagerUpdateError):
        TypesManager.update_type_field(mgr, 7, TypeSchemaKey.CI_EXPLORER_LABEL.value, 'name')


def test_find_types_wraps_a_failed_read() -> None:
    """A failure in the underlying read surfaces as TypesManagerGetError."""
    mgr = _manager()
    mgr.get_many.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.find_types(mgr, {'public_id': 1})


def test_get_types_by_wraps_a_failed_read() -> None:
    """A failure in get_types_by surfaces as TypesManagerGetError."""
    mgr = _manager()
    mgr.get_many.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_types_by(mgr)


# -------------------------------------------------- _as_stored_type_dict -------------------------------------------- #

def _minimal_type_doc(public_id: int = 1) -> dict[str, Any]:
    """Builds a minimal CmdbType-shaped doc that CmdbType.from_data accepts."""
    return {
        TypeSchemaKey.PUBLIC_ID.value: public_id,
        TypeSchemaKey.NAME.value: f'type-{public_id}',
        'label': f'Type {public_id}',
        TypeSchemaKey.AUTHOR_ID.value: 1,
        TypeSchemaKey.ACTIVE.value: True,
        TypeSchemaKey.FIELDS.value: [{FieldKey.TYPE.value: FieldType.TEXT.value, FieldKey.NAME.value: 'a'}],
        'render_meta': {'icon': '', 'sections': [], 'summary': {'fields': []}},
        'version': '1.0.0',
    }


def test_as_stored_type_dict_passes_through_plain_dict() -> None:
    """A raw dict is returned as an equal dict after the BSON-aware JSON round-trip."""
    raw = {TypeSchemaKey.PUBLIC_ID.value: 5, TypeSchemaKey.NAME.value: 'x'}

    result = TypesManager._as_stored_type_dict(raw)

    assert result == raw


def test_as_stored_type_dict_serialises_cmdb_type_instance() -> None:
    """A CmdbType instance is serialised to its to_json dict form."""
    cmdb_type = CmdbType.from_data(_minimal_type_doc(public_id=7))

    result = TypesManager._as_stored_type_dict(cmdb_type)

    assert isinstance(result, dict)
    assert result[TypeSchemaKey.PUBLIC_ID.value] == 7


def test_get_type_wraps_get_error() -> None:
    """A BaseManagerGetError from get_one surfaces as TypesManagerGetError."""
    mgr = _manager()
    mgr.get_one.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_type(mgr, 1)


def test_get_type_returns_the_raw_document() -> None:
    """get_type hands back the stored document untouched, without hydrating it."""
    mgr = _manager()
    mgr.get_one.return_value = {TypeSchemaKey.PUBLIC_ID.value: 1}

    assert TypesManager.get_type(mgr, 1) == {TypeSchemaKey.PUBLIC_ID.value: 1}


def test_get_type_instance_hydrates_the_document() -> None:
    """get_type_instance maps the stored document through CmdbType.from_data."""
    mgr = _manager()
    mgr.get_one.return_value = {TypeSchemaKey.PUBLIC_ID.value: 1}

    with patch(f'{MGR_PATH}.CmdbType') as cmdb_type:
        cmdb_type.from_data.return_value = 'hydrated'

        assert TypesManager.get_type_instance(mgr, 1) == 'hydrated'


@pytest.mark.parametrize('method', ['get_type', 'get_type_instance'], ids=['dict', 'instance'])
def test_missing_type_is_none_in_both_modes(method: str) -> None:
    """An unknown public_id is reported as None by both read methods, never as an error."""
    mgr = _manager()
    mgr.get_one.return_value = None

    assert getattr(TypesManager, method)(mgr, 9999) is None


def test_get_type_instance_wraps_hydration_error() -> None:
    """A CmdbType.from_data failure surfaces as TypesManagerGetError, not as the raw model error."""
    mgr = _manager()
    mgr.get_one.return_value = {TypeSchemaKey.PUBLIC_ID.value: 1}

    with patch.object(CmdbType, 'from_data') as cmdb_type_from_data:
        cmdb_type_from_data.side_effect = CmdbTypeInitFromDataError('broken document')

        with pytest.raises(TypesManagerGetError):
            TypesManager.get_type_instance(mgr, 1)


def test_delete_type_wraps_delete_error() -> None:
    """A BaseManagerDeleteError from delete surfaces as TypesManagerDeleteError."""
    mgr = _manager()
    mgr.delete.side_effect = BaseManagerDeleteError('boom')

    with pytest.raises(TypesManagerDeleteError):
        TypesManager.delete_type(mgr, 5)


# -------------------------------------- error wrapping: init / read / MDS ------------------------------------------- #
def test_init_catches_nothing() -> None:
    """Building the manager touches no database: a None dbm is a programming error and propagates as itself"""
    with pytest.raises(AttributeError):
        TypesManager(None)


def test_get_new_type_public_id_wraps_get_error() -> None:
    """A BaseManagerGetError from the id counter surfaces as TypesManagerGetError."""
    mgr = _manager()
    mgr.get_next_public_id.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_new_type_public_id(mgr)


def test_iterate_wraps_failure_as_iteration_error() -> None:
    """A failure in the aggregation surfaces as TypesManagerIterationError."""
    mgr = _manager()
    mgr.iterate_query.side_effect = BaseManagerIterationError('boom')

    with pytest.raises(TypesManagerIterationError):
        TypesManager.iterate(mgr, MagicMock())






# ------------------------------------------------- get_existing_type_ids -------------------------------------------- #

def test_get_existing_type_ids_returns_the_matching_ids() -> None:
    """The distinct lookup's result is handed back as a set, so callers can test membership."""
    mgr = _manager()
    mgr.get_distinct.return_value = [3, 7]

    assert TypesManager.get_existing_type_ids(mgr, [3, 7, 9]) == {3, 7}

    call = mgr.get_distinct.call_args
    assert call.args[0] == TypeSchemaKey.PUBLIC_ID.value
    assert call.args[1] == {TypeSchemaKey.PUBLIC_ID.value: {'$in': [3, 7, 9]}}


def test_get_existing_type_ids_skips_the_query_for_an_empty_list() -> None:
    """Nothing to resolve means no database round trip at all."""
    mgr = _manager()

    assert TypesManager.get_existing_type_ids(mgr, []) == set()
    mgr.get_distinct.assert_not_called()


def test_get_existing_type_ids_wraps_get_error() -> None:
    """A failing distinct query surfaces as the manager's own error type."""
    mgr = _manager()
    mgr.get_distinct.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_existing_type_ids(mgr, [1])


# ------------------------------------------ get_type_ids_of_special_type -------------------------------------------- #

def test_get_type_ids_of_special_type_queries_the_marker() -> None:
    """One distinct on the indexed public_id - no type document is loaded to answer 'which type is the Rack'."""
    mgr = _manager()
    mgr.get_distinct.return_value = [9551]

    assert TypesManager.get_type_ids_of_special_type(mgr, SpecialType.RACK) == [9551]

    call = mgr.get_distinct.call_args
    assert call.args[0] == TypeSchemaKey.PUBLIC_ID.value
    assert call.args[1] == {TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.RACK.value}


def test_get_type_ids_of_special_type_is_empty_when_the_marker_is_unused() -> None:
    """An installation without the special type yields an empty list, not None."""
    mgr = _manager()
    mgr.get_distinct.return_value = []

    assert TypesManager.get_type_ids_of_special_type(mgr, SpecialType.RACK) == []


def test_get_type_ids_of_special_type_drops_non_integer_values() -> None:
    """The ids go straight into a '$nin' of ints, so a drifted value must not travel with them."""
    mgr = _manager()
    mgr.get_distinct.return_value = [9551, None, 'garbage']

    assert TypesManager.get_type_ids_of_special_type(mgr, SpecialType.RACK) == [9551]


def test_get_type_ids_of_special_type_wraps_get_error() -> None:
    """A failing distinct query surfaces as the manager's own error type."""
    mgr = _manager()
    mgr.get_distinct.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_type_ids_of_special_type(mgr, SpecialType.RACK)


# ----------------------------------------- get_type_ids_with_location_field ----------------------------------------- #

def test_get_type_ids_with_location_field_matches_on_the_field_type() -> None:
    """
    The mountable types of the Rack picker, answered without loading a type document.

    The match is on the field's TYPE rather than its name, the way the whole location machinery matches,
    so a type whose location field is not called 'dg_location' still counts.
    """
    mgr = _manager()
    mgr.get_distinct.return_value = [9552]

    assert TypesManager.get_type_ids_with_location_field(mgr) == [9552]

    call = mgr.get_distinct.call_args
    assert call.args[0] == TypeSchemaKey.PUBLIC_ID.value
    assert call.args[1] == {
        TypeSchemaKey.FIELDS.value: {'$elemMatch': {FieldKey.TYPE.value: FieldType.LOCATION.value}},
    }


def test_get_type_ids_with_location_field_is_empty_when_no_type_declares_one() -> None:
    """An empty list, which the picker turns into an '$in' matching nothing - nothing is mountable."""
    mgr = _manager()
    mgr.get_distinct.return_value = []

    assert TypesManager.get_type_ids_with_location_field(mgr) == []


def test_get_type_ids_with_location_field_drops_non_integer_values() -> None:
    """The ids go straight into an '$in' of ints, so a drifted value must not travel with them."""
    mgr = _manager()
    mgr.get_distinct.return_value = [9552, None, 'garbage']

    assert TypesManager.get_type_ids_with_location_field(mgr) == [9552]


def test_get_type_ids_with_location_field_wraps_get_error() -> None:
    """A failing distinct query surfaces as the manager's own error type."""
    mgr = _manager()
    mgr.get_distinct.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_type_ids_with_location_field(mgr)


# ------------------------------------------- narrowed arms: a bug is not a failure ---------------------------------- #

BUG: str = 'a programming error'


@pytest.mark.parametrize('delegate, call', [
    ('get_next_public_id', lambda mgr: TypesManager.get_new_type_public_id(mgr)),
    ('get_one', lambda mgr: TypesManager.get_type(mgr, TYPE_ID)),
    ('get_one', lambda mgr: TypesManager.get_type_instance(mgr, TYPE_ID)),
    ('iterate_query', lambda mgr: TypesManager.iterate(mgr, MagicMock())),
    ('get_many', lambda mgr: TypesManager.get_types_by(mgr)),
    ('get_many', lambda mgr: TypesManager.find_types(mgr, {})),
    ('insert', lambda mgr: TypesManager.insert_type(mgr, {TypeSchemaKey.NAME.value: 'x'})),
    ('update', lambda mgr: TypesManager.update_type(mgr, TYPE_ID, {TypeSchemaKey.NAME.value: 'x'})),
    ('update', lambda mgr: TypesManager.update_type_field(mgr, TYPE_ID, TypeSchemaKey.CI_EXPLORER_LABEL.value, 'x')),
    ('delete', lambda mgr: TypesManager.delete_type(mgr, TYPE_ID)),
    ('count_documents', lambda mgr: TypesManager.check_special_type_exists(mgr, SpecialType.RACK)),
    ('get_distinct', lambda mgr: TypesManager.get_type_ids_of_special_type(mgr, SpecialType.RACK)),
    ('get_distinct', lambda mgr: TypesManager.get_type_ids_with_location_field(mgr)),
    ('get_distinct', lambda mgr: TypesManager.get_existing_type_ids(mgr, [TYPE_ID])),
], ids=[
    'get_new_type_public_id', 'get_type', 'get_type_instance', 'iterate', 'get_types_by', 'find_types',
    'insert_type', 'update_type', 'update_type_field', 'delete_type', 'check_special_type_exists',
    'get_type_ids_of_special_type', 'get_type_ids_with_location_field', 'get_existing_type_ids',
])
def test_a_programming_error_propagates_as_itself(delegate: str, call: Any) -> None:
    """Only what the call raises is wrapped - a bug reaches the route as itself, so it answers 500, not 400"""
    mgr = _manager()
    getattr(mgr, delegate).side_effect = TypeError(BUG)

    with pytest.raises(TypeError, match=BUG):
        call(mgr)


def test_a_bug_while_hydrating_a_type_propagates_as_itself() -> None:
    """from_data's declared error is the stored document's fault; anything else it raises is not"""
    mgr = _manager()
    mgr.get_one.return_value = {TypeSchemaKey.PUBLIC_ID.value: TYPE_ID}

    with patch.object(CmdbType, 'from_data', side_effect=TypeError(BUG)), pytest.raises(TypeError, match=BUG):
        TypesManager.get_type_instance(mgr, TYPE_ID)


@pytest.mark.parametrize('model_error', [CmdbTypeInitFromDataError('unreadable'), CmdbTypeToJsonError('unwritable')],
                         ids=['from_data', 'to_json'])
def test_the_declared_model_errors_are_the_reads_failure(model_error: Exception) -> None:
    """A stored type that no longer fits the model fails the read as the manager's own error, carrying the cause"""
    mgr = _manager()
    mgr.get_many.return_value = [{TypeSchemaKey.PUBLIC_ID.value: TYPE_ID}]

    with patch.object(CmdbType, 'from_data', side_effect=model_error), \
         pytest.raises(TypesManagerGetError) as caught:
        TypesManager.get_types_by(mgr)

    assert caught.value.args[0] is model_error


def test_iterate_wraps_an_unreadable_row_as_an_iteration_error() -> None:
    """IterationResult builds each row through from_data; its declared error is the listing's failure"""
    mgr = _manager()
    mgr.iterate_query.return_value = ([{TypeSchemaKey.PUBLIC_ID.value: TYPE_ID}], 1)

    with patch(f'{MGR_PATH}.IterationResult', side_effect=CmdbTypeInitFromDataError('unreadable')), \
         pytest.raises(TypesManagerIterationError):
        TypesManager.iterate(mgr, MagicMock())


@pytest.mark.parametrize('write, error', [
    (lambda mgr, document: TypesManager.insert_type(mgr, document), TypesManagerInsertError),
    (lambda mgr, document: TypesManager.update_type(mgr, TYPE_ID, document), TypesManagerUpdateError),
], ids=['insert_type', 'update_type'])
def test_an_undecodable_wrapper_value_is_the_writes_error(write: Any, error: type[Exception]) -> None:
    """A '$oid' the codec cannot decode came with the caller's document: the write's 400, nothing is written"""
    mgr = _manager()

    with pytest.raises(error):
        write(mgr, {TypeSchemaKey.NAME.value: 'x', 'reference': UNDECODABLE_OID})

    mgr.insert.assert_not_called()
    mgr.update.assert_not_called()


@pytest.mark.parametrize('write, error', [
    (lambda mgr, document: TypesManager.insert_type(mgr, document), TypesManagerInsertError),
    (lambda mgr, document: TypesManager.update_type(mgr, TYPE_ID, document), TypesManagerUpdateError),
], ids=['insert_type', 'update_type'])
def test_a_type_that_cannot_be_written_out_is_the_writes_error(write: Any, error: type[Exception]) -> None:
    """to_json's declared error is the write's failure, carrying the cause"""
    mgr = _manager()
    unwritable = CmdbTypeToJsonError('unwritable')

    with patch.object(CmdbType, 'to_json', side_effect=unwritable), pytest.raises(error) as caught:
        write(mgr, CmdbType.from_data(_minimal_type_doc(public_id=TYPE_ID)))

    assert caught.value.args[0] is unwritable


def test_a_bug_in_the_round_trip_propagates_as_itself() -> None:
    """Only the codec's undecodable-value errors are scoped to the write - any other error is a bug"""
    mgr = _manager()

    with patch(f'{MGR_PATH}.bson_round_trip', side_effect=TypeError(BUG)), pytest.raises(TypeError, match=BUG):
        TypesManager.insert_type(mgr, {TypeSchemaKey.NAME.value: 'x'})


@pytest.mark.parametrize('failure', [
    (BaseManagerInsertError('db'), TypesManagerInsertError, lambda mgr: TypesManager.insert_type(mgr, {})),
    (BaseManagerUpdateError('db'), TypesManagerUpdateError, lambda mgr: TypesManager.update_type(mgr, TYPE_ID, {})),
    (BaseManagerDeleteError('db'), TypesManagerDeleteError, lambda mgr: TypesManager.delete_type(mgr, TYPE_ID)),
], ids=['insert', 'update', 'delete'])
def test_the_wrapper_carries_the_failure_itself(failure: Any) -> None:
    """The manager error's argument is the database failure, so a caller can branch on what failed"""
    cause, wrapper, call = failure
    mgr = _manager()

    for delegate in ('insert', 'update', 'delete'):
        getattr(mgr, delegate).side_effect = cause

    with pytest.raises(wrapper) as caught:
        call(mgr)

    assert caught.value.args[0] is cause


# ------------------------------------------------------ _distinct_type_ids ------------------------------------------ #

def test_distinct_type_ids_reads_one_distinct_on_the_public_id() -> None:
    """The three id reads share one query shape: distinct public_id under the caller's criteria"""
    mgr = _manager()
    mgr.get_distinct.return_value = [3, True, 7, None, 'x']

    assert TypesManager._distinct_type_ids(mgr, {'k': 'v'}) == [3, True, 7]
    mgr.get_distinct.assert_called_once_with(TypeSchemaKey.PUBLIC_ID.value, {'k': 'v'})


def test_get_existing_type_ids_drops_non_integer_values_too() -> None:
    """The existence read now shares the int filter of the other two id reads"""
    mgr = _manager()
    mgr.get_distinct.return_value = [3, None, 'garbage']

    assert TypesManager.get_existing_type_ids(mgr, [3]) == {3}


# ------------------------------------------------------ get_denied_type_ids ----------------------------------------- #

def test_get_denied_type_ids_answers_the_shared_resolution() -> None:
    """The one projected read resolve_denied_type_ids makes, for the user and the permission"""
    user = MagicMock()

    with patch(f'{MGR_PATH}.resolve_denied_type_ids', return_value=[3, 9]) as resolve:
        assert TypesManager.get_denied_type_ids(_manager(), user, AccessControlPermission.READ) == [3, 9]

    resolve.assert_called_once_with(user, AccessControlPermission.READ)


@pytest.mark.parametrize('failure', [BaseManagerGetError('read'), BaseManagerInitError('wiring')],
                         ids=['read', 'manager'])
def test_get_denied_type_ids_wraps_a_failed_read(failure: Exception) -> None:
    """The manager's own error, carrying the failure - a route catches TypesManagerGetError"""
    with patch(f'{MGR_PATH}.resolve_denied_type_ids', side_effect=failure), \
         pytest.raises(TypesManagerGetError) as caught:
        TypesManager.get_denied_type_ids(_manager(), MagicMock(), AccessControlPermission.READ)

    assert caught.value.args[0] is failure


def test_get_denied_type_ids_lets_a_bug_through() -> None:
    """Not a failed read: it propagates as itself"""
    with patch(f'{MGR_PATH}.resolve_denied_type_ids', side_effect=TypeError(BUG)), \
         pytest.raises(TypeError, match=BUG):
        TypesManager.get_denied_type_ids(_manager(), MagicMock(), AccessControlPermission.READ)
