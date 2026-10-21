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
Unit tests for cmdb.database.updater.versions.updater_20260225

DB-free. The pure schema readers are called directly; the database-touching methods and the
orchestration get MagicMock managers, with the updater built via __new__ following the established
version-updater pattern.

Emphasis on the guards this migration exists to carry: only the projected type keys are fetched, a
type declaring no field names is never stripped, a definition with a broken field type still protects
its stored entries, the nested multi-data-section writes are skipped for a type that declares none,
and every write matches an untyped entry as absent/null/empty rather than only absent. The metadata
contract (creation_date / description) is covered by the shared parametrized test in
test_version_updaters.
"""
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.versions.updater_20260225 import (
    FIELD_NAME_KEY,
    FIELD_TYPE_KEY,
    FIELD_TYPE_UPDATE_PATH,
    MDS_DATA_PULL_PATH,
    MDS_DATA_QUERY_PATH,
    MDS_FIELD_TYPE_UPDATE_PATH,
    MDS_SECTION_TYPE,
    OBJECT_FIELDS_KEY,
    OBJECT_TYPE_ID_KEY,
    ROW_HAS_DATA_FILTER,
    SECTION_HAS_VALUES_FILTER,
    TYPE_PROJECTION,
    UNTYPED_MATCH,
    Update20260225,
    collect_field_names_by_type,
    collect_schema_field_names,
    declares_multi_data_section,
)
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 32

TEXT_FIELD: str = 'text-f96955e2'
REF_FIELD: str = 'ref-391f8254'
SECOND_TEXT_FIELD: str = 'text-2b7c19aa'


def _new_updater() -> Update20260225:
    """Builds the updater without its real __init__ and attaches mocked managers."""
    updater = Update20260225.__new__(Update20260225)
    updater.types_manager = MagicMock()
    updater.objects_manager = MagicMock()
    updater.settings_manager = MagicMock()

    return updater


# Sentinel so a parametrized None reaches the document as a real None instead of the default
_KEEP_DEFAULT: Any = object()

DEFAULT_FIELDS: list[dict[str, str]] = [
    {FIELD_NAME_KEY: TEXT_FIELD, FIELD_TYPE_KEY: 'text'},
    {FIELD_NAME_KEY: REF_FIELD, FIELD_TYPE_KEY: 'ref'},
]


def _type_doc(fields: Any = _KEEP_DEFAULT, sections: Any = _KEEP_DEFAULT) -> dict[str, Any]:
    """Builds a projected type document as load_type_plans receives it."""
    return {
        'public_id': TYPE_ID,
        'fields': DEFAULT_FIELDS if fields is _KEEP_DEFAULT else fields,
        'render_meta': {'sections': [{'type': 'section'}] if sections is _KEEP_DEFAULT else sections},
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                            collect_schema_field_names                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_collect_schema_field_names_returns_every_declared_name() -> None:
    """Every field name of the schema is collected"""
    assert collect_schema_field_names(_type_doc()) == {TEXT_FIELD, REF_FIELD}


def test_collect_schema_field_names_keeps_a_name_whose_type_is_broken() -> None:
    """A definition with a missing / empty type still contributes its name, so it is never stripped"""
    names = collect_schema_field_names(_type_doc(fields=[
        {FIELD_NAME_KEY: TEXT_FIELD},
        {FIELD_NAME_KEY: REF_FIELD, FIELD_TYPE_KEY: ''},
    ]))

    assert names == {TEXT_FIELD, REF_FIELD}


@pytest.mark.parametrize('fields', [None, [], [{}], ['not-a-dict'], [{FIELD_NAME_KEY: ''}], [{FIELD_NAME_KEY: 7}]])
def test_collect_schema_field_names_skips_unusable_entries(fields: list[Any] | None) -> None:
    """A missing 'fields' list and any entry without a usable name yield no names"""
    assert collect_schema_field_names(_type_doc(fields=fields)) == set()


def test_collect_schema_field_names_tolerates_a_type_without_fields_key() -> None:
    """A type document that carries no 'fields' key at all does not raise"""
    assert collect_schema_field_names({'public_id': TYPE_ID}) == set()


# -------------------------------------------------------------------------------------------------------------------- #
#                                            collect_field_names_by_type                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_collect_field_names_by_type_groups_names() -> None:
    """Names are grouped by the field type their definition declares"""
    grouped = collect_field_names_by_type(_type_doc(fields=[
        {FIELD_NAME_KEY: TEXT_FIELD, FIELD_TYPE_KEY: 'text'},
        {FIELD_NAME_KEY: SECOND_TEXT_FIELD, FIELD_TYPE_KEY: 'text'},
        {FIELD_NAME_KEY: REF_FIELD, FIELD_TYPE_KEY: 'ref'},
    ]))

    assert grouped == {'text': [TEXT_FIELD, SECOND_TEXT_FIELD], 'ref': [REF_FIELD]}


@pytest.mark.parametrize('field', [
    {FIELD_NAME_KEY: TEXT_FIELD},
    {FIELD_NAME_KEY: TEXT_FIELD, FIELD_TYPE_KEY: None},
    {FIELD_NAME_KEY: TEXT_FIELD, FIELD_TYPE_KEY: ''},
    {FIELD_NAME_KEY: TEXT_FIELD, FIELD_TYPE_KEY: 5},
    {FIELD_TYPE_KEY: 'text'},
    {FIELD_NAME_KEY: '', FIELD_TYPE_KEY: 'text'},
    'not-a-dict',
])
def test_collect_field_names_by_type_skips_unusable_definitions(field: Any) -> None:
    """A definition without a usable name AND a non-empty string type contributes nothing"""
    assert not collect_field_names_by_type(_type_doc(fields=[field]))


# -------------------------------------------------------------------------------------------------------------------- #
#                                           declares_multi_data_section                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_declares_multi_data_section_true_for_an_mds_section() -> None:
    """A schema carrying a multi-data-section is detected"""
    assert declares_multi_data_section(_type_doc(sections=[{'type': 'section'}, {'type': MDS_SECTION_TYPE}])) is True


@pytest.mark.parametrize('sections', [None, [], [{'type': 'section'}], [{'type': 'ref-section'}], ['not-a-dict'], [{}]])
def test_declares_multi_data_section_false_without_one(sections: list[Any] | None) -> None:
    """Any other section list means the type's objects carry no multi-data-section rows"""
    assert declares_multi_data_section(_type_doc(sections=sections)) is False


