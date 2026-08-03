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
Unit tests for the MDS-field propagation methods of cmdb.manager.types_manager

These methods mutate a CmdbObject's multi_data_sections when a CmdbType's MDS section gains or
loses a field. The canonical MDS shape nests field rows under section['values'][*]['data'] (each
row a list of {name, value, type} entries) - these tests pin that the methods operate on that
level, not on a 'data' key placed directly on the section.

The manager is never constructed (its __init__ would build a real DB connection); the methods are
exercised on a MagicMock-typed ``self``. Schema dict keys are referenced via the model key enums
per the no-magic-values rule
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.type_model import CmdbType, FieldKey, FieldType, SectionType, SectionKey, TypeSchemaKey
from cmdb.models.object_model import CmdbObjectMdsKey, CmdbObjectFieldKey, CmdbObjectMdsRowKey
from cmdb.manager.types_manager import TypesManager
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


# -------------------------------------------------- create_mds_field_entries ---------------------------------------- #

def test_create_mds_field_entries_appends_to_every_row() -> None:
    """A newly added field is appended (value None, mapped type) to the data of each row."""
    section: dict[str, Any] = _mds_section(SECTION_ID, [[_entry('a', 1)], [_entry('a', 2)]])
    field_type_map: dict[str, str] = {'a': FieldType.TEXT.value, 'b': FieldType.NUMBER.value}

    TypesManager.create_mds_field_entries(MagicMock(), ['b'], section, field_type_map)

    for row_index in (0, 1):
        added: dict[str, Any] = _row_data(section, row_index)[-1]
        assert _names(_row_data(section, row_index)) == ['a', 'b']
        assert added[CmdbObjectFieldKey.VALUE.value] is None
        assert added[CmdbObjectFieldKey.TYPE.value] == FieldType.NUMBER.value


def test_create_mds_field_entries_is_idempotent() -> None:
    """Re-adding a field already present in a row does not duplicate it."""
    section: dict[str, Any] = _mds_section(SECTION_ID, [[_entry('a', 1)]])

    TypesManager.create_mds_field_entries(MagicMock(), ['a'], section, {'a': FieldType.TEXT.value})

    assert _names(_row_data(section, 0)) == ['a']


def test_create_mds_field_entries_falls_back_to_text_type() -> None:
    """A field missing from the type map is stored with the 'text' fallback type."""
    section: dict[str, Any] = _mds_section(SECTION_ID, [[]])

    TypesManager.create_mds_field_entries(MagicMock(), ['c'], section, {})

    assert _row_data(section, 0)[0][CmdbObjectFieldKey.TYPE.value] == FieldType.TEXT.value


# -------------------------------------------------- delete_mds_field_entries ---------------------------------------- #

def test_delete_mds_field_entries_removes_from_every_row() -> None:
    """A removed field is stripped from the data of each row, leaving the rest intact."""
    section: dict[str, Any] = _mds_section(
        SECTION_ID,
        [[_entry('a', 1), _entry('b', 2)], [_entry('a', 3), _entry('b', 4)]],
    )

    TypesManager.delete_mds_field_entries(MagicMock(), ['b'], section)

    assert _names(_row_data(section, 0)) == ['a']
    assert _names(_row_data(section, 1)) == ['a']


# -------------------------------------------------- update_multi_data_fields ---------------------------------------- #

def _manager_with_real_entry_methods(objects: list[Any]) -> MagicMock:
    """Builds a MagicMock TypesManager whose entry-helpers run the real implementations."""
    manager = MagicMock(spec=TypesManager)
    manager.get_objects_for_type.return_value = objects
    manager.create_mds_field_entries.side_effect = lambda *args: TypesManager.create_mds_field_entries(
        manager, *args,
    )
    manager.delete_mds_field_entries.side_effect = lambda *args: TypesManager.delete_mds_field_entries(
        manager, *args,
    )

    return manager


