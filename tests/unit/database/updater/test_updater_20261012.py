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
Unit tests for the pure builders of cmdb.database.updater.versions.updater_20261012

Pure tests: no Mongo. The migration itself runs against a real server in
tests/integration/database/test_integration_updater_20261012.py; pinned here is what it writes:

  - the object fields of a migrated person / group, one entry per schema field, in schema order, with the
    plain string row types (no enum member reaches the database)
  - the ISMS remap: each reference is mapped BY ITS KIND - an old person and an old group could share an id -
    an id naming nothing migrated becomes None, an unset reference stays as it is
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.versions.updater_20261012 import (
    MIGRATED_SUFFIX,
    PERSON_COLLECTION,
    PERSON_GROUP_COLLECTION,
    Update20261012,
    build_assignment_remap,
    build_group_fields,
    build_person_fields,
    build_risk_assessment_remap,
    int_ids,
    remap_reference,
    text,
)
from cmdb.models.special_type_model.person_constants import PersonField, PersonGroupField
from cmdb.models.special_type_model.schemas.person_schema import get_person_group_schema, get_person_schema
# -------------------------------------------------------------------------------------------------------------------- #

# Old id 7 is both a person and a group - the collision the remap must keep apart
MAPPING: dict[str, dict[int, int]] = {
    'PERSON': {7: 1007, 8: 1008},
    'PERSON_GROUP': {7: 2007},
}