@pytest.mark.parametrize('type_doc', [{'public_id': TYPE_ID}, {'render_meta': None}, {'render_meta': 'broken'}])
def test_declares_multi_data_section_tolerates_a_missing_render_meta(type_doc: dict[str, Any]) -> None:
    """A type document without a usable render_meta does not raise"""
    assert declares_multi_data_section(type_doc) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 load_type_plans                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_type_plans_fetches_only_the_projected_keys() -> None:
    """Type documents are read with the narrow projection, not in full"""
    updater = _new_updater()
    updater.types_manager.find.return_value = []

    updater.load_type_plans()

    updater.types_manager.find.assert_called_once_with(criteria={}, projection=TYPE_PROJECTION)


def test_load_type_plans_builds_one_plan_per_type() -> None:
    """Each usable type yields its id, declared names, grouping and multi-data-section flag"""
    updater = _new_updater()
    updater.types_manager.find.return_value = [_type_doc(sections=[{'type': MDS_SECTION_TYPE}])]

    assert updater.load_type_plans() == [{
        'type_id': TYPE_ID,
        'known_names': {TEXT_FIELD, REF_FIELD},
        'names_by_field_type': {'text': [TEXT_FIELD], 'ref': [REF_FIELD]},
        'has_mds': True,
    }]


@pytest.mark.parametrize('public_id', [None, 'not-an-int', 1.5])
def test_load_type_plans_skips_a_type_without_a_usable_public_id(public_id: Any) -> None:
    """A type that cannot be matched against any object is skipped instead of raising"""
    updater = _new_updater()
    broken = _type_doc()
    broken['public_id'] = public_id
    updater.types_manager.find.return_value = [broken]

    assert not updater.load_type_plans()