def test_update_multi_data_fields_routes_changes_by_section_id() -> None:
    """Added fields land on the matching section's rows; only modified objects are returned."""
    target_type = SimpleNamespace(
        public_id=42,
        fields=[
            {FieldKey.NAME.value: 'a', FieldKey.TYPE.value: FieldType.TEXT.value},
            {FieldKey.NAME.value: 'b', FieldKey.TYPE.value: FieldType.NUMBER.value},
        ],
    )
    changed_object = SimpleNamespace(
        public_id=1, multi_data_sections=[_mds_section(SECTION_ID, [[_entry('a', 1)]])],
    )
    untouched_object = SimpleNamespace(
        public_id=2, multi_data_sections=[_mds_section(OTHER_SECTION_ID, [[_entry('a', 9)]])],
    )
    manager = _manager_with_real_entry_methods([changed_object, untouched_object])

    result = TypesManager.update_multi_data_fields(manager, target_type, {SECTION_ID: ['b']}, {})

    assert result == [changed_object]
    assert _names(_row_data(changed_object.multi_data_sections[0], 0)) == ['a', 'b']
    assert _names(_row_data(untouched_object.multi_data_sections[0], 0)) == ['a']


def test_update_multi_data_fields_returns_empty_when_no_section_matches() -> None:
    """An object whose sections are not in the add/delete maps is left unchanged and not returned."""
    target_type = SimpleNamespace(
        public_id=42, fields=[{FieldKey.NAME.value: 'a', FieldKey.TYPE.value: FieldType.TEXT.value}],
    )
    obj = SimpleNamespace(public_id=1, multi_data_sections=[_mds_section(OTHER_SECTION_ID, [[_entry('a', 1)]])])
    manager = _manager_with_real_entry_methods([obj])

    result = TypesManager.update_multi_data_fields(manager, target_type, {SECTION_ID: ['b']}, {})

    assert not result
    assert _names(_row_data(obj.multi_data_sections[0], 0)) == ['a']


# ------------------------------------------------------- fields_diff ------------------------------------------------ #

def test_fields_diff_reports_added_and_removed() -> None:
    """check_added=True yields names new to the list; check_added=False yields names dropped from it."""
    assert set(TypesManager.fields_diff(MagicMock(), ['a', 'b'], ['a', 'b', 'c'], check_added=True)) == {'c'}
    assert set(TypesManager.fields_diff(MagicMock(), ['a', 'b'], ['a'], check_added=False)) == {'b'}


# ------------------------------------------------- check_special_type_exists ---------------------------------------- #

def test_check_special_type_exists_reflects_lookup() -> None:
    """Returns True when a type with the special_type marker exists, False otherwise."""
    mgr = MagicMock(spec=TypesManager)

    mgr.get_one_by.return_value = {TypeSchemaKey.PUBLIC_ID.value: 1}
    assert TypesManager.check_special_type_exists(mgr, 'SUBNET') is True

    mgr.get_one_by.return_value = None
    assert TypesManager.check_special_type_exists(mgr, 'SUBNET') is False


# ------------------------------------------------ handle_multi_data_sections ---------------------------------------- #

def _old_type_with_mds_section(section_name: str, fields: list[str], section_type: str) -> SimpleNamespace:
    """Builds a CmdbType stand-in exposing one render_meta section with the given attributes."""
    section = SimpleNamespace(type=section_type, name=section_name, fields=fields)
    return SimpleNamespace(render_meta=SimpleNamespace(sections=[section]))


def _updated_type_doc(section_name: str, fields: list[str], section_type: str) -> dict[str, Any]:
    """Builds an updated-type dict carrying one render_meta section."""
    return {
        TypeSchemaKey.RENDER_META.value: {
            TypeSchemaKey.SECTIONS.value: [{
                SectionKey.TYPE.value: section_type,
                SectionKey.NAME.value: section_name,
                SectionKey.FIELDS.value: fields,
            }],
        },
    }


def _manager_with_real_fields_diff() -> MagicMock:
    """Builds a MagicMock TypesManager whose fields_diff runs the real implementation."""
    mgr = MagicMock(spec=TypesManager)
    mgr.fields_diff.side_effect = lambda initial, new, check_added=False: TypesManager.fields_diff(
        mgr, initial, new, check_added,
    )
    return mgr


def test_handle_multi_data_sections_routes_added_and_deleted_fields() -> None:
    """Per MDS section, the field diff is forwarded to update_multi_data_fields keyed by section name."""
    mgr = _manager_with_real_fields_diff()
    sentinel = [object()]
    mgr.update_multi_data_fields.return_value = sentinel
    old_type = _old_type_with_mds_section('sec', ['a', 'gone'], SectionType.MDS_SECTION.value)
    updated_type = _updated_type_doc('sec', ['a', 'added'], SectionType.MDS_SECTION.value)

    result = TypesManager.handle_multi_data_sections(mgr, old_type, updated_type)

    assert result is sentinel
    forwarded_old, added_fields, deleted_fields = mgr.update_multi_data_fields.call_args.args
    assert forwarded_old is old_type
    assert added_fields == {'sec': ['added']}
    assert deleted_fields == {'sec': ['gone']}


