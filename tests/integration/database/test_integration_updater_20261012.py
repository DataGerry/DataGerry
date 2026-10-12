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
Integration tests for cmdb.database.updater.versions.updater_20261012 against a real MongoDB

Seeds the pre-migration state - persons in ``management.person``, groups in ``management.personGroup`` with a
membership stored on one side only, a person and a group sharing an old id, and ISMS documents referencing
them - runs the migration and asserts:

  - a CmdbType of each person SpecialType is created, an existing one is reused
  - every person and group became an object of that type; a group's members are the union of both stored sides
  - every ISMS reference was rewritten by its kind, an id naming nothing migrated became None
  - the old collections were renamed to '<name>.migrated', and the old -> new mapping is recorded
  - a second run changes nothing, and a run whose old collections came back (an interrupted run) creates no
    duplicate object and does not remap the ISMS references a second time
  - a database without persons and groups is left alone: no type is created
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261012 import (
    MIGRATION_COLLECTION,
    PERSON_COLLECTION,
    PERSON_GROUP_COLLECTION,
    Update20261012,
)
from cmdb.framework.person.person_values import get_person_field_definitions
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_constants import PersonField, PersonGroupField
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

ADA_OLD: int = 1
BOB_OLD: int = 2
SHARED_OLD: int = 3          # a person AND a group carry this old id
GROUP_OLD: int = 4

RISK_ASSESSMENT_ID: int = 97101
ASSIGNMENT_ID: int = 97102

OLD_COLLECTIONS: tuple[str, ...] = (PERSON_COLLECTION, PERSON_GROUP_COLLECTION)

PERSONS: list[dict[str, Any]] = [
    {'public_id': ADA_OLD, 'display_name': 'Ada Lovelace', 'first_name': 'Ada', 'last_name': 'Lovelace',
     'email': 'ada@example.com', 'phone_number': '+49 1', 'groups': [GROUP_OLD]},
    # Bob's membership of GROUP_OLD is only stored on his side
    {'public_id': BOB_OLD, 'display_name': '', 'first_name': 'Bob', 'last_name': 'Builder',
     'email': None, 'phone_number': None, 'groups': [GROUP_OLD, 999]},
    {'public_id': SHARED_OLD, 'display_name': 'Carol', 'first_name': 'Carol', 'last_name': 'C',
     'email': '', 'phone_number': '', 'groups': []},
]

GROUPS: list[dict[str, Any]] = [
    # Ada is listed here; a member id naming no person is dropped
    {'public_id': GROUP_OLD, 'name': 'Security', 'email': 'sec@example.com', 'group_members': [ADA_OLD, 777]},
    {'public_id': SHARED_OLD, 'name': 'Audit', 'email': '', 'group_members': [SHARED_OLD]},
]


def _person_type_ids(database_manager: MongoDatabaseManager, database_name: str) -> list[int]:
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    return [doc['public_id'] for doc in types.find({'special_type': {'$in': ['PERSON', 'PERSON_GROUP']}})]