def _values(fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {field['name']: field['value'] for field in fields}


def test_identity() -> None:
    """The registry key and the old collections"""
    updater = Update20261012.__new__(Update20261012)

    assert updater.creation_date() == 20261012
    assert updater.description()
    assert PERSON_COLLECTION == 'management.person'
    assert PERSON_GROUP_COLLECTION == 'management.personGroup'
    assert MIGRATED_SUFFIX == '.migrated'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    small helpers                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('value, expected', [('Ada', 'Ada'), ('', ''), (None, ''), (5, ''), (['x'], '')])
def test_text(value: Any, expected: str) -> None:
    """A text value of an old document, '' for anything that is no string"""
    assert text({'key': value}, 'key') == expected
    assert text({}, 'key') == ''


@pytest.mark.parametrize('value, expected', [
    ([3, 1, 3, 2], [3, 1, 2]),
    ([1, True, '2', None, 2.0, 4], [1, 4]),
    (None, []),
    ('1,2', []),
])
def test_int_ids(value: Any, expected: list[int]) -> None:
    """The integer ids of an old list, in order, deduplicated; bools and junk dropped"""
    assert int_ids(value) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    object fields                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_person_fields_copies_every_old_value() -> None:
    """Display name, names, email and phone number survive; the salutation did not exist"""
    fields = build_person_fields({
        'public_id': 4, 'display_name': 'Ada L.', 'first_name': 'Ada', 'last_name': 'Lovelace',
        'email': 'ada@example.com', 'phone_number': '+49 1', 'groups': [1],
    })

    assert _values(fields) == {
        PersonField.DISPLAY_NAME.value: 'Ada L.',
        PersonField.SALUTATION.value: None,
        PersonField.FIRST_NAME.value: 'Ada',
        PersonField.LAST_NAME.value: 'Lovelace',
        PersonField.EMAIL.value: 'ada@example.com',
        PersonField.PHONE_NUMBER.value: '+49 1',
    }


def test_build_person_fields_follows_the_schema_order_with_plain_types() -> None:
    """One entry per schema field; the stored 'type' and 'name' are plain strings, not enum members"""
    fields = build_person_fields({'display_name': 'Ada'})
    schema_fields = get_person_schema()['fields']

    assert [field['name'] for field in fields] == [field['name'].value for field in schema_fields]
    assert [field['type'] for field in fields] == [field['type'].value for field in schema_fields]
    assert all(type(field['name']) is str and type(field['type']) is str for field in fields)


@pytest.mark.parametrize('person, expected', [
    ({'first_name': 'Ada', 'last_name': 'Lovelace'}, 'Ada Lovelace'),
    ({'display_name': '', 'last_name': 'Lovelace'}, 'Lovelace'),
    ({'display_name': None, 'first_name': 'Ada'}, 'Ada'),
    ({}, ''),
])
def test_a_missing_display_name_is_built_from_the_names(person: dict[str, Any], expected: str) -> None:
    """The full name is the label of the new object, so it is derived when the old document lacks one"""
    assert _values(build_person_fields(person))[PersonField.DISPLAY_NAME.value] == expected


def test_a_person_with_null_values_gets_empty_text() -> None:
    """Old documents could still hold null (see updater_20260909)"""
    values = _values(build_person_fields({'display_name': 'Ada', 'email': None, 'phone_number': None}))

    assert values[PersonField.EMAIL.value] == ''
    assert values[PersonField.PHONE_NUMBER.value] == ''


def test_build_group_fields() -> None:
    """Name, email and the members as PERSON selections of the NEW ids"""
    fields = build_group_fields({'public_id': 3, 'name': 'Security', 'email': 'sec@example.com'}, [1007, 1008])

    assert _values(fields) == {
        PersonGroupField.NAME.value: 'Security',
        PersonGroupField.EMAIL.value: 'sec@example.com',
        PersonGroupField.MEMBERS.value: [{'ref_type': 'PERSON', 'id': 1007}, {'ref_type': 'PERSON', 'id': 1008}],
    }
    assert [field['type'] for field in fields] == [field['type'].value for field in get_person_group_schema()['fields']]
    assert next(field for field in fields if field['name'] == PersonGroupField.MEMBERS.value)['type'] == 'person'


def test_a_nameless_group_is_named_by_its_old_id() -> None:
    """The group name is required on the new type"""
    values = _values(build_group_fields({'public_id': 3, 'name': ''}, []))

    assert values[PersonGroupField.NAME.value] == '#3'
    assert values[PersonGroupField.MEMBERS.value] == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       ISMS remap                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('kind, value, expected', [
    ('PERSON', 7, 1007),
    ('PERSON_GROUP', 7, 2007),
    ('PERSON', 99, None),
    ('PERSON_GROUP', 8, None),
    ('PERSON', None, None),
    (None, 7, 7),
    ('NOBODY', 7, 7),
])
def test_remap_reference(kind: str | None, value: Any, expected: Any) -> None:
    """By kind; an unmapped id becomes None; an unknown kind leaves the stored value"""
    assert remap_reference({'key': value}, 'key', kind, MAPPING) == expected


def test_build_risk_assessment_remap_maps_every_key_by_its_kind() -> None:
    """The colliding id 7 resolves to the person for a PERSON ref_type and to the group for a PERSON_GROUP one"""
    document = {
        'risk_owner_id': 7, 'risk_owner_id_ref_type': 'PERSON',
        'responsible_persons_id': 7, 'responsible_persons_id_ref_type': 'PERSON_GROUP',
        'auditor_id': 99, 'auditor_id_ref_type': 'PERSON',
        'risk_assessor_id': 8,
        'interviewed_persons': [8, 99, 7, 8],
    }

    assert build_risk_assessment_remap(document, MAPPING) == {
        'risk_owner_id': 1007,
        'responsible_persons_id': 2007,
        'auditor_id': None,
        'risk_assessor_id': 1008,
        'interviewed_persons': [1008, 1007],
    }


def test_build_risk_assessment_remap_leaves_unset_references_out() -> None:
    """A document referencing nobody needs no write"""
    document = {'risk_owner_id': None, 'risk_owner_id_ref_type': 'PERSON', 'risk_assessor_id': None}

    assert build_risk_assessment_remap(document, MAPPING) == {}


def test_the_interviewed_persons_are_always_persons() -> None:
    """A person-only list is mapped through the person half even where a group shares the id"""
    assert build_risk_assessment_remap({'interviewed_persons': [7]}, MAPPING) == {'interviewed_persons': [1007]}


def test_build_assignment_remap() -> None:
    """The responsible party of a control measure assignment, by its kind"""
    group = {'responsible_for_implementation_id': 7, 'responsible_for_implementation_id_ref_type': 'PERSON_GROUP'}
    unset = {'responsible_for_implementation_id': None}

    assert build_assignment_remap(group, MAPPING) == {'responsible_for_implementation_id': 2007}
    assert build_assignment_remap(unset, MAPPING) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     start_update                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def _updater() -> Update20261012:
    updater = Update20261012.__new__(Update20261012)
    updater.dbm = MagicMock()
    updater.db_name = 'testdb'
    updater.settings_manager = MagicMock()

    return updater


def test_an_empty_database_only_bumps_the_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """No old collection: no type is created, nothing is renamed"""
    updater = _updater()
    updater.dbm.get_collection.return_value.database.list_collection_names.return_value = ['framework.objects']
    bumped = MagicMock()
    migrate = MagicMock()
    monkeypatch.setattr(updater, 'increase_updater_version', bumped)
    monkeypatch.setattr(updater, '_migrate', migrate)

    updater.start_update()

    migrate.assert_not_called()
    updater.dbm.get_collection.return_value.rename.assert_not_called()
    bumped.assert_called_once_with(20261012)


def test_a_failure_is_raised_as_an_updater_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """The version is not bumped when a step failed, so the next start retries"""
    updater = _updater()
    updater.dbm.get_collection.side_effect = RuntimeError('mongo down')
    bumped = MagicMock()
    monkeypatch.setattr(updater, 'increase_updater_version', bumped)

    with pytest.raises(UpdaterException):
        updater.start_update()

    bumped.assert_not_called()