# -------------------------------------------------------------------------------------------------------------------- #
#                                             strip_undeclared_fields                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_strip_undeclared_fields_pulls_entries_the_schema_does_not_declare() -> None:
    """Entries whose name is not declared any more are pulled from the top-level fields list"""
    updater = _new_updater()

    updater.strip_undeclared_fields(TYPE_ID, {REF_FIELD, TEXT_FIELD}, has_mds=False)

    undeclared = {FIELD_NAME_KEY: {'$nin': [REF_FIELD, TEXT_FIELD]}}
    updater.objects_manager.update_many_raw.assert_called_once_with(
        filter_query={OBJECT_TYPE_ID_KEY: TYPE_ID, OBJECT_FIELDS_KEY: {'$elemMatch': undeclared}},
        update={'$pull': {OBJECT_FIELDS_KEY: undeclared}},
    )


def test_strip_undeclared_fields_also_pulls_from_multi_data_rows() -> None:
    """A type declaring a multi-data-section gets the nested pull, guarded against malformed shapes"""
    updater = _new_updater()

    updater.strip_undeclared_fields(TYPE_ID, {TEXT_FIELD}, has_mds=True)

    undeclared = {FIELD_NAME_KEY: {'$nin': [TEXT_FIELD]}}
    assert updater.objects_manager.update_many_raw.call_args_list[1] == call(
        filter_query={OBJECT_TYPE_ID_KEY: TYPE_ID, MDS_DATA_QUERY_PATH: {'$elemMatch': undeclared}},
        update={'$pull': {MDS_DATA_PULL_PATH: undeclared}},
        array_filters=[SECTION_HAS_VALUES_FILTER, ROW_HAS_DATA_FILTER],
    )


def test_strip_undeclared_fields_skips_the_nested_pull_without_an_mds_section() -> None:
    """Only one write is issued for a type that declares no multi-data-section"""
    updater = _new_updater()

    updater.strip_undeclared_fields(TYPE_ID, {TEXT_FIELD}, has_mds=True)
    mds_calls = updater.objects_manager.update_many_raw.call_count

    updater.objects_manager.reset_mock()
    updater.strip_undeclared_fields(TYPE_ID, {TEXT_FIELD}, has_mds=False)

    assert (mds_calls, updater.objects_manager.update_many_raw.call_count) == (2, 1)


def test_strip_undeclared_fields_does_nothing_when_no_name_is_declared() -> None:
    """An empty name set would strip every entry, so nothing is written at all"""
    updater = _new_updater()

    updater.strip_undeclared_fields(TYPE_ID, set(), has_mds=True)

    updater.objects_manager.update_many_raw.assert_not_called()


def test_strip_undeclared_fields_sorts_the_declared_names() -> None:
    """The name list is deterministic, so the same schema always issues the same query"""
    updater = _new_updater()

    updater.strip_undeclared_fields(TYPE_ID, {REF_FIELD, TEXT_FIELD, SECOND_TEXT_FIELD}, has_mds=False)

    pulled = updater.objects_manager.update_many_raw.call_args.kwargs['update']['$pull'][OBJECT_FIELDS_KEY]
    assert pulled[FIELD_NAME_KEY]['$nin'] == sorted([REF_FIELD, TEXT_FIELD, SECOND_TEXT_FIELD])


# -------------------------------------------------------------------------------------------------------------------- #
#                                              backfill_field_types                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_backfill_field_types_writes_the_schema_type_onto_untyped_entries() -> None:
    """One $set per field type, matching an entry whose type is absent, null or empty"""
    updater = _new_updater()

    updater.backfill_field_types(TYPE_ID, {'text': [TEXT_FIELD]}, has_mds=False)

    untyped = {FIELD_NAME_KEY: {'$in': [TEXT_FIELD]}, FIELD_TYPE_KEY: UNTYPED_MATCH}
    updater.objects_manager.update_many_raw.assert_called_once_with(
        filter_query={OBJECT_TYPE_ID_KEY: TYPE_ID, OBJECT_FIELDS_KEY: {'$elemMatch': untyped}},
        update={'$set': {FIELD_TYPE_UPDATE_PATH: 'text'}},
        array_filters=[{f'f.{FIELD_NAME_KEY}': {'$in': [TEXT_FIELD]}, f'f.{FIELD_TYPE_KEY}': UNTYPED_MATCH}],
    )


def test_backfill_field_types_matches_absent_null_and_empty_types() -> None:
    """The untyped match is '$in: [None, ""]' so null and empty stored types are filled too"""
    assert UNTYPED_MATCH == {'$in': [None, '']}


