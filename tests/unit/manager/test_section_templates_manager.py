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
Unit tests for cmdb.manager.section_templates_manager

The DB-touching collaborators (objects_manager / types_manager) and the cross-method calls are
stubbed via MagicMock on a MagicMock-typed ``self`` so each method body is exercised in
isolation - the manager is never constructed (its __init__ would build real managers). Field
definitions are plain dicts keyed by their wire strings; object documents are lightweight
SimpleNamespace stand-ins exposing only the attributes the methods read (public_id,
multi_data_sections). Schema dict keys are referenced via the model key enums per the
no-magic-values rule
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.type_model import SectionType, FieldKey
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.manager.section_templates_manager import SectionTemplatesManager
from cmdb.errors.manager.section_templates_manager import (
    SectionTemplatesManagerInsertError,
    SectionTemplatesManagerGetError,
    SectionTemplatesManagerUpdateError,
    SectionTemplatesManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=protected-access

PATH: str = 'cmdb.manager.section_templates_manager'

TYPE_ID: int = 42
SECTION_NAME: str = 'dg-ipam-interface'


class _FakeSection:
    """A stand-in for a TypeFieldSection / TypeMultiDataSection exposing the attributes used."""

    def __init__(self, name: str, fields: list[str], section_type: str = SectionType.SECTION.value) -> None:
        self.name = name
        self.label = ''
        self.type = section_type
        self.fields = list(fields)

    def get_fields(self) -> list[str]:
        """Returns the section's field-name list."""
        return list(self.fields)


def _fake_type(
    public_id: int,
    global_template_ids: list[str],
    type_fields: list[dict[str, Any]],
    summary_fields: list[str],
    sections: list[_FakeSection],
) -> SimpleNamespace:
    """Builds a CmdbType stand-in with the attributes the manager reads/mutates."""
    render_meta = SimpleNamespace(
        summary=SimpleNamespace(fields=list(summary_fields)),
        sections=list(sections),
    )
    fake = SimpleNamespace(
        public_id=public_id,
        global_template_ids=list(global_template_ids),
        fields=list(type_fields),
        render_meta=render_meta,
    )
    fake.get_section = lambda name: next((s for s in fake.render_meta.sections if s.name == name), None)

    return fake


def _field_def(name: str, field_type: str = 'text', value: Any = None) -> dict[str, Any]:
    """Builds a template field definition keyed by the wire strings, with an optional default."""
    field: dict[str, Any] = {FieldKey.NAME.value: name, FieldKey.TYPE.value: field_type}

    if value is not None:
        field[FieldKey.VALUE.value] = value

    return field


# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_section_label_diff                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_section_label_diff_returns_new_label_when_changed() -> None:
    """A changed label is returned so the caller re-applies it to the section"""
    result = SectionTemplatesManager.get_section_label_diff(
        MagicMock(), {'label': 'New'}, {'label': 'Old'},
    )

    assert result == 'New'


def test_get_section_label_diff_returns_empty_string_when_unchanged() -> None:
    """An unchanged label yields '' so the caller leaves the section label untouched"""
    result = SectionTemplatesManager.get_section_label_diff(
        MagicMock(), {'label': 'Same'}, {'label': 'Same'},
    )

    assert result == ''


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 get_fields_diff                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_fields_diff_reports_added_definitions_and_deleted_names() -> None:
    """Added entries carry the full field definition; deleted entries carry just the field name"""
    added = _field_def('c')
    new_params = {'fields': [_field_def('a'), _field_def('b'), added]}
    current_params = {'fields': [_field_def('a'), _field_def('b'), _field_def('gone')]}

    diff = SectionTemplatesManager.get_fields_diff(MagicMock(), new_params, current_params)

    assert diff['added'] == [added]
    assert diff['deleted'] == ['gone']


def test_get_fields_diff_handles_missing_fields_key() -> None:
    """A payload without a 'fields' key is treated as no fields, not a KeyError"""
    diff = SectionTemplatesManager.get_fields_diff(MagicMock(), {}, {})

    assert diff == {'added': [], 'deleted': []}


# -------------------------------------------------------------------------------------------------------------------- #
#                                          set_new_global_template_fields                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_set_new_global_template_fields_is_a_noop_for_empty_fields() -> None:
    """No added fields means neither the flat nor the MDS object pass runs"""
    mock_self = MagicMock()

    SectionTemplatesManager.set_new_global_template_fields(mock_self, TYPE_ID, [], SectionType.SECTION, SECTION_NAME)

    mock_self._add_flat_fields_to_objects.assert_not_called()
    mock_self._add_mds_fields_to_objects.assert_not_called()


def test_set_new_global_template_fields_rejects_non_dict_fields() -> None:
    """A non-dict field list is a programming error and raises ValueError"""
    with pytest.raises(ValueError):
        SectionTemplatesManager.set_new_global_template_fields(
            MagicMock(), TYPE_ID, ['not-a-dict'], SectionType.SECTION, SECTION_NAME,
        )


def test_set_new_global_template_fields_regular_section_seeds_flat_only() -> None:
    """A regular section seeds the flat fields array and never touches MDS rows"""
    mock_self = MagicMock()
    fields = [_field_def('a')]

    SectionTemplatesManager.set_new_global_template_fields(
        mock_self, TYPE_ID, fields, SectionType.SECTION, SECTION_NAME,
    )

    mock_self._add_flat_fields_to_objects.assert_called_once_with(TYPE_ID, fields)
    mock_self._add_mds_fields_to_objects.assert_not_called()


def test_set_new_global_template_fields_mds_section_seeds_both_flat_and_rows() -> None:
    """An MDS field is recorded in the flat fields array (the FE's field source) AND in the rows"""
    mock_self = MagicMock()
    fields = [_field_def('a')]

    SectionTemplatesManager.set_new_global_template_fields(
        mock_self, TYPE_ID, fields, SectionType.MDS_SECTION, SECTION_NAME,
    )

    mock_self._add_flat_fields_to_objects.assert_called_once_with(TYPE_ID, fields)
    mock_self._add_mds_fields_to_objects.assert_called_once_with(TYPE_ID, fields, SECTION_NAME)


# -------------------------------------------------------------------------------------------------------------------- #
#                                           _add_flat_fields_to_objects                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_add_flat_fields_to_objects_pushes_each_missing_field_with_its_default() -> None:
    """One $push per field, scoped to objects lacking it, seeding the definition's default value"""
    mock_self = MagicMock()

    SectionTemplatesManager._add_flat_fields_to_objects(
        mock_self, TYPE_ID, [_field_def('ip', value='ipv4'), _field_def('host')],
    )

    name_path = f"{CmdbObjectKey.FIELDS.value}.{CmdbObjectFieldKey.NAME.value}"
    assert mock_self.objects_manager.update_many_raw.call_count == 2

    first = mock_self.objects_manager.update_many_raw.call_args_list[0].kwargs
    assert first['filter_query'] == {CmdbObjectKey.TYPE_ID: TYPE_ID, name_path: {"$ne": 'ip'}}
    assert first['update'] == {"$push": {CmdbObjectKey.FIELDS: {
        CmdbObjectFieldKey.NAME: 'ip',
        CmdbObjectFieldKey.TYPE: 'text',
        CmdbObjectFieldKey.VALUE: 'ipv4',
    }}}

    second = mock_self.objects_manager.update_many_raw.call_args_list[1].kwargs
    assert second['update']["$push"][CmdbObjectKey.FIELDS][CmdbObjectFieldKey.VALUE] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                            _add_mds_fields_to_objects                                                #
# -------------------------------------------------------------------------------------------------------------------- #
_MDS: str = CmdbObjectKey.MULTI_DATA_SECTIONS.value
_VALUES: str = CmdbObjectMdsKey.VALUES.value
_DATA: str = CmdbObjectMdsRowKey.DATA.value
_SECTION_ID: str = CmdbObjectMdsKey.SECTION_ID.value
_NAME: str = CmdbObjectFieldKey.NAME.value


def test_add_mds_fields_to_objects_pushes_each_missing_field_via_array_filters() -> None:
    """Each new field is $pushed into the matching section's rows that lack it, server-side"""
    mock_self = MagicMock()

    SectionTemplatesManager._add_mds_fields_to_objects(
        mock_self, TYPE_ID, [_field_def('ip-type', field_type='select', value='ipv4')], SECTION_NAME,
    )

    mock_self.objects_manager.update_many_raw.assert_called_once()
    call = mock_self.objects_manager.update_many_raw.call_args.kwargs
    assert call['filter_query'] == {CmdbObjectKey.TYPE_ID: TYPE_ID, f'{_MDS}.{_SECTION_ID}': SECTION_NAME}
    assert call['update'] == {'$push': {f'{_MDS}.$[s].{_VALUES}.$[v].{_DATA}': {
        CmdbObjectFieldKey.NAME: 'ip-type',
        CmdbObjectFieldKey.TYPE: 'select',
        CmdbObjectFieldKey.VALUE: 'ipv4',
    }}}
    # Section is targeted via $[s]; only rows whose data lacks the name are targeted via $[v]
    assert call['array_filters'] == [
        {f's.{_SECTION_ID}': SECTION_NAME},
        {f'v.{_DATA}.{_NAME}': {'$ne': 'ip-type'}},
    ]


def test_add_mds_fields_to_objects_is_a_noop_for_empty_fields() -> None:
    """No update is issued when there are no fields to add"""
    mock_self = MagicMock()

    SectionTemplatesManager._add_mds_fields_to_objects(mock_self, TYPE_ID, [], SECTION_NAME)

    mock_self.objects_manager.update_many_raw.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                cleanup_mds_fields                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_cleanup_mds_fields_pulls_named_fields_via_array_filter() -> None:
    """Named fields are $pulled from every row of the matching section server-side"""
    mock_self = MagicMock()

    SectionTemplatesManager.cleanup_mds_fields(mock_self, TYPE_ID, ['drop'], SECTION_NAME)

    mock_self.objects_manager.update_many_raw.assert_called_once()
    call = mock_self.objects_manager.update_many_raw.call_args.kwargs
    assert call['filter_query'] == {CmdbObjectKey.TYPE_ID: TYPE_ID, f'{_MDS}.{_SECTION_ID}': SECTION_NAME}
    assert call['update'] == {'$pull': {f'{_MDS}.$[s].{_VALUES}.$[].{_DATA}': {_NAME: {'$in': ['drop']}}}}
    assert call['array_filters'] == [{f's.{_SECTION_ID}': SECTION_NAME}]


def test_cleanup_mds_fields_is_a_noop_for_empty_list() -> None:
    """An empty field list issues no update"""
    mock_self = MagicMock()

    SectionTemplatesManager.cleanup_mds_fields(mock_self, TYPE_ID, [], SECTION_NAME)

    mock_self.objects_manager.update_many_raw.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                               cleanup_section_fields                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_cleanup_section_fields_is_a_noop_for_empty_list() -> None:
    """No field names means no pull query is issued"""
    mock_self = MagicMock()

    SectionTemplatesManager.cleanup_section_fields(mock_self, TYPE_ID, [])

    mock_self.objects_manager.update_many_pull.assert_not_called()


def test_cleanup_section_fields_pulls_named_fields_by_type() -> None:
    """A single $pull removes every named flat field from the type's objects"""
    mock_self = MagicMock()

    SectionTemplatesManager.cleanup_section_fields(mock_self, TYPE_ID, ['a', 'b'])

    mock_self.objects_manager.update_many_pull.assert_called_once_with(
        {CmdbObjectKey.TYPE_ID: TYPE_ID},
        {CmdbObjectKey.FIELDS: {CmdbObjectFieldKey.NAME: {"$in": ['a', 'b']}}},
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                           delete_mds_section_from_objects                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_delete_mds_section_from_objects_pulls_the_whole_section() -> None:
    """The entire MDS section container is removed from every object of the type"""
    mock_self = MagicMock()

    SectionTemplatesManager.delete_mds_section_from_objects(mock_self, TYPE_ID, SECTION_NAME)

    mock_self.objects_manager.update_many_pull.assert_called_once_with(
        {CmdbObjectKey.TYPE_ID: TYPE_ID},
        {CmdbObjectKey.MULTI_DATA_SECTIONS: {CmdbObjectMdsKey.SECTION_ID: SECTION_NAME}},
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                          cleanup_global_section_objects                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_cleanup_global_section_objects_regular_section_only_cleans_flat() -> None:
    """A regular section cleans the flat fields and does not touch any MDS path"""
    mock_self = MagicMock()

    SectionTemplatesManager.cleanup_global_section_objects(
        mock_self, TYPE_ID, ['a'], SectionType.SECTION, SECTION_NAME,
    )

    mock_self.cleanup_section_fields.assert_called_once_with(TYPE_ID, ['a'])
    mock_self.cleanup_mds_fields.assert_not_called()
    mock_self.delete_mds_section_from_objects.assert_not_called()


def test_cleanup_global_section_objects_mds_field_mode_cleans_rows() -> None:
    """An MDS section in field mode cleans flat fields and removes the named fields from rows"""
    mock_self = MagicMock()

    SectionTemplatesManager.cleanup_global_section_objects(
        mock_self, TYPE_ID, ['a'], SectionType.MDS_SECTION, SECTION_NAME, delete_mode=False,
    )

    mock_self.cleanup_section_fields.assert_called_once_with(TYPE_ID, ['a'])
    mock_self.cleanup_mds_fields.assert_called_once_with(TYPE_ID, ['a'], SECTION_NAME)
    mock_self.delete_mds_section_from_objects.assert_not_called()


def test_cleanup_global_section_objects_mds_delete_mode_drops_section() -> None:
    """An MDS section in delete mode drops the whole section container instead of fields"""
    mock_self = MagicMock()

    SectionTemplatesManager.cleanup_global_section_objects(
        mock_self, TYPE_ID, ['a'], SectionType.MDS_SECTION, SECTION_NAME, delete_mode=True,
    )

    mock_self.delete_mds_section_from_objects.assert_called_once_with(TYPE_ID, SECTION_NAME)
    mock_self.cleanup_mds_fields.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                          handle_section_template_changes                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_handle_section_template_changes_is_a_noop_for_non_global_template() -> None:
    """A non-global template never propagates - no type lookup happens"""
    mock_self = MagicMock()
    current = MagicMock(is_global=False)

    SectionTemplatesManager.handle_section_template_changes(mock_self, {'name': 't'}, current)

    mock_self.get_types_using_template.assert_not_called()


def test_handle_section_template_changes_is_a_noop_without_a_template_name() -> None:
    """A payload missing the template name is ignored rather than raising"""
    mock_self = MagicMock()
    current = MagicMock(is_global=True)

    with patch(f'{PATH}.CmdbSectionTemplate.to_json', return_value={}):
        SectionTemplatesManager.handle_section_template_changes(mock_self, {}, current)

    mock_self.get_types_using_template.assert_not_called()


def test_handle_section_template_changes_applies_to_each_consuming_type() -> None:
    """Every type returned by the lookup gets the change applied exactly once"""
    mock_self = MagicMock()
    type_a, type_b = MagicMock(), MagicMock()
    mock_self.get_types_using_template.return_value = [type_a, type_b]
    mock_self.get_section_label_diff.return_value = 'New'
    mock_self.get_fields_diff.return_value = {'added': [], 'deleted': []}
    current = MagicMock(is_global=True)
    new_params = {'name': 't'}

    with patch(f'{PATH}.CmdbSectionTemplate.to_json', return_value={'name': 't', 'label': 'Old', 'fields': []}):
        SectionTemplatesManager.handle_section_template_changes(mock_self, new_params, current)

    assert mock_self._apply_template_changes_to_type.call_count == 2
    applied_types = [c.args[0] for c in mock_self._apply_template_changes_to_type.call_args_list]
    assert applied_types == [type_a, type_b]


# -------------------------------------------------------------------------------------------------------------------- #
#                                         get_global_template_usage_count                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_global_template_usage_count_returns_zero_for_non_global() -> None:
    """A non-global template reports zero usage without querying"""
    mock_self = MagicMock()

    counts = SectionTemplatesManager.get_global_template_usage_count(mock_self, 'tpl', is_global=False)

    assert counts == {'types': 0, 'objects': 0}
    mock_self.types_manager.get_distinct.assert_not_called()


def test_get_global_template_usage_count_counts_types_and_objects() -> None:
    """Type ids come from a distinct projection (not materialised types); objects via a count query"""
    mock_self = MagicMock()
    mock_self.types_manager.get_distinct.return_value = [1, 2]
    mock_self.objects_manager.count_documents.return_value = 7

    counts = SectionTemplatesManager.get_global_template_usage_count(mock_self, 'tpl', is_global=True)

    assert counts == {'types': 2, 'objects': 7}
    mock_self.objects_manager.count_documents.assert_called_once_with({CmdbObjectKey.TYPE_ID: {"$in": [1, 2]}})


# -------------------------------------------------------------------------------------------------------------------- #
#                                       delete_global_section_from_objects                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_delete_global_section_from_objects_regular_pulls_flat_only() -> None:
    """A regular section pulls the named flat fields and does not drop an MDS container"""
    mock_self = MagicMock()

    SectionTemplatesManager.delete_global_section_from_objects(
        mock_self, TYPE_ID, ['a', 'b'], SectionType.SECTION, SECTION_NAME,
    )

    mock_self.objects_manager.update_many_pull.assert_called_once_with(
        criteria={CmdbObjectKey.TYPE_ID: TYPE_ID},
        update={CmdbObjectKey.FIELDS: {CmdbObjectFieldKey.NAME: {"$in": ['a', 'b']}}},
    )
    mock_self.delete_mds_section_from_objects.assert_not_called()


def test_delete_global_section_from_objects_mds_pulls_flat_and_drops_section() -> None:
    """An MDS section pulls the flat fields and additionally drops the whole MDS container"""
    mock_self = MagicMock()

    SectionTemplatesManager.delete_global_section_from_objects(
        mock_self, TYPE_ID, ['a'], SectionType.MDS_SECTION, SECTION_NAME,
    )

    mock_self.objects_manager.update_many_pull.assert_called_once()
    mock_self.delete_mds_section_from_objects.assert_called_once_with(TYPE_ID, SECTION_NAME)


def test_delete_global_section_from_objects_skips_flat_pull_without_field_names() -> None:
    """With no field names the flat pull is skipped (an MDS section still drops its container)"""
    mock_self = MagicMock()

    SectionTemplatesManager.delete_global_section_from_objects(
        mock_self, TYPE_ID, [], SectionType.MDS_SECTION, SECTION_NAME,
    )

    mock_self.objects_manager.update_many_pull.assert_not_called()
    mock_self.delete_mds_section_from_objects.assert_called_once_with(TYPE_ID, SECTION_NAME)


# -------------------------------------------------------------------------------------------------------------------- #
#                                         cleanup_global_section_templates                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_cleanup_global_section_templates_strips_template_from_each_type() -> None:
    """The template name, its fields, summary entries and section are removed and the type persisted"""
    mock_self = MagicMock()
    section = _FakeSection(SECTION_NAME, ['f1', 'f2'])
    fake = _fake_type(
        public_id=TYPE_ID,
        global_template_ids=[SECTION_NAME],
        type_fields=[{FieldKey.NAME.value: 'f1'}, {FieldKey.NAME.value: 'keep'}, {FieldKey.NAME.value: 'f2'}],
        summary_fields=['f1', 'keep'],
        sections=[section],
    )
    mock_self.get_types_using_template.return_value = [fake]

    SectionTemplatesManager.cleanup_global_section_templates(mock_self, SECTION_NAME, delete_mode=True)

    assert SECTION_NAME not in fake.global_template_ids
    assert [f[FieldKey.NAME.value] for f in fake.fields] == ['keep']
    assert fake.render_meta.summary.fields == ['keep']
    assert fake.render_meta.sections == []
    mock_self.cleanup_global_section_objects.assert_called_once()
    mock_self.types_manager.update_type.assert_called_once_with(TYPE_ID, fake)


def test_cleanup_global_section_templates_skips_type_without_the_section() -> None:
    """A type that no longer carries the section is left unchanged (no object cleanup, no persist)"""
    mock_self = MagicMock()
    fake = _fake_type(TYPE_ID, [SECTION_NAME], [], [], sections=[])
    mock_self.get_types_using_template.return_value = [fake]

    SectionTemplatesManager.cleanup_global_section_templates(mock_self, SECTION_NAME)

    # global_template_ids is still pruned, but no object cleanup / persist runs
    assert SECTION_NAME not in fake.global_template_ids
    mock_self.cleanup_global_section_objects.assert_not_called()
    mock_self.types_manager.update_type.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                          cleanup_global_section_from_type                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_cleanup_global_section_from_type_uses_the_live_section_when_present() -> None:
    """When the section is still on the type, its fields/type drive the cleanup"""
    mock_self = MagicMock()
    section = _FakeSection(SECTION_NAME, ['f1'], SectionType.MDS_SECTION.value)
    fake = _fake_type(TYPE_ID, [SECTION_NAME], [{FieldKey.NAME.value: 'f1'}], ['f1'], sections=[section])
    mock_self.types_manager.get_type.return_value = fake

    SectionTemplatesManager.cleanup_global_section_from_type(mock_self, TYPE_ID, SECTION_NAME)

    assert fake.fields == []
    assert fake.render_meta.summary.fields == []
    mock_self.types_manager.update_type.assert_called_once_with(TYPE_ID, fake)
    mock_self.delete_global_section_from_objects.assert_called_once_with(
        TYPE_ID, ['f1'], SectionType.MDS_SECTION.value, SECTION_NAME,
    )


def test_cleanup_global_section_from_type_falls_back_to_snapshot_hints() -> None:
    """When the section is already gone, the caller's snapshot hints drive the object cleanup"""
    mock_self = MagicMock()
    fake = _fake_type(TYPE_ID, [SECTION_NAME], [{FieldKey.NAME.value: 'f1'}], ['f1'], sections=[])
    mock_self.types_manager.get_type.return_value = fake

    SectionTemplatesManager.cleanup_global_section_from_type(
        mock_self, TYPE_ID, SECTION_NAME,
        expected_field_names=['f1'], expected_section_type=SectionType.SECTION.value,
    )

    mock_self.delete_global_section_from_objects.assert_called_once_with(
        TYPE_ID, ['f1'], SectionType.SECTION.value, SECTION_NAME,
    )


def test_cleanup_global_section_from_type_noops_when_section_gone_and_no_hints() -> None:
    """No live section and no snapshot hints means nothing is persisted or cleaned"""
    mock_self = MagicMock()
    fake = _fake_type(TYPE_ID, [SECTION_NAME], [], [], sections=[])
    mock_self.types_manager.get_type.return_value = fake

    SectionTemplatesManager.cleanup_global_section_from_type(mock_self, TYPE_ID, SECTION_NAME)

    mock_self.types_manager.update_type.assert_not_called()
    mock_self.delete_global_section_from_objects.assert_not_called()


def test_cleanup_global_section_from_type_noops_when_type_missing() -> None:
    """A type that does not exist short-circuits without any further work"""
    mock_self = MagicMock()
    mock_self.types_manager.get_type.return_value = None

    SectionTemplatesManager.cleanup_global_section_from_type(mock_self, TYPE_ID, SECTION_NAME)

    mock_self.types_manager.update_type.assert_not_called()
    mock_self.delete_global_section_from_objects.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                         _apply_template_changes_to_type                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_apply_template_changes_to_type_rewrites_section_and_materializes_diff() -> None:
    """Label, section fields, summary and type.fields are updated and the object diff is applied"""
    mock_self = MagicMock()
    section = _FakeSection(SECTION_NAME, ['old'])
    fake = _fake_type(
        public_id=TYPE_ID,
        global_template_ids=[SECTION_NAME],
        type_fields=[{FieldKey.NAME.value: 'old'}, {FieldKey.NAME.value: 'other'}],
        summary_fields=['old', 'other'],
        sections=[section],
    )
    new_field = {FieldKey.NAME.value: 'new'}
    new_params = {'name': SECTION_NAME, 'label': 'New', 'fields': [new_field]}
    field_diffs = {'added': [new_field], 'deleted': ['old']}
    current = MagicMock(type=SectionType.SECTION.value, name=SECTION_NAME)

    SectionTemplatesManager._apply_template_changes_to_type(mock_self, fake, new_params, field_diffs, 'New', current)

    assert section.label == 'New'
    assert section.fields == ['new']
    assert fake.render_meta.summary.fields == ['other']  # 'old' (deleted) stripped
    assert [f[FieldKey.NAME.value] for f in fake.fields] == ['other', 'new']  # old + section fields dropped, new added
    mock_self.cleanup_global_section_objects.assert_called_once()
    mock_self.set_new_global_template_fields.assert_called_once()
    mock_self.types_manager.update_type.assert_called_once_with(TYPE_ID, fake)


def test_apply_template_changes_to_type_skips_a_type_without_the_section() -> None:
    """A type that no longer carries the section is left untouched"""
    mock_self = MagicMock()
    fake = _fake_type(TYPE_ID, [SECTION_NAME], [], [], sections=[])
    current = MagicMock(type=SectionType.SECTION.value, name=SECTION_NAME)

    SectionTemplatesManager._apply_template_changes_to_type(
        mock_self, fake, {'name': SECTION_NAME, 'label': 'x', 'fields': []}, {'added': [], 'deleted': []}, 'x', current,
    )

    mock_self.types_manager.update_type.assert_not_called()
    mock_self.set_new_global_template_fields.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              CRUD error wrapping                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
_VALID_TEMPLATE: dict[str, Any] = {
    'public_id': TYPE_ID, 'name': 't', 'label': 'T', 'type': SectionType.SECTION.value, 'fields': [],
}


def test_insert_section_template_returns_new_id() -> None:
    """A successful insert returns the new public_id from the base manager"""
    mock_self = MagicMock()
    mock_self.insert.return_value = TYPE_ID

    assert SectionTemplatesManager.insert_section_template(mock_self, dict(_VALID_TEMPLATE)) == TYPE_ID


def test_insert_section_template_wraps_errors() -> None:
    """A base-manager insert failure is wrapped as SectionTemplatesManagerInsertError"""
    mock_self = MagicMock()
    mock_self.insert.side_effect = RuntimeError('boom')

    with pytest.raises(SectionTemplatesManagerInsertError):
        SectionTemplatesManager.insert_section_template(mock_self, dict(_VALID_TEMPLATE))


def test_get_section_template_returns_instance_when_found() -> None:
    """A found document is wrapped in a CmdbSectionTemplate"""
    mock_self = MagicMock()
    mock_self.get_one.return_value = dict(_VALID_TEMPLATE)

    result = SectionTemplatesManager.get_section_template(mock_self, TYPE_ID)

    assert isinstance(result, CmdbSectionTemplate)


def test_get_section_template_returns_none_when_missing() -> None:
    """A missing document yields None rather than raising"""
    mock_self = MagicMock()
    mock_self.get_one.return_value = None

    assert SectionTemplatesManager.get_section_template(mock_self, TYPE_ID) is None


def test_get_section_template_wraps_errors() -> None:
    """A base-manager get failure is wrapped as SectionTemplatesManagerGetError"""
    mock_self = MagicMock()
    mock_self.get_one.side_effect = RuntimeError('boom')

    with pytest.raises(SectionTemplatesManagerGetError):
        SectionTemplatesManager.get_section_template(mock_self, TYPE_ID)


def test_update_section_template_wraps_errors() -> None:
    """A base-manager update failure is wrapped as SectionTemplatesManagerUpdateError"""
    mock_self = MagicMock()
    mock_self.update.side_effect = RuntimeError('boom')

    with pytest.raises(SectionTemplatesManagerUpdateError):
        SectionTemplatesManager.update_section_template(mock_self, TYPE_ID, dict(_VALID_TEMPLATE))


def test_delete_section_template_wraps_errors() -> None:
    """A base-manager delete failure is wrapped as SectionTemplatesManagerDeleteError"""
    mock_self = MagicMock()
    mock_self.delete.side_effect = RuntimeError('boom')

    with pytest.raises(SectionTemplatesManagerDeleteError):
        SectionTemplatesManager.delete_section_template(mock_self, TYPE_ID)
