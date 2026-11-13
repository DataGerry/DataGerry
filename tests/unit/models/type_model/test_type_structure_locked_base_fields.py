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
Unit tests for the locked base fields of the PERSON and PERSON_GROUP SpecialTypes

Pure tests. Pinned:

  - the base field names and kinds of each marker (``person_type_constants.LOCKED_BASE_FIELDS``)
  - a type carrying the marker that keeps every base field, with its kind, outside a multi-data section, passes - and
    may add fields of its own
  - a missing base field, a base field of another kind and a base field in a multi-data section are each refused,
    naming the marker and the fields; all findings of one document are reported together
  - a group's ``members`` selector keeps its settings: persons only, several of them
  - a type without such a marker (none, a singleton, an unknown value) is not judged
"""
from typing import Any

import pytest

from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.type_constants import STRUCTURE_ERROR_SEPARATOR, TypeStructureError
from cmdb.models.type_model.type_structure_rules import STRUCTURE_RULES, validate_type_structure
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_type_constants import (
    LOCKED_BASE_FIELDS,
    LOCKED_BASE_FIELD_SETTINGS,
    PersonField,
    PersonGroupField,
)
# -------------------------------------------------------------------------------------------------------------------- #

EXTRA_FIELD: str = 'department'
SECTION_NAME: str = 'person-section'
ROWS_SECTION_NAME: str = 'rows-section'


def _field(name: str, kind: str) -> dict[str, Any]:
    """One field declaration"""
    return {'name': name, 'type': kind, 'label': name.title()}


def _base_fields(marker: SpecialType) -> list[dict[str, Any]]:
    """Every base field of the marker, with its kind and - for a base person selector - its locked settings"""
    settings: dict[str, dict[str, Any]] = LOCKED_BASE_FIELD_SETTINGS.get(marker, {})

    return [{**_field(name, kind.value), **settings.get(name, {})} for name, kind in LOCKED_BASE_FIELDS[marker].items()]


def _type(marker: Any, fields: list[dict[str, Any]], rows: list[str] | None = None) -> dict[str, Any]:
    """A type document with the marker; every field in one section, the names in `rows` in a multi-data section"""
    rows = rows or []
    sections: list[dict[str, Any]] = [{
        'type': SectionType.SECTION.value, 'name': SECTION_NAME, 'label': 'Person',
        'fields': [field['name'] for field in fields if field['name'] not in rows],
    }]

    if rows:
        sections.append({'type': SectionType.MDS_SECTION.value, 'name': ROWS_SECTION_NAME, 'label': 'Rows',
                         'fields': rows})

    return {'name': 'person-type', 'special_type': marker, 'fields': fields, 'render_meta': {'sections': sections}}


def test_the_person_base_fields() -> None:
    """Names and kinds every PERSON type keeps; distinct kinds per field pin a swap"""
    assert LOCKED_BASE_FIELDS[SpecialType.PERSON] == {
        PersonField.DISPLAY_NAME.value: FieldType.TEXT,
        PersonField.FIRST_NAME.value: FieldType.TEXT,
        PersonField.LAST_NAME.value: FieldType.TEXT,
        PersonField.PHONE_NUMBER.value: FieldType.TEXT,
        PersonField.EMAIL.value: FieldType.TEXT,
        PersonField.USER.value: FieldType.NUMBER,
    }
    assert [member.value for member in PersonField] == [
        'display_name', 'first_name', 'last_name', 'phone_number', 'email', 'user',
    ]


def test_the_person_group_base_fields() -> None:
    """Names and kinds every PERSON_GROUP type keeps"""
    assert LOCKED_BASE_FIELDS[SpecialType.PERSON_GROUP] == {
        PersonGroupField.NAME.value: FieldType.TEXT,
        PersonGroupField.EMAIL.value: FieldType.TEXT,
        PersonGroupField.MEMBERS.value: FieldType.PERSON,
    }


def test_a_groups_members_select_several_persons() -> None:
    """The only base person selector, and its locked settings"""
    assert LOCKED_BASE_FIELD_SETTINGS == {
        SpecialType.PERSON_GROUP: {PersonGroupField.MEMBERS.value: {'selectable': ['PERSON'], 'multiple': True}},
    }


@pytest.mark.parametrize('settings', [
    {'selectable': ['PERSON', 'PERSON_GROUP'], 'multiple': True},
    {'selectable': ['PERSON'], 'multiple': False},
], ids=['groups-too', 'one-member'])
def test_changed_members_settings_are_refused(settings: dict[str, Any]) -> None:
    """Named with what they must be"""
    fields = [
        {**field, **settings} if field['name'] == PersonGroupField.MEMBERS.value else field
        for field in _base_fields(SpecialType.PERSON_GROUP)
    ]

    assert validate_type_structure(_type('PERSON_GROUP', fields)) == \
        TypeStructureError.BASE_FIELDS_SETTINGS_CHANGED.format(
            special_type='PERSON_GROUP', fields=["members (selectable=['PERSON'], multiple=True)"],
        )


def test_only_the_markers_several_types_may_carry_have_base_fields() -> None:
    """A singleton keeps its schema through its own feature rules"""
    assert set(LOCKED_BASE_FIELDS) == SpecialType.get_multiple_types()


@pytest.mark.parametrize('marker', [SpecialType.PERSON, SpecialType.PERSON_GROUP], ids=str)
def test_a_type_keeping_its_base_fields_passes(marker: SpecialType) -> None:
    """And it may add a field of its own"""
    assert validate_type_structure(_type(marker.value, [*_base_fields(marker), _field(EXTRA_FIELD, 'text')])) is None


@pytest.mark.parametrize('marker', [SpecialType.PERSON, SpecialType.PERSON_GROUP], ids=str)
def test_a_missing_base_field_is_refused(marker: SpecialType) -> None:
    """Named, together with the marker"""
    dropped: str = next(iter(LOCKED_BASE_FIELDS[marker]))
    fields = [field for field in _base_fields(marker) if field['name'] != dropped]

    assert validate_type_structure(_type(marker.value, fields)) == TypeStructureError.BASE_FIELDS_MISSING.format(
        special_type=marker.value, names=[dropped],
    )


def test_a_base_field_of_another_kind_is_refused() -> None:
    """The kind it must keep is named"""
    fields = [
        _field(name, 'text' if name == PersonField.USER.value else kind.value)
        for name, kind in LOCKED_BASE_FIELDS[SpecialType.PERSON].items()
    ]

    assert validate_type_structure(_type('PERSON', fields)) == TypeStructureError.BASE_FIELDS_KIND_CHANGED.format(
        special_type='PERSON', fields=['user (number)'],
    )


def test_a_base_field_in_a_multi_data_section_is_refused() -> None:
    """Its value would live in rows, not on the object"""
    document = _type('PERSON_GROUP', _base_fields(SpecialType.PERSON_GROUP), rows=[PersonGroupField.EMAIL.value])

    assert validate_type_structure(document) == TypeStructureError.BASE_FIELDS_IN_MULTI_DATA_SECTION.format(
        special_type='PERSON_GROUP', names=['email'],
    )


def test_every_finding_is_reported_together() -> None:
    """Missing, changed and in rows, in that order"""
    fields = [
        _field(PersonField.DISPLAY_NAME.value, 'text'),
        _field(PersonField.FIRST_NAME.value, 'text'),
        _field(PersonField.LAST_NAME.value, 'textarea'),
        _field(PersonField.PHONE_NUMBER.value, 'text'),
        _field(PersonField.EMAIL.value, 'text'),
    ]
    document = _type('PERSON', fields, rows=[PersonField.PHONE_NUMBER.value])

    assert validate_type_structure(document) == STRUCTURE_ERROR_SEPARATOR.join([
        TypeStructureError.BASE_FIELDS_MISSING.format(special_type='PERSON', names=['user']),
        TypeStructureError.BASE_FIELDS_KIND_CHANGED.format(special_type='PERSON', fields=['last_name (text)']),
        TypeStructureError.BASE_FIELDS_IN_MULTI_DATA_SECTION.format(special_type='PERSON', names=['phone_number']),
    ])


@pytest.mark.parametrize('marker', [None, '', 'RACK', 'NOT_A_SPECIAL_TYPE'], ids=str)
def test_a_type_without_such_a_marker_is_not_judged(marker: Any) -> None:
    """None of the person base fields is required of it"""
    assert validate_type_structure(_type(marker, [_field(EXTRA_FIELD, 'text')])) is None


def test_the_rule_is_registered() -> None:
    """It runs on every path that asks validate_type_structure - the type routes and both import verbs"""
    assert '_locked_base_field_errors' in {rule.__name__ for rule in STRUCTURE_RULES}
