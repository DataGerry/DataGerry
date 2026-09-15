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

The multi-data-section propagation is split across two modules and so are its tests: what a type
edit CHANGES (and what that does to one object in memory) is pure and lives in
tests/unit/manager/test_types_mds_helper.py; what is pinned here is the manager's own half - which
objects it reads, with which projection, in which batches, and that it YIELDS the changed ones so the
caller can write one batch before the next is read. A propagation that collected everything first was
one unbounded read and one unbounded bulk write per type.
"""
import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.type_model import CmdbType, FieldKey, FieldType, SectionType, SectionKey, TypeSchemaKey
from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.manager.types_manager import MDS_OBJECT_PROJECTION, TypesManager
from cmdb.errors.manager import BaseManagerGetError, BaseManagerDeleteError
from cmdb.errors.manager.types_manager import (
    TypesManagerInsertError,
    TypesManagerUpdateError,
    TypesManagerGetError,
    TypesManagerDeleteError,
    TypesManagerInitError,
    TypesManagerIterationError,
    TypesManagerUpdateMDSError,
)
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=protected-access

MGR_PATH: str = 'cmdb.manager.types_manager'

SECTION_ID: str = 'dg-ipam-interface'
OTHER_SECTION_ID: str = 'dg-other-section'
TYPE_ID: int = 42


def _entry(name: str, value: Any = None, field_type: str = FieldType.TEXT.value) -> dict[str, Any]:
    """Builds one stored MDS field entry ({name, value, type})."""
    return {
        CmdbObjectFieldKey.NAME.value: name,
        CmdbObjectFieldKey.VALUE.value: value,
        CmdbObjectFieldKey.TYPE.value: field_type,
    }


def _mds_section(section_id: str, rows: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """Builds one MDS section dict: rows nested under values[].data per the canonical shape."""
    return {
        CmdbObjectMdsKey.SECTION_ID.value: section_id,
        CmdbObjectMdsKey.VALUES.value: [{CmdbObjectMdsRowKey.DATA.value: row} for row in rows],
    }


def _row_data(section: dict[str, Any], row_index: int) -> list[dict[str, Any]]:
    """Returns the field-entry list of a given row of an MDS section."""
    return section[CmdbObjectMdsKey.VALUES.value][row_index][CmdbObjectMdsRowKey.DATA.value]


def _names(entries: list[dict[str, Any]]) -> list[str]:
    """Returns the field names of a row's entry list, in order."""
    return [entry[CmdbObjectFieldKey.NAME.value] for entry in entries]


# ------------------------------------------------- the type reads ---------------------------------------------------- #

def test_iterate_binds_the_rows_to_an_iteration_result() -> None:
    """The paged read hands its rows to IterationResult with the CmdbType class."""
    mgr = MagicMock(spec=TypesManager)
    mgr.iterate_query.return_value = ([{TypeSchemaKey.PUBLIC_ID.value: 1}], 1)

    with patch(f'{MGR_PATH}.IterationResult') as iteration_result:
        result = TypesManager.iterate(mgr, MagicMock())

    assert result is iteration_result.return_value
    assert iteration_result.call_args.args[2] is CmdbType


def test_find_types_hydrates_every_match() -> None:
    """A criteria read answers with CmdbTypes, not documents."""
    mgr = MagicMock(spec=TypesManager)
    mgr.find.return_value = [{TypeSchemaKey.PUBLIC_ID.value: 1}, {TypeSchemaKey.PUBLIC_ID.value: 2}]

    with patch.object(CmdbType, 'from_data', side_effect=lambda doc: f'type-{doc["public_id"]}'):
        assert TypesManager.find_types(mgr, {'active': True}) == ['type-1', 'type-2']


def test_get_types_lookup_keys_the_types_by_public_id() -> None:
    """One bulk read, so a caller resolving many type references pays for one round trip."""
    mgr = MagicMock(spec=TypesManager)
    mgr.find_types.return_value = [SimpleNamespace(public_id=7), SimpleNamespace(public_id=8)]

    result = TypesManager.get_types_lookup(mgr, [7, 8])

    assert sorted(result) == [7, 8]
    assert mgr.find_types.call_args.kwargs['criteria'] == {
        TypeSchemaKey.PUBLIC_ID.value: {'$in': [7, 8]},
    }


