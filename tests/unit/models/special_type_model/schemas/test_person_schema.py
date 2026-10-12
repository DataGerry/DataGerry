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
Unit tests for cmdb.models.special_type_model.schemas.person_schema

Pins the PERSON and PERSON_GROUP blueprints: the marker, the required label field each kind is shown by,
the MEMBERS field that is the one place a membership is stored, and that every field sits in exactly one
section. The person field keys ('person_ref_kind', 'multiple') are checked against the CmdbType Cerberus
schema too, so a blueprint the type route would refuse fails here

Pure tests: no Mongo, no Flask
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.type_model.cmdb_type_schema import get_cmdb_type_schema
from cmdb.models.type_model import FieldKey, FieldType, SectionKey, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.person_constants import (
    PersonField,
    PersonGroupField,
    PersonRefKind,
    SALUTATION_OPTIONS,
)
from cmdb.models.special_type_model.schemas.person_schema import get_person_group_schema, get_person_schema
from cmdb.models.special_type_model.schemas.schema_provider import SchemaProvider
from tests.utils.person_stubs import plain
# -------------------------------------------------------------------------------------------------------------------- #

BLUEPRINTS: list[tuple[SpecialType, Any]] = [
    (SpecialType.PERSON, get_person_schema),
    (SpecialType.PERSON_GROUP, get_person_group_schema),
]


