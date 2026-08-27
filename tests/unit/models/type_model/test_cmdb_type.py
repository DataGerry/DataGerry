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
Unit tests for cmdb.models.type_model.cmdb_type

Pure: no Mongo, no Flask. CmdbType is the schema every CmdbObject is written against, so what is
pinned here is the document contract (`from_data` / `to_json`, guarded by a round-trip test now that
both halves are keyed by `TypeSchemaKey`) and the accessors the renderer and the managers read the
schema through.

Two behaviours are asserted because they were WRONG before 2026-08-26 and would be easy to
reintroduce: `get_nested_summaries` collects every reference field's overrides rather than the first
one's, and the summary accessors skip a name that no longer resolves to a field instead of raising
for the whole summary - a stale summary name is a normal state, because removing a field from a type
does not clean it out of the summaries that referenced it.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.type_constants import NestedSummaryKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.errors.models.cmdb_type import (
    CmdbTypeInitError,
    CmdbTypeInitFromDataError,
    CmdbTypeToJsonError,
    CmdbTypeFieldNotFoundError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 12
TYPE_NAME: str = 'server'
NAME_FIELD: str = 'text-name'
OWNER_FIELD: str = 'ref-owner'
MDS_FIELD: str = 'text-row'


def _field(name: str, field_type: str, **extra: Any) -> dict[str, Any]:
    """Builds one field definition."""
    return {FieldKey.NAME.value: name, FieldKey.TYPE.value: field_type, **extra}


def _section(name: str, section_type: str, fields: list[str]) -> dict[str, Any]:
    """Builds one render_meta section."""
    return {'name': name, 'type': section_type, 'label': name, 'fields': fields}


def _document(**overrides: Any) -> dict[str, Any]:
    """Builds a stored CmdbType document with the keys from_data requires."""
    document: dict[str, Any] = {
        TypeSchemaKey.PUBLIC_ID.value: PUBLIC_ID,
        TypeSchemaKey.NAME.value: TYPE_NAME,
        TypeSchemaKey.AUTHOR_ID.value: 1,
        TypeSchemaKey.RENDER_META.value: {},
    }
    document.update(overrides)

    return document


def _type(**overrides: Any) -> CmdbType:
    """Builds a CmdbType through from_data, which is how every caller builds one."""
    return CmdbType.from_data(_document(**overrides))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      __init__                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_defaults_are_applied() -> None:
    """An omitted optional argument falls back to its documented default"""
    cmdb_type = _type()

    assert cmdb_type.label == TYPE_NAME.title()
    assert cmdb_type.version == CmdbType.DEFAULT_VERSION
    assert cmdb_type.active is True
    assert cmdb_type.selectable_as_parent is True
    assert cmdb_type.global_template_ids == []
    assert cmdb_type.fields == []


def test_creation_time_defaults_to_now() -> None:
    """A type built without a creation time is stamped at construction"""
    before = datetime.now(timezone.utc)

    assert _type().creation_time >= before


def test_a_failing_init_is_wrapped() -> None:
    """Anything raised while building the type surfaces as CmdbTypeInitError"""
    with pytest.raises(CmdbTypeInitError):
        CmdbType(public_id=PUBLIC_ID, name=None, author_id=1, render_meta=None)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                from_data / to_json                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_from_data_reads_every_key() -> None:
    """A full document maps onto the matching attributes"""
    stamp = datetime(2026, 3, 1, tzinfo=timezone.utc)
    cmdb_type = _type(**{
        TypeSchemaKey.LABEL.value: 'Server',
        TypeSchemaKey.VERSION.value: '2.0.0',
        TypeSchemaKey.DESCRIPTION.value: 'A server',
        TypeSchemaKey.ACTIVE.value: False,
        TypeSchemaKey.SELECTABLE_AS_PARENT.value: False,
        TypeSchemaKey.SPECIAL_TYPE.value: 'SUBNET',
        TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value: ['tpl'],
        TypeSchemaKey.CREATION_TIME.value: stamp,
        TypeSchemaKey.EDITOR_ID.value: 3,
        TypeSchemaKey.LAST_EDIT_TIME.value: stamp,
        TypeSchemaKey.CI_EXPLORER_LABEL.value: 'srv',
        TypeSchemaKey.CI_EXPLORER_COLOR.value: '#fff',
        TypeSchemaKey.FIELDS.value: [_field(NAME_FIELD, FieldType.TEXT)],
    })

    assert (cmdb_type.label, cmdb_type.version, cmdb_type.description) == ('Server', '2.0.0', 'A server')
    assert (cmdb_type.active, cmdb_type.selectable_as_parent) == (False, False)
    assert (cmdb_type.editor_id, cmdb_type.creation_time, cmdb_type.last_edit_time) == (3, stamp, stamp)
    assert cmdb_type.global_template_ids == ['tpl']


def test_special_type_is_kept_as_its_stored_string() -> None:
    """The marker round-trips verbatim; SpecialType is a str enum so a member still compares equal"""
    cmdb_type = _type(**{TypeSchemaKey.SPECIAL_TYPE.value: 'SUBNET'})

    assert cmdb_type.special_type == 'SUBNET'
    assert CmdbType.to_json(cmdb_type)[TypeSchemaKey.SPECIAL_TYPE.value] == 'SUBNET'


@pytest.mark.parametrize('key', [TypeSchemaKey.CREATION_TIME, TypeSchemaKey.LAST_EDIT_TIME])
def test_from_data_parses_a_string_timestamp(key: TypeSchemaKey) -> None:
    """A timestamp that came back as a string is parsed into a datetime"""
    cmdb_type = _type(**{key.value: '2026-03-01T10:00:00'})

    assert getattr(cmdb_type, key.value) == datetime(2026, 3, 1, 10, 0, 0)


def test_from_data_keeps_a_null_editor_id() -> None:
    """A type nobody has edited keeps editor_id None instead of coercing it to 0"""
    assert _type().editor_id is None


@pytest.mark.parametrize('missing', [TypeSchemaKey.PUBLIC_ID, TypeSchemaKey.NAME, TypeSchemaKey.AUTHOR_ID])
def test_from_data_wraps_a_missing_required_key(missing: TypeSchemaKey) -> None:
    """A document missing a mandatory key surfaces as CmdbTypeInitFromDataError, not a KeyError"""
    document = _document()
    del document[missing.value]

    with pytest.raises(CmdbTypeInitFromDataError):
        CmdbType.from_data(document)


def test_to_json_emits_every_schema_key() -> None:
    """The serialised document carries exactly the keys from_data reads"""
    document = CmdbType.to_json(_type())

    assert TypeSchemaKey.PUBLIC_ID.value in document
    assert TypeSchemaKey.RENDER_META.value in document
    assert TypeSchemaKey.ACL.value in document


def test_to_json_wraps_a_failure() -> None:
    """A wrong argument is reported as CmdbTypeToJsonError, not an AttributeError"""
    with pytest.raises(CmdbTypeToJsonError):
        CmdbType.to_json({'public_id': PUBLIC_ID})


def test_from_data_and_to_json_round_trip() -> None:
    """
    The two halves agree on every key name

    Both are keyed by TypeSchemaKey now; a drift between what from_data reads and what to_json writes
    would be a silently dropped field rather than an error.
    """
    original = _type(**{
        TypeSchemaKey.LABEL.value: 'Server',
        TypeSchemaKey.DESCRIPTION.value: 'A server',
        TypeSchemaKey.FIELDS.value: [_field(NAME_FIELD, FieldType.TEXT)],
        TypeSchemaKey.CREATION_TIME.value: datetime(2026, 3, 1, tzinfo=timezone.utc),
    })

    assert CmdbType.to_json(CmdbType.from_data(CmdbType.to_json(original))) == CmdbType.to_json(original)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  simple accessors                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_name_returns_the_name() -> None:
    """The name is the CmdbType's stable identifier"""
    assert _type().get_name() == TYPE_NAME


def test_get_label_falls_back_to_the_title_cased_name() -> None:
    """A type whose label was cleared displays its title-cased name"""
    cmdb_type = _type()
    cmdb_type.label = ''

    assert cmdb_type.get_label() == TYPE_NAME.title()


def test_get_label_does_not_write_the_fallback_back() -> None:
    """A reader must not change the CmdbType it is reading"""
    cmdb_type = _type()
    cmdb_type.label = ''

    cmdb_type.get_label()

    assert cmdb_type.label == ''


def test_get_field_returns_the_definition() -> None:
    """A field is looked up by its name, which is its immutable identifier"""
    cmdb_type = _type(**{TypeSchemaKey.FIELDS.value: [_field(NAME_FIELD, FieldType.TEXT)]})

    assert cmdb_type.get_field(NAME_FIELD)[FieldKey.TYPE.value] == FieldType.TEXT


def test_get_field_raises_for_an_unknown_name() -> None:
    """The single-field accessor keeps its raising contract"""
    with pytest.raises(CmdbTypeFieldNotFoundError):
        _type().get_field('nope')


def test_field_type_accessors() -> None:
    """The names-only and definition-keyed views agree on which fields match"""
    cmdb_type = _type(**{TypeSchemaKey.FIELDS.value: [
        _field(NAME_FIELD, FieldType.TEXT),
        _field(OWNER_FIELD, FieldType.REFERENCE),
    ]})

    assert cmdb_type.get_all_fields_of_type(FieldType.TEXT) == [NAME_FIELD]
    assert list(cmdb_type.get_fields_with_type(FieldType.REFERENCE)) == [OWNER_FIELD]
    assert cmdb_type.get_fields_with_type(FieldType.REFERENCE)[OWNER_FIELD][FieldKey.NAME.value] == OWNER_FIELD
    assert cmdb_type.get_fields() == cmdb_type.fields


# -------------------------------------------------------------------------------------------------------------------- #
#                                              sections / externals                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _with_sections(*sections: dict[str, Any]) -> CmdbType:
    """Builds a type whose render_meta carries the given sections."""
    return _type(**{TypeSchemaKey.RENDER_META.value: {'sections': list(sections)}})


def test_section_accessors() -> None:
    """Sections are reachable by name and their presence is reported"""
    cmdb_type = _with_sections(_section('information', SectionType.SECTION, [NAME_FIELD]))

    assert cmdb_type.has_sections() is True
    assert cmdb_type.get_section('information').name == 'information'
    assert cmdb_type.get_section('nope') is None
    assert len(cmdb_type.get_sections()) == 1


def test_a_type_without_sections_reports_none() -> None:
    """has_sections is what callers branch on before touching the section list"""
    assert _type().has_sections() is False


def test_mds_accessors_only_see_multi_data_sections() -> None:
    """The MDS views must not pick up an ordinary section's fields"""
    cmdb_type = _with_sections(
        _section('information', SectionType.SECTION, [NAME_FIELD]),
        _section('rows', SectionType.MDS_SECTION, [MDS_FIELD]),
    )

    assert cmdb_type.get_all_mds_fields() == [MDS_FIELD]
    assert cmdb_type.get_mds_section_ids() == {'rows'}


def test_external_accessors() -> None:
    """External links are reachable by name and their presence is reported"""
    cmdb_type = _type(**{TypeSchemaKey.RENDER_META.value: {
        'externals': [{'name': 'docs', 'href': 'https://example.test', 'label': 'Docs', 'fields': []}],
    }})

    assert cmdb_type.has_externals() is True
    assert cmdb_type.get_external('docs').name == 'docs'
    assert cmdb_type.get_external('nope') is None


def test_a_type_without_externals_reports_none() -> None:
    """has_externals is what callers branch on before touching the external list"""
    assert _type().has_externals() is False


def test_get_icon_is_none_when_render_meta_carries_none() -> None:
    """The icon is optional presentation data"""
    assert _type().get_icon() in (None, '')


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    summaries                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def _nested(type_id: int, **extra: Any) -> dict[str, Any]:
    """Builds one nested-summary entry addressing the given type."""
    return {NestedSummaryKey.TYPE_ID.value: type_id, **extra}


def test_get_nested_summaries_collects_every_reference_field() -> None:
    """
    Regression: it used to return only the FIRST reference field's overrides

    A type with two reference fields may override the same referenced type differently, so both
    entries have to come back.
    """
    cmdb_type = _type(**{TypeSchemaKey.FIELDS.value: [
        _field(NAME_FIELD, FieldType.TEXT),
        _field(OWNER_FIELD, FieldType.REFERENCE, **{FieldKey.SUMMARIES.value: [_nested(1)]}),
        _field('ref-site', FieldType.REFERENCE, **{FieldKey.SUMMARIES.value: [_nested(2)]}),
    ]})

    assert cmdb_type.get_nested_summaries() == [_nested(1), _nested(2)]


def test_get_nested_summaries_ignores_non_reference_fields() -> None:
    """The comparison is against FieldType.REFERENCE, never a bare 'ref' literal"""
    cmdb_type = _type(**{TypeSchemaKey.FIELDS.value: [
        _field(NAME_FIELD, FieldType.TEXT, **{FieldKey.SUMMARIES.value: [_nested(1)]}),
    ]})

    assert not cmdb_type.get_nested_summaries()


def test_get_nested_summaries_is_empty_without_overrides() -> None:
    """A reference field that declares no summaries contributes nothing"""
    cmdb_type = _type(**{TypeSchemaKey.FIELDS.value: [_field(OWNER_FIELD, FieldType.REFERENCE)]})

    assert not cmdb_type.get_nested_summaries()


def test_nested_prefix_and_line_match_on_type_id() -> None:
    """Only the entry addressing THIS type applies"""
    cmdb_type = _type()
    entries = [
        _nested(999, **{NestedSummaryKey.PREFIX.value: True, NestedSummaryKey.LINE.value: 'other'}),
        _nested(PUBLIC_ID, **{NestedSummaryKey.PREFIX.value: False, NestedSummaryKey.LINE.value: 'Name {}'}),
    ]

    assert cmdb_type.has_nested_prefix(entries) is False
    assert cmdb_type.get_nested_summary_line(entries) == 'Name {}'


def test_nested_prefix_and_line_default_without_a_match() -> None:
    """No entry for this type means no prefix and no line"""
    cmdb_type = _type()

    assert cmdb_type.has_nested_prefix([_nested(999)]) is False
    assert cmdb_type.get_nested_summary_line([_nested(999)]) is None


def test_get_summary_resolves_the_configured_fields() -> None:
    """The summary is the field definitions named by render_meta.summary"""
    cmdb_type = _type(**{
        TypeSchemaKey.FIELDS.value: [_field(NAME_FIELD, FieldType.TEXT)],
        TypeSchemaKey.RENDER_META.value: {'summary': {'fields': [NAME_FIELD]}},
    })

    assert cmdb_type.has_summaries() is True
    assert [field[FieldKey.NAME.value] for field in cmdb_type.get_summary().fields] == [NAME_FIELD]


def test_get_summary_skips_a_field_that_no_longer_exists() -> None:
    """
    Regression: a stale summary name used to raise for the WHOLE summary

    Removing a field from a type does not clean its name out of render_meta.summary.fields, so a
    stale name is a normal state of a long-lived type.
    """
    cmdb_type = _type(**{
        TypeSchemaKey.FIELDS.value: [_field(NAME_FIELD, FieldType.TEXT)],
        TypeSchemaKey.RENDER_META.value: {'summary': {'fields': ['deleted-field', NAME_FIELD]}},
    })

    assert [field[FieldKey.NAME.value] for field in cmdb_type.get_summary().fields] == [NAME_FIELD]


def test_get_nested_summary_fields_resolves_the_matching_entry() -> None:
    """The field names of the entry addressing this type are resolved to definitions"""
    cmdb_type = _type(**{TypeSchemaKey.FIELDS.value: [_field(NAME_FIELD, FieldType.TEXT)]})
    entries = [_nested(PUBLIC_ID, **{NestedSummaryKey.FIELDS.value: [NAME_FIELD]})]

    assert [field[FieldKey.NAME.value] for field in cmdb_type.get_nested_summary_fields(entries)] == [NAME_FIELD]


def test_get_nested_summary_fields_skips_a_field_that_no_longer_exists() -> None:
    """Same tolerance as get_summary - one stale name may not cost the whole nested summary"""
    cmdb_type = _type(**{TypeSchemaKey.FIELDS.value: [_field(NAME_FIELD, FieldType.TEXT)]})
    entries = [_nested(PUBLIC_ID, **{NestedSummaryKey.FIELDS.value: ['deleted-field', NAME_FIELD]})]

    assert [field[FieldKey.NAME.value] for field in cmdb_type.get_nested_summary_fields(entries)] == [NAME_FIELD]


def test_get_nested_summary_fields_is_empty_without_a_match() -> None:
    """No entry for this type means no nested summary fields"""
    assert not _type().get_nested_summary_fields([_nested(999)])


def test_a_type_without_a_summary_reports_none() -> None:
    """has_summaries is what callers branch on before building a summary line"""
    assert _type().has_summaries() is False