def test_delete_type_reports_the_acknowledgement() -> None:
    """
    A caller can tell a deletion from a no-op

    It used to return None, so "deleted" and "no such type" were the same answer - while update_type
    deliberately returns its UpdateResult for exactly that reason.
    """
    mgr = MagicMock(spec=TypesManager)
    mgr.delete.return_value = True

    assert TypesManager.delete_type(mgr, 7) is True
    assert mgr.delete.call_args.args[0] == {TypeSchemaKey.PUBLIC_ID.value: 7}

    mgr.delete.return_value = False
    assert TypesManager.delete_type(mgr, 7) is False


def test_as_stored_type_dict_keeps_a_timestamp_through_the_bson_round_trip() -> None:
    """
    The round trip a raw dict takes on its way into the collection

    It decodes with the shared json_codec, whose ISO branch used to read a naive timestamp as the
    HOST's local time - so a type's creation_time moved by the server's UTC offset on every update
    that went through this path.
    """
    created = datetime.datetime(2026, 9, 9, 10, 0, 0, tzinfo=datetime.timezone.utc)

    stored = TypesManager._as_stored_type_dict({
        TypeSchemaKey.PUBLIC_ID.value: TYPE_ID, 'creation_time': created,
    })

    assert stored['creation_time'] == created


# ------------------------------------------------ the object reads --------------------------------------------------- #

def test_get_objects_for_type_reads_by_type_id() -> None:
    """The unnarrowed read asks for the type's objects through the base manager, not through dbm."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many_from_other_collection.return_value = []

    TypesManager.get_objects_for_type(mgr, TYPE_ID)

    call = mgr.get_many_from_other_collection.call_args
    assert call.args[0] == CmdbObject.COLLECTION
    assert call.kwargs[CmdbObjectKey.TYPE_ID.value] == TYPE_ID
    assert call.kwargs['projection'] is None


def test_get_objects_for_type_narrows_by_mds_section() -> None:
    """The MDS narrowing is a dotted path on the section_id, so unaffected objects never load."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many_from_other_collection.return_value = []

    TypesManager.get_objects_for_type(mgr, TYPE_ID, section_ids=[SECTION_ID])

    mds_path = f'{CmdbObjectKey.MULTI_DATA_SECTIONS.value}.{CmdbObjectMdsKey.SECTION_ID.value}'
    assert mgr.get_many_from_other_collection.call_args.kwargs[mds_path] == {'$in': [SECTION_ID]}


def test_get_objects_for_type_narrows_by_public_ids() -> None:
    """What the batched propagation reads one chunk with."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many_from_other_collection.return_value = []

    TypesManager.get_objects_for_type(mgr, TYPE_ID, public_ids=[1, 2])

    assert mgr.get_many_from_other_collection.call_args.kwargs[
        CmdbObjectKey.PUBLIC_ID.value
    ] == {'$in': [1, 2]}


def test_get_objects_for_type_forwards_the_projection() -> None:
    """A projected read is what keeps a type's `fields` out of the propagation."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many_from_other_collection.return_value = []

    TypesManager.get_objects_for_type(mgr, TYPE_ID, projection=MDS_OBJECT_PROJECTION)

    assert mgr.get_many_from_other_collection.call_args.kwargs['projection'] is MDS_OBJECT_PROJECTION


def test_get_objects_for_type_hydrates_each_document() -> None:
    """The documents come back as CmdbObjects, projected or not."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many_from_other_collection.return_value = [{
        CmdbObjectKey.PUBLIC_ID.value: 5,
        CmdbObjectKey.TYPE_ID.value: TYPE_ID,
        CmdbObjectKey.AUTHOR_ID.value: 1,
        CmdbObjectKey.MULTI_DATA_SECTIONS.value: [],
    }]

    result = TypesManager.get_objects_for_type(mgr, TYPE_ID, projection=MDS_OBJECT_PROJECTION)

    assert [obj.public_id for obj in result] == [5]


def test_get_object_ids_for_type_reads_ids_only() -> None:
    """The first half of the batched propagation: ids are small enough to hold for a whole type."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many_from_other_collection.return_value = [
        {CmdbObjectKey.PUBLIC_ID.value: 3}, {CmdbObjectKey.PUBLIC_ID.value: 4},
    ]

    assert TypesManager.get_object_ids_for_type(mgr, TYPE_ID, section_ids=[SECTION_ID]) == [3, 4]

    projection = mgr.get_many_from_other_collection.call_args.kwargs['projection']
    assert projection == {CmdbObjectKey.PUBLIC_ID.value: 1, '_id': 0}