def _purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes everything a run may have created, and the seeds"""
    database = database_manager.get_collection(CmdbType.COLLECTION, database_name).database
    type_ids: list[int] = _person_type_ids(database_manager, database_name)

    database[CmdbObject.COLLECTION].delete_many({'type_id': {'$in': type_ids}})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': type_ids}})
    database[IsmsRiskAssessment.COLLECTION].delete_many({'public_id': RISK_ASSESSMENT_ID})
    database[IsmsControlMeasureAssignment.COLLECTION].delete_many({'public_id': ASSIGNMENT_ID})

    for name in database.list_collection_names():
        if name == MIGRATION_COLLECTION or any(name.startswith(old) for old in OLD_COLLECTIONS):
            database.drop_collection(name)


@pytest.fixture(name='database')
def fixture_database(database_manager: MongoDatabaseManager, database_name: str):
    """The raw pymongo database, purged before and after"""
    _purge(database_manager, database_name)
    yield database_manager.get_collection(CmdbType.COLLECTION, database_name).database
    _purge(database_manager, database_name)


@pytest.fixture(name='seeded')
def fixture_seeded(database: Any):
    """The old person / group documents and two ISMS documents referencing them"""
    database[PERSON_COLLECTION].insert_many([dict(person) for person in PERSONS])
    database[PERSON_GROUP_COLLECTION].insert_many([dict(group) for group in GROUPS])
    database[IsmsRiskAssessment.COLLECTION].insert_one({
        'public_id': RISK_ASSESSMENT_ID,
        'risk_owner_id': SHARED_OLD, 'risk_owner_id_ref_type': 'PERSON',
        'responsible_persons_id': SHARED_OLD, 'responsible_persons_id_ref_type': 'PERSON_GROUP',
        'auditor_id': 555, 'auditor_id_ref_type': 'PERSON',
        'risk_assessor_id': ADA_OLD,
        'interviewed_persons': [BOB_OLD, 555, SHARED_OLD],
    })
    database[IsmsControlMeasureAssignment.COLLECTION].insert_one({
        'public_id': ASSIGNMENT_ID,
        'responsible_for_implementation_id': GROUP_OLD,
        'responsible_for_implementation_id_ref_type': 'PERSON_GROUP',
    })

    return database


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    Update20261012(database_manager, database_name).start_update()


def _mapping(database: Any) -> dict[str, dict[int, int]]:
    mapping: dict[str, dict[int, int]] = {'PERSON': {}, 'PERSON_GROUP': {}}

    for row in database[MIGRATION_COLLECTION].find({'kind': {'$exists': True}}):
        mapping[row['kind']][row['old_id']] = row['new_id']

    return mapping


def _values(document: dict[str, Any]) -> dict[str, Any]:
    return {field['name']: field['value'] for field in document['fields']}


def _person_objects(database: Any) -> list[dict[str, Any]]:
    type_ids = [doc['public_id'] for doc in database[CmdbType.COLLECTION].find(
        {'special_type': {'$in': ['PERSON', 'PERSON_GROUP']}})]

    return list(database[CmdbObject.COLLECTION].find({'type_id': {'$in': type_ids}}, {'_id': 0}))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        a run                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMigration:
    """One run over the seeded state"""

    def test_creates_one_type_per_person_special_type(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded: Any) -> None:
        """Built from the predefined schemas; the group type's MEMBERS field is a multiple PERSON field"""
        _run(database_manager, database_name)

        person_type = seeded[CmdbType.COLLECTION].find_one({'special_type': 'PERSON'})
        group_type = seeded[CmdbType.COLLECTION].find_one({'special_type': 'PERSON_GROUP'})

        assert person_type['name'] == 'dg_person'
        assert group_type['name'] == 'dg_person_group'
        assert person_type['render_meta']['summary']['fields'] == [PersonField.DISPLAY_NAME.value]

        members = get_person_field_definitions(group_type['fields'])[PersonGroupField.MEMBERS.value]

        assert members['person_ref_kind'] == 'PERSON'
        assert members['multiple'] is True

    def test_every_person_and_group_becomes_an_object(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded: Any) -> None:
        """Three persons, two groups - the colliding old id included"""
        _run(database_manager, database_name)

        mapping = _mapping(seeded)

        assert set(mapping['PERSON']) == {ADA_OLD, BOB_OLD, SHARED_OLD}
        assert set(mapping['PERSON_GROUP']) == {GROUP_OLD, SHARED_OLD}
        assert len(set(mapping['PERSON'].values()) | set(mapping['PERSON_GROUP'].values())) == 5
        assert len(_person_objects(seeded)) == 5

    def test_a_person_keeps_its_values(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded: Any) -> None:
        """Names, email and phone; a null becomes ''; a blank display name is built from the names"""
        _run(database_manager, database_name)

        mapping = _mapping(seeded)
        ada = seeded[CmdbObject.COLLECTION].find_one({'public_id': mapping['PERSON'][ADA_OLD]})
        bob = seeded[CmdbObject.COLLECTION].find_one({'public_id': mapping['PERSON'][BOB_OLD]})

        assert _values(ada)[PersonField.DISPLAY_NAME.value] == 'Ada Lovelace'
        assert _values(ada)[PersonField.EMAIL.value] == 'ada@example.com'
        assert _values(ada)[PersonField.PHONE_NUMBER.value] == '+49 1'
        assert _values(bob)[PersonField.DISPLAY_NAME.value] == 'Bob Builder'
        assert _values(bob)[PersonField.EMAIL.value] == ''
        assert ada['author_id'] == 1
        assert ada['active'] is True

    def test_the_members_are_the_union_of_both_stored_sides(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded: Any) -> None:
        """Ada was listed by the group, Bob only listed the group; ids naming no person are dropped"""
        _run(database_manager, database_name)

        mapping = _mapping(seeded)
        security = seeded[CmdbObject.COLLECTION].find_one({'public_id': mapping['PERSON_GROUP'][GROUP_OLD]})
        audit = seeded[CmdbObject.COLLECTION].find_one({'public_id': mapping['PERSON_GROUP'][SHARED_OLD]})

        assert _values(security)[PersonGroupField.NAME.value] == 'Security'
        assert _values(security)[PersonGroupField.MEMBERS.value] == [
            {'ref_type': 'PERSON', 'id': mapping['PERSON'][ADA_OLD]},
            {'ref_type': 'PERSON', 'id': mapping['PERSON'][BOB_OLD]},
        ]
        # The group's old member id 3 is the PERSON 3 (Carol), not the group itself
        assert _values(audit)[PersonGroupField.MEMBERS.value] == [
            {'ref_type': 'PERSON', 'id': mapping['PERSON'][SHARED_OLD]},
        ]
        members_row = next(f for f in security['fields'] if f['name'] == PersonGroupField.MEMBERS.value)
        assert members_row['type'] == 'person'

    def test_the_isms_references_are_remapped_by_kind(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded: Any) -> None:
        """The shared old id resolves per ref_type; an id naming nothing migrated is cleared"""
        _run(database_manager, database_name)

        mapping = _mapping(seeded)
        assessment = seeded[IsmsRiskAssessment.COLLECTION].find_one({'public_id': RISK_ASSESSMENT_ID})
        assignment = seeded[IsmsControlMeasureAssignment.COLLECTION].find_one({'public_id': ASSIGNMENT_ID})

        assert assessment['risk_owner_id'] == mapping['PERSON'][SHARED_OLD]
        assert assessment['responsible_persons_id'] == mapping['PERSON_GROUP'][SHARED_OLD]
        assert assessment['auditor_id'] is None
        assert assessment['risk_assessor_id'] == mapping['PERSON'][ADA_OLD]
        assert assessment['interviewed_persons'] == [mapping['PERSON'][BOB_OLD], mapping['PERSON'][SHARED_OLD]]
        assert assessment['risk_owner_id_ref_type'] == 'PERSON'
        assert assignment['responsible_for_implementation_id'] == mapping['PERSON_GROUP'][GROUP_OLD]

    def test_the_old_collections_are_renamed(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded: Any) -> None:
        """Kept as a backup under '<name>.migrated', with every document"""
        _run(database_manager, database_name)

        names = seeded.list_collection_names()

        assert PERSON_COLLECTION not in names
        assert PERSON_GROUP_COLLECTION not in names
        assert seeded[f'{PERSON_COLLECTION}.migrated'].count_documents({}) == len(PERSONS)
        assert seeded[f'{PERSON_GROUP_COLLECTION}.migrated'].count_documents({}) == len(GROUPS)

    def test_an_existing_person_type_is_reused(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded: Any) -> None:
        """An administrator may already have created one: no second type of that SpecialType"""
        seeded[CmdbType.COLLECTION].insert_one({'public_id': 97199, 'name': 'my_people', 'special_type': 'PERSON',
                                                'fields': []})

        _run(database_manager, database_name)

        assert seeded[CmdbType.COLLECTION].count_documents({'special_type': 'PERSON'}) == 1
        ada = seeded[CmdbObject.COLLECTION].find_one({'public_id': _mapping(seeded)['PERSON'][ADA_OLD]})
        assert ada['type_id'] == 97199

    def test_a_taken_type_name_is_suffixed(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded: Any) -> None:
        """A user type already called 'dg_person' is not touched"""
        seeded[CmdbType.COLLECTION].insert_one({'public_id': 97198, 'name': 'dg_person', 'fields': []})

        try:
            _run(database_manager, database_name)

            assert seeded[CmdbType.COLLECTION].find_one({'special_type': 'PERSON'})['name'] == 'dg_person_2'
        finally:
            seeded[CmdbType.COLLECTION].delete_one({'public_id': 97198})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       re-runs                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReRun:
    """The migration is re-runnable"""

    def test_a_second_run_changes_nothing(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded: Any) -> None:
        """The old collections are gone, so there is nothing left to migrate"""
        _run(database_manager, database_name)
        objects_after_first = _person_objects(seeded)
        assessment_after_first = seeded[IsmsRiskAssessment.COLLECTION].find_one({'public_id': RISK_ASSESSMENT_ID})

        _run(database_manager, database_name)

        assert _person_objects(seeded) == objects_after_first
        assert seeded[IsmsRiskAssessment.COLLECTION].find_one({'public_id': RISK_ASSESSMENT_ID}) == assessment_after_first
        assert len(_person_type_ids(database_manager, database_name)) == 2

    def test_an_interrupted_run_reuses_what_it_created(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded: Any) -> None:
        """
        Old collections still present after objects and ISMS remap were written - the state a crash before the
        rename leaves: no object is created twice and the ISMS references are not remapped again
        """
        _run(database_manager, database_name)
        objects_after_first = _person_objects(seeded)
        assessment_after_first = seeded[IsmsRiskAssessment.COLLECTION].find_one({'public_id': RISK_ASSESSMENT_ID})

        seeded[f'{PERSON_COLLECTION}.migrated'].rename(PERSON_COLLECTION)
        seeded[f'{PERSON_GROUP_COLLECTION}.migrated'].rename(PERSON_GROUP_COLLECTION)

        _run(database_manager, database_name)

        assert _person_objects(seeded) == objects_after_first
        assert seeded[IsmsRiskAssessment.COLLECTION].find_one({'public_id': RISK_ASSESSMENT_ID}) == assessment_after_first
        assert PERSON_COLLECTION not in seeded.list_collection_names()

    def test_a_second_backup_does_not_overwrite_the_first(
            self, database_manager: MongoDatabaseManager, database_name: str, seeded: Any) -> None:
        """A '.migrated' collection that already exists gets a timestamped sibling instead"""
        seeded[f'{PERSON_COLLECTION}.migrated'].insert_one({'public_id': 1, 'backup': 'earlier'})

        _run(database_manager, database_name)

        names = [name for name in seeded.list_collection_names() if name.startswith(f'{PERSON_COLLECTION}.migrated')]

        assert len(names) == 2
        assert seeded[f'{PERSON_COLLECTION}.migrated'].find_one({'backup': 'earlier'}) is not None


def test_a_database_without_persons_is_left_alone(
        database_manager: MongoDatabaseManager, database_name: str, database: Any) -> None:
    """No type is created - an administrator creates them like any other SpecialType"""
    database[PERSON_COLLECTION].insert_one({'drop': 'me'})
    database[PERSON_COLLECTION].delete_many({})

    _run(database_manager, database_name)

    assert _person_type_ids(database_manager, database_name) == []
    assert MIGRATION_COLLECTION not in database.list_collection_names()