def test_handle_multi_data_sections_returns_empty_when_no_field_changes() -> None:
    """An MDS section whose fields are unchanged produces no update call and an empty result."""
    mgr = _manager_with_real_fields_diff()
    old_type = _old_type_with_mds_section('sec', ['a', 'b'], SectionType.MDS_SECTION.value)
    updated_type = _updated_type_doc('sec', ['a', 'b'], SectionType.MDS_SECTION.value)

    assert TypesManager.handle_multi_data_sections(mgr, old_type, updated_type) == []
    mgr.update_multi_data_fields.assert_not_called()


def test_handle_multi_data_sections_skips_non_mds_sections() -> None:
    """A regular (non-MDS) section is ignored even when its fields differ."""
    mgr = _manager_with_real_fields_diff()
    old_type = _old_type_with_mds_section('sec', ['a'], SectionType.SECTION.value)
    updated_type = _updated_type_doc('sec', ['a', 'b'], SectionType.SECTION.value)

    assert TypesManager.handle_multi_data_sections(mgr, old_type, updated_type) == []
    mgr.update_multi_data_fields.assert_not_called()


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


def test_update_multi_data_fields_narrows_fetch_to_affected_sections() -> None:
    """The object fetch is narrowed to exactly the section_ids touched by the add/delete maps."""
    target_type = SimpleNamespace(
        public_id=42, fields=[{FieldKey.NAME.value: 'a', FieldKey.TYPE.value: FieldType.TEXT.value}],
    )
    manager = _manager_with_real_entry_methods([])

    TypesManager.update_multi_data_fields(manager, target_type, {SECTION_ID: ['b']}, {OTHER_SECTION_ID: ['c']})

    call = manager.get_objects_for_type.call_args
    assert call.args[0] == 42
    assert set(call.kwargs['section_ids']) == {SECTION_ID, OTHER_SECTION_ID}


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


def test_update_multi_data_fields_wraps_get_error() -> None:
    """A TypesManagerGetError while loading objects surfaces as TypesManagerUpdateError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_objects_for_type.side_effect = TypesManagerGetError('boom')

    with pytest.raises(TypesManagerUpdateError):
        TypesManager.update_multi_data_fields(mgr, SimpleNamespace(public_id=1), {SECTION_ID: ['f']}, {})


def test_update_multi_data_fields_wraps_unexpected_error() -> None:
    """Any other failure during MDS field mutation surfaces as TypesManagerUpdateError."""
    mgr = MagicMock(spec=TypesManager)
    mgr.get_objects_for_type.side_effect = RuntimeError('boom')

    with pytest.raises(TypesManagerUpdateError):
        TypesManager.update_multi_data_fields(mgr, SimpleNamespace(public_id=1), {SECTION_ID: ['f']}, {})


def test_handle_multi_data_sections_wraps_update_error_as_mds_error() -> None:
    """A TypesManagerUpdateError from the field update surfaces as TypesManagerUpdateMDSError."""
    mgr = _manager_with_real_fields_diff()
    mgr.update_multi_data_fields.side_effect = TypesManagerUpdateError('boom')
    old_type = _old_type_with_mds_section('sec', ['a'], SectionType.MDS_SECTION.value)
    updated_type = _updated_type_doc('sec', ['a', 'b'], SectionType.MDS_SECTION.value)

    with pytest.raises(TypesManagerUpdateMDSError):
        TypesManager.handle_multi_data_sections(mgr, old_type, updated_type)


def test_handle_multi_data_sections_wraps_unexpected_error_as_mds_error() -> None:
    """A malformed updated_type (no render_meta) surfaces as TypesManagerUpdateMDSError."""
    mgr = _manager_with_real_fields_diff()
    old_type = _old_type_with_mds_section('sec', ['a'], SectionType.MDS_SECTION.value)

    with pytest.raises(TypesManagerUpdateMDSError):
        TypesManager.handle_multi_data_sections(mgr, old_type, {})


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