def test_get_object_ids_for_type_drops_non_integer_ids() -> None:
    """The ids go into an '$in' of ints, so a drifted value must not travel with them."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many_from_other_collection.return_value = [
        {CmdbObjectKey.PUBLIC_ID.value: 3}, {CmdbObjectKey.PUBLIC_ID.value: None}, {},
    ]

    assert TypesManager.get_object_ids_for_type(mgr, TYPE_ID) == [3]


def test_get_object_ids_for_type_wraps_a_failing_read() -> None:
    """The manager's own error type, like every other read here."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many_from_other_collection.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_object_ids_for_type(mgr, TYPE_ID)


# --------------------------------------------- handle_multi_data_sections ------------------------------------------- #
# The pure decide-and-apply half lives in cmdb.manager.types_mds_helper and is tested there; what is
# pinned here is the manager's own part: which objects it reads, with which projection, in which
# batches, and that it yields the changed ones instead of collecting them


def _mds_object(public_id: int, section_id: str, rows: list[list[dict[str, Any]]]) -> CmdbObject:
    """A CmdbObject carrying one MDS section, built the way a projected read hands it over."""
    return CmdbObject.from_data({
        CmdbObjectKey.PUBLIC_ID.value: public_id,
        CmdbObjectKey.TYPE_ID.value: TYPE_ID,
        CmdbObjectKey.AUTHOR_ID.value: 1,
        CmdbObjectKey.MULTI_DATA_SECTIONS.value: [_mds_section(section_id, rows)],
    })