def _fields_by_name(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {field[FieldKey.NAME]: field for field in schema[TypeSchemaKey.FIELDS]}


@pytest.mark.parametrize('special_type, builder', BLUEPRINTS, ids=str)
def test_the_blueprint_carries_its_marker(special_type: SpecialType, builder: Any) -> None:
    """The marker is what claims the SpecialType on insert"""
    assert builder()[TypeSchemaKey.SPECIAL_TYPE] == special_type


@pytest.mark.parametrize('special_type, builder', BLUEPRINTS, ids=str)
def test_the_provider_dispatches_to_the_blueprint(special_type: SpecialType, builder: Any) -> None:
    """SchemaProvider answers the person blueprints like any other SpecialType"""
    assert SchemaProvider().get_schema(special_type) == builder()


@pytest.mark.parametrize('special_type, builder', BLUEPRINTS, ids=str)
def test_every_field_sits_in_exactly_one_section(special_type: SpecialType, builder: Any) -> None:
    """A field outside every section is never rendered, one in two sections renders twice"""
    schema: dict[str, Any] = builder()
    placed: list[str] = [name for section in schema[TypeSchemaKey.SECTIONS] for name in section[SectionKey.FIELDS]]

    assert sorted(placed) == sorted(_fields_by_name(schema))


@pytest.mark.parametrize('special_type, builder', BLUEPRINTS, ids=str)
def test_a_fresh_blueprint_per_call(special_type: SpecialType, builder: Any) -> None:
    """The type constructor stores the lists it is given, so two calls must not share them"""
    first: dict[str, Any] = builder()
    second: dict[str, Any] = builder()

    assert first == second
    assert first[TypeSchemaKey.FIELDS] is not second[TypeSchemaKey.FIELDS]


def test_the_person_is_labelled_by_its_required_display_name() -> None:
    """The full name is the only required field and the first one - the summary field of the created type"""
    schema: dict[str, Any] = get_person_schema()
    fields: dict[str, dict[str, Any]] = _fields_by_name(schema)

    assert schema[TypeSchemaKey.FIELDS][0][FieldKey.NAME] == PersonField.DISPLAY_NAME
    assert fields[PersonField.DISPLAY_NAME][FieldKey.TYPE] == FieldType.TEXT
    assert [name for name, field in fields.items() if field.get(FieldKey.REQUIRED)] == [PersonField.DISPLAY_NAME]


def test_the_person_holds_every_person_field_and_no_person_reference() -> None:
    """Memberships are derived from the groups, so the PERSON blueprint has no person field of its own"""
    fields: dict[str, dict[str, Any]] = _fields_by_name(get_person_schema())

    assert set(fields) == set(PersonField)
    assert all(field[FieldKey.TYPE] != FieldType.PERSON for field in fields.values())


def test_the_salutation_offers_the_fixed_options() -> None:
    """The select's options are the SALUTATION_OPTIONS, in order"""
    salutation: dict[str, Any] = _fields_by_name(get_person_schema())[PersonField.SALUTATION]

    assert salutation[FieldKey.TYPE] == FieldType.SELECT
    assert [(option[FieldKey.NAME], option[FieldKey.LABEL]) for option in salutation[FieldKey.OPTIONS]] == list(
        SALUTATION_OPTIONS
    )


def test_the_group_is_labelled_by_its_required_name() -> None:
    """The group name is required and first"""
    schema: dict[str, Any] = get_person_group_schema()
    fields: dict[str, dict[str, Any]] = _fields_by_name(schema)

    assert schema[TypeSchemaKey.FIELDS][0][FieldKey.NAME] == PersonGroupField.NAME
    assert fields[PersonGroupField.NAME][FieldKey.REQUIRED] is True
    assert set(fields) == set(PersonGroupField)


def test_the_members_field_is_a_multiple_person_field_restricted_to_persons() -> None:
    """The one place a membership is stored: a list of PERSON selections"""
    members: dict[str, Any] = _fields_by_name(get_person_group_schema())[PersonGroupField.MEMBERS]

    assert members[FieldKey.TYPE] == FieldType.PERSON
    assert members[FieldKey.PERSON_REF_KIND] == PersonRefKind.PERSON
    assert members[FieldKey.MULTIPLE] is True


def _type_payload(fields: list[dict[str, Any]]) -> dict[str, Any]:
    names: list[str] = [field['name'] for field in fields]

    return {
        'name': 'person-schema-test',
        'label': 'Person schema test',
        'author_id': 1,
        'active': True,
        'fields': fields,
        'render_meta': {
            'icon': 'fa-user',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': names}],
            'summary': {'fields': names[:1]},
        },
        'version': '1.0.0',
    }


@pytest.mark.parametrize('builder', [get_person_schema, get_person_group_schema])
def test_the_type_schema_accepts_the_blueprint_fields(builder: Any) -> None:
    """The fields of a created person type pass the CmdbType schema the type routes validate with"""
    validator = Validator(get_cmdb_type_schema(), purge_unknown=True)

    assert validator.validate(_type_payload(plain(builder()[TypeSchemaKey.FIELDS]))), validator.errors


@pytest.mark.parametrize('ref_kind', [member.value for member in PersonRefKind])
def test_the_type_schema_accepts_every_person_ref_kind(ref_kind: str) -> None:
    """'person_ref_kind' takes exactly the PersonRefKind values"""
    validator = Validator(get_cmdb_type_schema(), purge_unknown=True)
    field: dict[str, Any] = {'type': 'person', 'name': 'owner', 'label': 'Owner',
                             'person_ref_kind': ref_kind, 'multiple': False}

    assert validator.validate(_type_payload([field])), validator.errors


@pytest.mark.parametrize('field_patch', [
    {'person_ref_kind': 'USER'},
    {'person_ref_kind': 'person'},
    {'multiple': 'yes'},
])
def test_the_type_schema_refuses_a_bad_person_field_key(field_patch: dict[str, Any]) -> None:
    """An unknown kind or a non-boolean 'multiple' is refused at the type route"""
    validator = Validator(get_cmdb_type_schema(), purge_unknown=True)
    field: dict[str, Any] = {'type': 'person', 'name': 'owner', 'label': 'Owner', **field_patch}

    assert not validator.validate(_type_payload([field]))


def test_the_person_keys_are_optional_on_the_type_schema() -> None:
    """A person field without the keys is valid - it then selects both kinds, singly"""
    validator = Validator(get_cmdb_type_schema(), purge_unknown=True)

    assert validator.validate(_type_payload([{'type': 'person', 'name': 'owner', 'label': 'Owner'}])), validator.errors