def test_backfill_field_types_also_writes_into_multi_data_rows() -> None:
    """A type declaring a multi-data-section gets the nested $set behind the traversal guards"""
    updater = _new_updater()

    updater.backfill_field_types(TYPE_ID, {'ref': [REF_FIELD]}, has_mds=True)

    untyped = {FIELD_NAME_KEY: {'$in': [REF_FIELD]}, FIELD_TYPE_KEY: UNTYPED_MATCH}
    entry_filter = {f'f.{FIELD_NAME_KEY}': {'$in': [REF_FIELD]}, f'f.{FIELD_TYPE_KEY}': UNTYPED_MATCH}
    assert updater.objects_manager.update_many_raw.call_args_list[1] == call(
        filter_query={OBJECT_TYPE_ID_KEY: TYPE_ID, MDS_DATA_QUERY_PATH: {'$elemMatch': untyped}},
        update={'$set': {MDS_FIELD_TYPE_UPDATE_PATH: 'ref'}},
        array_filters=[SECTION_HAS_VALUES_FILTER, ROW_HAS_DATA_FILTER, entry_filter],
    )


def test_backfill_field_types_issues_one_pair_per_field_type() -> None:
    """Two field types on a multi-data type mean four writes; without one, two"""
    updater = _new_updater()
    grouping = {'text': [TEXT_FIELD], 'ref': [REF_FIELD]}

    updater.backfill_field_types(TYPE_ID, grouping, has_mds=True)
    with_mds = updater.objects_manager.update_many_raw.call_count

    updater.objects_manager.reset_mock()
    updater.backfill_field_types(TYPE_ID, grouping, has_mds=False)

    assert (with_mds, updater.objects_manager.update_many_raw.call_count) == (4, 2)


def test_backfill_field_types_writes_nothing_for_an_empty_grouping() -> None:
    """A schema with no usable definition issues no write at all"""
    updater = _new_updater()

    updater.backfill_field_types(TYPE_ID, {}, has_mds=True)

    updater.objects_manager.update_many_raw.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                             normalise_object_fields                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_normalise_object_fields_strips_before_backfilling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undeclared entries are pulled first, so the backfill never looks at them"""
    updater = _new_updater()
    updater.types_manager.find.return_value = [_type_doc()]
    order: list[str] = []

    monkeypatch.setattr(type(updater), 'strip_undeclared_fields',
                        lambda *_args, **_kwargs: order.append('strip'))
    monkeypatch.setattr(type(updater), 'backfill_field_types',
                        lambda *_args, **_kwargs: order.append('backfill'))

    updater.normalise_object_fields()

    assert order == ['strip', 'backfill']


def test_normalise_object_fields_wraps_a_failure() -> None:
    """A failing read is surfaced as an UpdaterException naming the migration's job"""
    updater = _new_updater()
    updater.types_manager.find.side_effect = RuntimeError('boom')

    with pytest.raises(UpdaterException) as exc_info:
        updater.normalise_object_fields()

    assert 'boom' in str(exc_info.value)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   start_update                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_start_update_bumps_the_version_last(monkeypatch: pytest.MonkeyPatch) -> None:
    """The version is persisted only after the normalisation completed"""
    updater = _new_updater()
    order: list[str] = []

    monkeypatch.setattr(type(updater), 'normalise_object_fields',
                        lambda *_args, **_kwargs: order.append('normalise'))
    monkeypatch.setattr(type(updater), 'increase_updater_version',
                        lambda _self, value: order.append(f'version:{value}'))

    updater.start_update()

    assert order == ['normalise', 'version:20260225']


def test_start_update_does_not_double_wrap_an_updater_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """An UpdaterException from the normalisation is re-raised as-is, not nested in a second one"""
    updater = _new_updater()
    raised = UpdaterException('Failed to normalise the field entries of the objects: boom')

    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise raised

    monkeypatch.setattr(type(updater), 'normalise_object_fields', _raise)

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value is raised


def test_start_update_wraps_a_version_bump_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure outside the normalisation is wrapped so startup aborts loudly"""
    updater = _new_updater()

    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError('no settings')

    monkeypatch.setattr(type(updater), 'normalise_object_fields', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(type(updater), 'increase_updater_version', _raise)

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert 'no settings' in str(exc_info.value)