def _old_type(section_fields: list[str], section_type: str = SectionType.MDS_SECTION.value) -> CmdbType:
    """A stored CmdbType carrying one section with the given fields."""
    return CmdbType.from_data({
        TypeSchemaKey.PUBLIC_ID.value: TYPE_ID,
        'name': 'a-type',
        TypeSchemaKey.LABEL.value: 'A Type',
        'author_id': 1,
        'version': '1.0.0',
        'active': True,
        TypeSchemaKey.FIELDS.value: [
            {FieldKey.NAME.value: name, FieldKey.TYPE.value: FieldType.TEXT.value}
            for name in section_fields
        ],
        TypeSchemaKey.RENDER_META.value: {
            'icon': 'fa-cube',
            'externals': [],
            'summary': {TypeSchemaKey.FIELDS.value: section_fields},
            TypeSchemaKey.SECTIONS.value: [{
                SectionKey.TYPE.value: section_type,
                SectionKey.NAME.value: SECTION_ID,
                SectionKey.LABEL.value: 'Section',
                SectionKey.FIELDS.value: section_fields,
            }],
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    })


def _updated_type_doc(
        section_fields: list[str] | None,
        field_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    An updated-type document; `section_fields=None` means the MDS section itself was removed
    """
    all_fields: list[str] = section_fields or []
    types: dict[str, str] = field_types or {}
    sections: list[dict[str, Any]] = [] if section_fields is None else [{
        SectionKey.TYPE.value: SectionType.MDS_SECTION.value,
        SectionKey.NAME.value: SECTION_ID,
        SectionKey.FIELDS.value: section_fields,
    }]

    return {
        TypeSchemaKey.FIELDS.value: [
            {FieldKey.NAME.value: name, FieldKey.TYPE.value: types.get(name, FieldType.TEXT.value)}
            for name in all_fields
        ],
        TypeSchemaKey.RENDER_META.value: {TypeSchemaKey.SECTIONS.value: sections},
    }


def _propagating_manager(objects: list[CmdbObject], object_ids: list[int] | None = None) -> MagicMock:
    """A MagicMock TypesManager whose two reads answer with the given objects."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_object_ids_for_type.return_value = (
        object_ids if object_ids is not None else [obj.public_id for obj in objects]
    )
    mgr.get_objects_for_type.side_effect = lambda *_args, public_ids=None, **_kwargs: [
        obj for obj in objects if public_ids is None or obj.public_id in public_ids
    ]

    return mgr


def test_handle_multi_data_sections_yields_the_changed_objects() -> None:
    """An added field reaches every row of the objects carrying the section."""
    changed = _mds_object(1, SECTION_ID, [[_entry('a', 1)]])
    mgr = _propagating_manager([changed])

    batches = list(TypesManager.handle_multi_data_sections(
        mgr, _old_type(['a']), _updated_type_doc(['a', 'b']),
    ))

    assert batches == [[changed]]
    assert _names(_row_data(changed.multi_data_sections[0], 0)) == ['a', 'b']


def test_handle_multi_data_sections_reads_only_the_affected_sections() -> None:
    """The id read is narrowed to the sections the edit touches - other objects never load"""
    mgr = _propagating_manager([])

    list(TypesManager.handle_multi_data_sections(mgr, _old_type(['a']), _updated_type_doc(['a', 'b'])))

    assert mgr.get_object_ids_for_type.call_args.kwargs['section_ids'] == [SECTION_ID]


def test_handle_multi_data_sections_reads_only_the_projected_keys() -> None:
    """A type's `fields` list - usually the bulk of an object - stays out of the read"""
    mgr = _propagating_manager([_mds_object(1, SECTION_ID, [[_entry('a')]])])

    list(TypesManager.handle_multi_data_sections(mgr, _old_type(['a']), _updated_type_doc(['a', 'b'])))

    assert mgr.get_objects_for_type.call_args.kwargs['projection'] is MDS_OBJECT_PROJECTION


def test_handle_multi_data_sections_batches_its_reads_and_yields(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The propagation is bounded: one batch is read, yielded and written before the next is read

    That is what keeps a type with many objects from becoming one unbounded read and one unbounded
    bulk write.
    """
    monkeypatch.setattr(f'{MGR_PATH}.MDS_PROPAGATION_BATCH_SIZE', 2)
    objects = [_mds_object(public_id, SECTION_ID, [[_entry('a')]]) for public_id in (1, 2, 3)]
    mgr = _propagating_manager(objects)

    batches = list(TypesManager.handle_multi_data_sections(
        mgr, _old_type(['a']), _updated_type_doc(['a', 'b']),
    ))

    assert [[obj.public_id for obj in batch] for batch in batches] == [[1, 2], [3]]
    assert mgr.get_objects_for_type.call_count == 2


def test_handle_multi_data_sections_yields_nothing_when_no_object_changed() -> None:
    """An object that already carries the field is not written again"""
    mgr = _propagating_manager([_mds_object(1, SECTION_ID, [[_entry('a'), _entry('b')]])])

    assert list(TypesManager.handle_multi_data_sections(
        mgr, _old_type(['a']), _updated_type_doc(['a', 'b']),
    )) == []


def test_handle_multi_data_sections_reads_nothing_for_an_unchanged_type() -> None:
    """A pure metadata edit must not touch the object collection at all"""
    mgr = _propagating_manager([])

    assert list(TypesManager.handle_multi_data_sections(
        mgr, _old_type(['a']), _updated_type_doc(['a']),
    )) == []
    mgr.get_object_ids_for_type.assert_not_called()


def test_handle_multi_data_sections_drops_a_removed_section() -> None:
    """
    A section the edit no longer declares is removed from the objects

    Before 2026-09-09 it was skipped, so every object kept the rows of a section its type did not
    have - invisible to every read and impossible to edit.
    """
    obj = _mds_object(1, SECTION_ID, [[_entry('a', 'kept value')]])
    mgr = _propagating_manager([obj])

    batches = list(TypesManager.handle_multi_data_sections(mgr, _old_type(['a']), _updated_type_doc(None)))

    assert batches == [[obj]]
    assert obj.multi_data_sections == []


def test_handle_multi_data_sections_wraps_a_failing_read_as_mds_error() -> None:
    """The propagation's own error type, so the route can report it separately from the type write"""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_object_ids_for_type.side_effect = TypesManagerGetError('boom')

    with pytest.raises(TypesManagerUpdateMDSError):
        list(TypesManager.handle_multi_data_sections(mgr, _old_type(['a']), _updated_type_doc(['a', 'b'])))


def test_handle_multi_data_sections_wraps_an_unexpected_error_as_mds_error() -> None:
    """Anything else surfaces the same way rather than escaping the manager"""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_object_ids_for_type.side_effect = RuntimeError('boom')

    with pytest.raises(TypesManagerUpdateMDSError):
        list(TypesManager.handle_multi_data_sections(mgr, _old_type(['a']), _updated_type_doc(['a', 'b'])))


def test_handle_multi_data_sections_survives_a_payload_without_render_meta() -> None:
    """
    A malformed payload costs the propagation, not the data

    It used to raise a KeyError, which the route reported as "the Type got updated but the MDS
    updates failed" - a 400 for a type that was already written. And now that a missing section means
    "removed", a payload describing no sections at all must not be read as "every section was
    removed": that would drop the MDS rows of every object of the type.
    """
    mgr = _propagating_manager([])

    assert list(TypesManager.handle_multi_data_sections(mgr, _old_type(['a']), {})) == []
    mgr.get_object_ids_for_type.assert_not_called()


# ------------------------------------------------- check_special_type_exists ---------------------------------------- #

def test_check_special_type_exists_reflects_lookup() -> None:
    """Returns True when a type with the special_type marker exists, False otherwise."""
    mgr = MagicMock(spec=TypesManager)
    mgr._special_type_value = TypesManager._special_type_value

    mgr.get_one_by.return_value = {TypeSchemaKey.PUBLIC_ID.value: 1}
    assert TypesManager.check_special_type_exists(mgr, SpecialType.SUBNET) is True

    mgr.get_one_by.return_value = None
    assert TypesManager.check_special_type_exists(mgr, SpecialType.SUBNET) is False


def test_check_special_type_exists_queries_the_marker_by_value() -> None:
    """The criteria carry plain strings, like every other query in this manager."""
    mgr = MagicMock(spec=TypesManager)
    mgr._special_type_value = TypesManager._special_type_value
    mgr.get_one_by.return_value = None

    TypesManager.check_special_type_exists(mgr, SpecialType.SUBNET)

    assert mgr.get_one_by.call_args.args[0] == {
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
    mgr = MagicMock(spec=TypesManager)
    mgr._special_type_value = TypesManager._special_type_value
    mgr.get_one_by.return_value = None

    TypesManager.check_special_type_exists(mgr, marker)

    assert mgr.get_one_by.call_args.args[0] == {
        TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.SUBNET.value,
    }


@pytest.mark.parametrize('marker', [SpecialType.RACK, SpecialType.RACK.value],
                         ids=['member', 'string'])
def test_get_type_ids_of_special_type_accepts_a_member_or_a_string(marker: Any) -> None:
    """Same two shapes, same query - the id read is used by the Rack and Cable paths"""
    mgr = MagicMock(spec=TypesManager)
    mgr._special_type_value = TypesManager._special_type_value
    mgr.get_distinct.return_value = []

    TypesManager.get_type_ids_of_special_type(mgr, marker)

    assert mgr.get_distinct.call_args.args[1] == {
        TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.RACK.value,
    }


def test_check_special_type_exists_wraps_a_failing_lookup() -> None:
    """
    It used to leak the BaseManager error

    The class promises that every public method answers with a TypesManager* error, and a caller
    handling only those would have seen an unhandled BaseManagerGetError.
    """
    mgr = MagicMock(spec=TypesManager)
    mgr._special_type_value = TypesManager._special_type_value
    mgr.get_one_by.side_effect = BaseManagerGetError('db down')

    with pytest.raises(TypesManagerGetError):
        TypesManager.check_special_type_exists(mgr, SpecialType.SUBNET)


# ------------------------------------------------------ read helpers ------------------------------------------------ #

def test_get_all_types_hydrates_each_raw_row() -> None:
    """Each raw row from get_many is mapped through CmdbType.from_data."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many.return_value = [{'public_id': 1}, {'public_id': 2}]

    with patch(f'{MGR_PATH}.CmdbType') as cmdb_type:
        cmdb_type.from_data.side_effect = lambda raw: ('hydrated', raw['public_id'])
        result = TypesManager.get_all_types(mgr)

    assert result == [('hydrated', 1), ('hydrated', 2)]


def test_get_all_types_defaults_to_descending() -> None:
    """Without an explicit direction the BaseManager default (-1) is forwarded."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many.return_value = []

    TypesManager.get_all_types(mgr)

    mgr.get_many.assert_called_once_with(direction=CmdbDAO.DAO_DESCENDING)


def test_get_all_types_forwards_the_requested_direction() -> None:
    """An explicit ascending direction reaches get_many (used by the type export)."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many.return_value = []

    TypesManager.get_all_types(mgr, direction=CmdbDAO.DAO_ASCENDING)

    mgr.get_many.assert_called_once_with(direction=CmdbDAO.DAO_ASCENDING)


def test_get_types_by_forwards_sort_direction_and_filter() -> None:
    """direction binds to the sort order instead of being swallowed as a query filter field."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many.return_value = []
    criteria = {'public_id': {'$in': [1, 2]}}  # the shape the type-export route sends

    TypesManager.get_types_by(mgr, sort='public_id', direction=CmdbDAO.DAO_ASCENDING, **criteria)

    mgr.get_many.assert_called_once_with(
        sort='public_id', direction=CmdbDAO.DAO_ASCENDING, **criteria
    )


def test_get_types_by_defaults_to_descending() -> None:
    """Without an explicit direction the BaseManager default (-1) is forwarded."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many.return_value = []

    TypesManager.get_types_by(mgr)

    mgr.get_many.assert_called_once_with(sort='public_id', direction=CmdbDAO.DAO_DESCENDING)


# ----------------------------------------------------- error wrapping ----------------------------------------------- #

def test_insert_type_wraps_unexpected_error() -> None:
    """A failure in the underlying insert surfaces as TypesManagerInsertError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.insert.side_effect = RuntimeError('boom')

    with pytest.raises(TypesManagerInsertError):
        TypesManager.insert_type(mgr, {TypeSchemaKey.NAME.value: 'x'})


def test_update_type_wraps_unexpected_error() -> None:
    """A failure in the underlying update surfaces as TypesManagerUpdateError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.update.side_effect = RuntimeError('boom')

    with pytest.raises(TypesManagerUpdateError):
        TypesManager.update_type(mgr, 1, {TypeSchemaKey.NAME.value: 'x'})


def test_update_type_pins_the_document_identity() -> None:
    """A payload carrying a different public_id cannot rewrite the stored id."""
    mgr = MagicMock(spec=TypesManager)
    mgr._as_stored_type_dict.return_value = {TypeSchemaKey.PUBLIC_ID.value: 99, TypeSchemaKey.NAME.value: 'x'}

    TypesManager.update_type(mgr, 7, {TypeSchemaKey.PUBLIC_ID.value: 99})

    _, kwargs = mgr.update.call_args
    assert kwargs['criteria'] == {TypeSchemaKey.PUBLIC_ID.value: 7}
    assert kwargs['data'][TypeSchemaKey.PUBLIC_ID.value] == 7


def test_update_type_returns_the_update_result() -> None:
    """The UpdateResult is passed through so callers can read matched_count."""
    mgr = MagicMock(spec=TypesManager)
    mgr._as_stored_type_dict.return_value = {TypeSchemaKey.NAME.value: 'x'}
    update_result = SimpleNamespace(matched_count=0, modified_count=0)
    mgr.update.return_value = update_result

    assert TypesManager.update_type(mgr, 7, {}) is update_result


def test_update_type_field_sets_only_that_key() -> None:
    """A single-field update $sets one key and leaves the rest of the document alone."""
    mgr = MagicMock(spec=TypesManager)

    TypesManager.update_type_field(mgr, 7, TypeSchemaKey.CI_EXPLORER_LABEL.value, 'name')

    _, kwargs = mgr.update.call_args
    assert kwargs['criteria'] == {TypeSchemaKey.PUBLIC_ID.value: 7}
    assert kwargs['data'] == {TypeSchemaKey.CI_EXPLORER_LABEL.value: 'name'}


def test_update_type_field_wraps_unexpected_error() -> None:
    """A failure in the underlying update surfaces as TypesManagerUpdateError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.update.side_effect = RuntimeError('boom')

    with pytest.raises(TypesManagerUpdateError):
        TypesManager.update_type_field(mgr, 7, TypeSchemaKey.CI_EXPLORER_LABEL.value, 'name')


def test_find_types_wraps_unexpected_error() -> None:
    """A failure in the underlying find surfaces as TypesManagerGetError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.find.side_effect = RuntimeError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.find_types(mgr, {'public_id': 1})


def test_get_objects_for_type_wraps_unexpected_error() -> None:
    """A failure fetching objects of a type surfaces as TypesManagerGetError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many_from_other_collection.side_effect = RuntimeError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_objects_for_type(mgr, 1)


def test_get_types_by_wraps_unexpected_error() -> None:
    """A failure in get_types_by surfaces as TypesManagerGetError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many.side_effect = RuntimeError('boom')

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
    mgr = MagicMock(spec=TypesManager)
    mgr.get_one.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_type(mgr, 1)


def test_get_type_returns_the_raw_document() -> None:
    """get_type hands back the stored document untouched, without hydrating it."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_one.return_value = {TypeSchemaKey.PUBLIC_ID.value: 1}

    assert TypesManager.get_type(mgr, 1) == {TypeSchemaKey.PUBLIC_ID.value: 1}


def test_get_type_instance_hydrates_the_document() -> None:
    """get_type_instance maps the stored document through CmdbType.from_data."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_one.return_value = {TypeSchemaKey.PUBLIC_ID.value: 1}

    with patch(f'{MGR_PATH}.CmdbType') as cmdb_type:
        cmdb_type.from_data.return_value = 'hydrated'

        assert TypesManager.get_type_instance(mgr, 1) == 'hydrated'


@pytest.mark.parametrize('method', ['get_type', 'get_type_instance'], ids=['dict', 'instance'])
def test_missing_type_is_none_in_both_modes(method: str) -> None:
    """An unknown public_id is reported as None by both read methods, never as an error."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_one.return_value = None

    assert getattr(TypesManager, method)(mgr, 9999) is None


def test_get_type_instance_wraps_hydration_error() -> None:
    """A CmdbType.from_data failure surfaces as TypesManagerGetError, not as the raw model error."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_one.return_value = {TypeSchemaKey.PUBLIC_ID.value: 1}

    with patch(f'{MGR_PATH}.CmdbType') as cmdb_type:
        cmdb_type.from_data.side_effect = RuntimeError('broken document')

        with pytest.raises(TypesManagerGetError):
            TypesManager.get_type_instance(mgr, 1)


def test_delete_type_wraps_delete_error() -> None:
    """A BaseManagerDeleteError from delete surfaces as TypesManagerDeleteError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.delete.side_effect = BaseManagerDeleteError('boom')

    with pytest.raises(TypesManagerDeleteError):
        TypesManager.delete_type(mgr, 5)


# -------------------------------------- error wrapping: init / read / MDS ------------------------------------------- #
def test_init_wraps_super_failure_as_init_error() -> None:
    """A failure while constructing the base manager (None dbm) surfaces as TypesManagerInitError."""
    with pytest.raises(TypesManagerInitError):
        TypesManager(None)


def test_get_new_type_public_id_wraps_get_error() -> None:
    """A BaseManagerGetError from the id counter surfaces as TypesManagerGetError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_next_public_id.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_new_type_public_id(mgr)


def test_iterate_wraps_failure_as_iteration_error() -> None:
    """A failure in the aggregation surfaces as TypesManagerIterationError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.iterate_query.side_effect = RuntimeError('boom')

    with pytest.raises(TypesManagerIterationError):
        TypesManager.iterate(mgr, MagicMock())


def test_get_all_types_wraps_base_get_error() -> None:
    """A BaseManagerGetError from the fetch surfaces as TypesManagerGetError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_all_types(mgr)


def test_get_all_types_wraps_unexpected_error() -> None:
    """Any other failure while hydrating types surfaces as TypesManagerGetError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many.side_effect = RuntimeError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_all_types(mgr)


def test_get_objects_for_type_wraps_base_get_error() -> None:
    """A BaseManagerGetError from the object fetch surfaces as TypesManagerGetError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_many_from_other_collection.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_objects_for_type(mgr, 1)


# ------------------------------------------------- get_existing_type_ids -------------------------------------------- #

def test_get_existing_type_ids_returns_the_matching_ids() -> None:
    """The distinct lookup's result is handed back as a set, so callers can test membership."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_distinct.return_value = [3, 7]

    assert TypesManager.get_existing_type_ids(mgr, [3, 7, 9]) == {3, 7}

    call = mgr.get_distinct.call_args
    assert call.args[0] == TypeSchemaKey.PUBLIC_ID.value
    assert call.args[1] == {TypeSchemaKey.PUBLIC_ID.value: {'$in': [3, 7, 9]}}


def test_get_existing_type_ids_skips_the_query_for_an_empty_list() -> None:
    """Nothing to resolve means no database round trip at all."""
    mgr = MagicMock(spec=TypesManager)

    assert TypesManager.get_existing_type_ids(mgr, []) == set()
    mgr.get_distinct.assert_not_called()


def test_get_existing_type_ids_wraps_get_error() -> None:
    """A failing distinct query surfaces as the manager's own error type."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_distinct.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_existing_type_ids(mgr, [1])


# ------------------------------------------ get_type_ids_of_special_type -------------------------------------------- #

def test_get_type_ids_of_special_type_queries_the_marker() -> None:
    """One distinct on the indexed public_id - no type document is loaded to answer 'which type is the Rack'."""
    mgr = MagicMock(spec=TypesManager)
    mgr._special_type_value = TypesManager._special_type_value
    mgr.get_distinct.return_value = [9551]

    assert TypesManager.get_type_ids_of_special_type(mgr, SpecialType.RACK) == [9551]

    call = mgr.get_distinct.call_args
    assert call.args[0] == TypeSchemaKey.PUBLIC_ID.value
    assert call.args[1] == {TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.RACK.value}


def test_get_type_ids_of_special_type_is_empty_when_the_marker_is_unused() -> None:
    """An installation without the special type yields an empty list, not None."""
    mgr = MagicMock(spec=TypesManager)
    mgr._special_type_value = TypesManager._special_type_value
    mgr.get_distinct.return_value = []

    assert TypesManager.get_type_ids_of_special_type(mgr, SpecialType.RACK) == []


def test_get_type_ids_of_special_type_drops_non_integer_values() -> None:
    """The ids go straight into a '$nin' of ints, so a drifted value must not travel with them."""
    mgr = MagicMock(spec=TypesManager)
    mgr._special_type_value = TypesManager._special_type_value
    mgr.get_distinct.return_value = [9551, None, 'garbage']

    assert TypesManager.get_type_ids_of_special_type(mgr, SpecialType.RACK) == [9551]


def test_get_type_ids_of_special_type_wraps_get_error() -> None:
    """A failing distinct query surfaces as the manager's own error type."""
    mgr = MagicMock(spec=TypesManager)
    mgr._special_type_value = TypesManager._special_type_value
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
    mgr = MagicMock(spec=TypesManager)
    mgr.get_distinct.return_value = [9552]

    assert TypesManager.get_type_ids_with_location_field(mgr) == [9552]

    call = mgr.get_distinct.call_args
    assert call.args[0] == TypeSchemaKey.PUBLIC_ID.value
    assert call.args[1] == {
        TypeSchemaKey.FIELDS.value: {'$elemMatch': {FieldKey.TYPE.value: FieldType.LOCATION.value}},
    }


def test_get_type_ids_with_location_field_is_empty_when_no_type_declares_one() -> None:
    """An empty list, which the picker turns into an '$in' matching nothing - nothing is mountable."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_distinct.return_value = []

    assert TypesManager.get_type_ids_with_location_field(mgr) == []


def test_get_type_ids_with_location_field_drops_non_integer_values() -> None:
    """The ids go straight into an '$in' of ints, so a drifted value must not travel with them."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_distinct.return_value = [9552, None, 'garbage']

    assert TypesManager.get_type_ids_with_location_field(mgr) == [9552]


def test_get_type_ids_with_location_field_wraps_get_error() -> None:
    """A failing distinct query surfaces as the manager's own error type."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_distinct.side_effect = BaseManagerGetError('boom')

    with pytest.raises(TypesManagerGetError):
        TypesManager.get_type_ids_with_location_field(mgr)
