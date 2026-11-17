# DataGerry - OpenSource Enterprise CMDB
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
Integration tests for cmdb.database.updater.versions.updater_20261119 against a real MongoDB

A scratch database holds what an installation from before step 6 holds: no person Type (only this migration stores
the defaults), three person records, two group records (one naming a person that does not exist), user groups with old
person rights, a risk assessment and a control-measure assignment pointing at persons and groups (one at a person that
does not exist). Pinned:

  - every record becomes an object of its default Type (base fields, members mapped, the system the
    author), the id map holds one entry per record, the old collections are renamed ``_migrated``
  - every ISMS reference names the new object id, ``*_ref_type`` kept, a dangling one emptied; no flag is left
  - the old rights are ACL entries of the default Types, the ACL is on
  - every migrated object carries one CREATE log written by the system
  - a second run changes nothing; a run stopped after the id map, after part of the ISMS rewrite, or after the rename
    finishes without a second object, a second mapping or a second log
  - a database without an old record (a new one with empty old collections, a staging database) is left alone
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions import updater_20261119 as module
from cmdb.database.updater.versions.updater_20261119 import Update20261119
from cmdb.models.log_model.log_action_enum import LogAction
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-updater-20261119'
VERSION: int = 20261119

ADA, BOB, EVE = 11, 12, 13
OPS, DEV = 21, 22
MISSING_PERSON: int = 99
ADMIN_GROUP, VIEWER_GROUP, GROUP_EDITOR_GROUP = 1, 5, 6

PERSONS: list[dict[str, Any]] = [
    {'public_id': ADA, 'display_name': 'Ada L', 'first_name': 'Ada', 'last_name': 'Lovelace', 'phone_number': '1',
     'email': 'ada@example.com', 'groups': [OPS]},
    {'public_id': BOB, 'display_name': 'Bob B', 'first_name': 'Bob', 'last_name': 'Builder', 'phone_number': '',
     'email': '', 'groups': [OPS, DEV]},
    {'public_id': EVE, 'display_name': 'Eve E', 'first_name': 'Eve', 'last_name': 'Example', 'phone_number': '',
     'email': '', 'groups': []},
]
GROUPS: list[dict[str, Any]] = [
    {'public_id': OPS, 'name': 'Operations', 'email': 'ops@example.com', 'group_members': [ADA, BOB, MISSING_PERSON]},
    {'public_id': DEV, 'name': 'Development', 'email': '', 'group_members': []},
]
USER_GROUPS: list[dict[str, Any]] = [
    {'public_id': ADMIN_GROUP, 'name': 'admin', 'label': 'Admin', 'rights': ['base.*']},
    {'public_id': VIEWER_GROUP, 'name': 'viewer', 'label': 'Viewer',
     'rights': ['base.user-management.person.view', 'base.framework.object.view']},
    {'public_id': GROUP_EDITOR_GROUP, 'name': 'group-editor', 'label': 'Group editor',
     'rights': ['base.user-management.personGroup.*']},
]
RISK_ASSESSMENT: dict[str, Any] = {
    'public_id': 1, 'risk_owner_id': ADA, 'risk_owner_id_ref_type': 'PERSON',
    'responsible_persons_id': OPS, 'responsible_persons_id_ref_type': 'PERSON_GROUP',
    'auditor_id': MISSING_PERSON, 'auditor_id_ref_type': 'PERSON',
    'risk_assessor_id': BOB, 'interviewed_persons': [EVE, MISSING_PERSON, ADA],
}
ASSIGNMENT: dict[str, Any] = {
    'public_id': 1, 'responsible_for_implementation_id': DEV,
    'responsible_for_implementation_id_ref_type': 'PERSON_GROUP',
}


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """A database as it was before step 6, dropped before and after"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)

    for collection, rows in ((module.PERSONS, PERSONS), (module.PERSON_GROUPS, GROUPS),
                             (module.USER_GROUPS, USER_GROUPS), (module.RISK_ASSESSMENTS, [RISK_ASSESSMENT]),
                             (module.CONTROL_MEASURE_ASSIGNMENTS, [ASSIGNMENT])):
        client[scratch][collection].insert_many([dict(row) for row in rows])

    yield scratch

    client.drop_database(scratch)


def _run(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """One run of the update"""
    Update20261119(database_manager, scratch).start_update()


def _db(database_manager: MongoDatabaseManager, scratch: str) -> Any:
    """The scratch database handle"""
    return database_manager.connector.client[scratch]


def _ids(db: Any, kind: str) -> dict[int, int]:
    """New object id by old id"""
    return {entry['old_id']: entry['new_object_id'] for entry in db[module.ID_MAP].find({'kind': kind})}


def _values(db: Any, object_id: int) -> dict[str, Any]:
    """An object's field values by name"""
    return {entry['name']: entry['value'] for entry in db[module.OBJECTS].find_one({'public_id': object_id})['fields']}


def _default_type(db: Any, marker: str) -> dict[str, Any]:
    """The default Type of a marker"""
    return db[module.TYPES].find_one({'special_type': marker, 'system_type': True})


def _snapshot(db: Any) -> dict[str, Any]:
    """Everything the update writes, without the Mongo ids"""
    return {collection: list(db[collection].find({}, {'_id': 0, 'log_time': 0, 'creation_time': 0}))
            for collection in (module.OBJECTS, module.ID_MAP, module.RISK_ASSESSMENTS,
                               module.CONTROL_MEASURE_ASSIGNMENTS, module.TYPES)} | {
        'logs': db[module.LOGS].count_documents({})}


class TestTheMigration:
    """One run on the database as it was"""

    def test_every_record_becomes_an_object_of_its_default_type(self, database_manager, scratch) -> None:
        """Base fields, members mapped (the missing person dropped), the system the author"""
        _run(database_manager, scratch)
        db = _db(database_manager, scratch)
        persons, groups = _ids(db, 'PERSON'), _ids(db, 'PERSON_GROUP')

        assert sorted(persons) == [ADA, BOB, EVE] and sorted(groups) == [OPS, DEV]
        assert _values(db, persons[ADA]) == {
            'display_name': 'Ada L', 'first_name': 'Ada', 'last_name': 'Lovelace', 'phone_number': '1',
            'email': 'ada@example.com',
        }
        assert _values(db, groups[OPS]) == {'name': 'Operations', 'email': 'ops@example.com',
                                             'members': [persons[ADA], persons[BOB]]}
        stored = db[module.OBJECTS].find_one({'public_id': groups[OPS]})
        assert (stored['type_id'], stored['special_type'], stored['author_id']) == (
            _default_type(db, 'PERSON_GROUP')['public_id'], 'PERSON_GROUP', 0)

    def test_the_old_collections_are_renamed(self, database_manager, scratch) -> None:
        """Kept, under _migrated"""
        _run(database_manager, scratch)
        names = set(_db(database_manager, scratch).list_collection_names())

        assert {f'{module.PERSONS}_migrated', f'{module.PERSON_GROUPS}_migrated'} <= names
        assert not {module.PERSONS, module.PERSON_GROUPS} & names

    def test_the_isms_references_name_the_new_ids(self, database_manager, scratch) -> None:
        """ref types kept, the dangling auditor emptied, the missing interviewee dropped, no flag left"""
        _run(database_manager, scratch)
        db = _db(database_manager, scratch)
        persons, groups = _ids(db, 'PERSON'), _ids(db, 'PERSON_GROUP')
        assessment = db[module.RISK_ASSESSMENTS].find_one({}, {'_id': 0})
        assignment = db[module.CONTROL_MEASURE_ASSIGNMENTS].find_one({}, {'_id': 0})

        assert assessment == {**RISK_ASSESSMENT, 'risk_owner_id': persons[ADA], 'responsible_persons_id': groups[OPS],
                              'auditor_id': None, 'risk_assessor_id': persons[BOB],
                              'interviewed_persons': [persons[EVE], persons[ADA]]}
        assert assignment == {**ASSIGNMENT, 'responsible_for_implementation_id': groups[DEV]}

    def test_the_old_rights_are_acl_entries_and_the_acl_is_on(self, database_manager, scratch) -> None:
        """base.* everything; view = READ; personGroup.* only on the group type"""
        _run(database_manager, scratch)
        db = _db(database_manager, scratch)
        everything = ['CREATE', 'READ', 'UPDATE', 'DELETE']

        assert _default_type(db, 'PERSON')['acl'] == {'activated': True, 'groups': {'includes': {
            str(ADMIN_GROUP): everything, str(VIEWER_GROUP): ['READ']}}}
        assert _default_type(db, 'PERSON_GROUP')['acl'] == {'activated': True, 'groups': {'includes': {
            str(ADMIN_GROUP): everything, str(GROUP_EDITOR_GROUP): everything}}}

    def test_every_object_gets_one_creation_log_by_the_system(self, database_manager, scratch) -> None:
        """Five objects, five CREATE logs, each with the rendered object and the type stamped"""
        _run(database_manager, scratch)
        db = _db(database_manager, scratch)
        logs = list(db[module.LOGS].find())

        assert sorted(log['object_id'] for log in logs) == sorted(
            [*_ids(db, 'PERSON').values(), *_ids(db, 'PERSON_GROUP').values()])
        assert {(log['user_id'], log['comment'], log['action']) for log in logs} == {
            (module.SYSTEM_AUTHOR_ID, module.LOG_COMMENT, LogAction.CREATE.value)}
        assert all(log['render_state'] and log['type_id'] for log in logs)

    def test_the_version_is_written(self, database_manager, scratch) -> None:
        """The settings record the update"""
        _run(database_manager, scratch)

        assert _db(database_manager, scratch)['settings.conf'].find_one({'_id': 'updater'})['version'] == VERSION


class TestRerunSafety:
    """Any run after a stop finishes the job without doubling anything"""

    def test_a_second_run_changes_nothing(self, database_manager, scratch) -> None:
        """Same objects, map, references, ACL and logs"""
        _run(database_manager, scratch)
        before = _snapshot(_db(database_manager, scratch))

        _run(database_manager, scratch)

        assert _snapshot(_db(database_manager, scratch)) == before

    def test_a_stop_after_the_id_map_writes_the_objects_under_the_mapped_ids(self, database_manager, scratch) -> None:
        """The map entries exist, the objects not: one object per record, under the mapped id"""
        update = Update20261119(database_manager, scratch)
        update._assign_new_ids('PERSON', PERSONS)  # pylint: disable=protected-access
        mapped = _ids(_db(database_manager, scratch), 'PERSON')

        _run(database_manager, scratch)
        db = _db(database_manager, scratch)

        assert _ids(db, 'PERSON') == mapped
        assert db[module.OBJECTS].count_documents({'special_type': 'PERSON'}) == len(PERSONS)

    def test_a_stop_inside_the_isms_rewrite_maps_no_id_twice(self, database_manager, scratch) -> None:
        """A document already rewritten and flagged is not mapped again"""
        db = _db(database_manager, scratch)
        already = {**RISK_ASSESSMENT, 'public_id': 2, 'risk_owner_id': 777, module.ISMS_FLAG: True}
        db[module.RISK_ASSESSMENTS].insert_one(already)

        _run(database_manager, scratch)

        assert db[module.RISK_ASSESSMENTS].find_one({'public_id': 2})['risk_owner_id'] == 777
        assert not db[module.RISK_ASSESSMENTS].count_documents({module.ISMS_FLAG: {'$exists': True}})

    def test_a_stop_after_the_rename_clears_the_flags_and_rewrites_nothing(self, database_manager, scratch) -> None:
        """The bring-up recreated empty old collections and a flag is left: no reference is touched again"""
        _run(database_manager, scratch)
        db = _db(database_manager, scratch)
        db.create_collection(module.PERSONS)
        db[module.RISK_ASSESSMENTS].update_many({}, {'$set': {module.ISMS_FLAG: True}})
        before = db[module.RISK_ASSESSMENTS].find_one({}, {'_id': 0, module.ISMS_FLAG: 0})

        _run(database_manager, scratch)

        assert db[module.RISK_ASSESSMENTS].find_one({}, {'_id': 0}) == before
        assert db[module.LOGS].count_documents({}) == len(PERSONS) + len(GROUPS)


def test_a_database_without_the_old_collections_is_left_alone(database_manager, database_name: str) -> None:
    """A staging database: no Type seeded, nothing written but the version"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}-staging'
    client = database_manager.connector.client
    client.drop_database(scratch)
    client[scratch][module.TYPES].insert_one({'public_id': 4, 'name': 'router'})

    try:
        _run(database_manager, scratch)

        assert [row['name'] for row in client[scratch][module.TYPES].find()] == ['router']
        assert set(client[scratch].list_collection_names()) == {module.TYPES, 'settings.conf'}
    finally:
        client.drop_database(scratch)


def test_empty_old_collections_are_nothing_to_migrate(database_manager, database_name: str) -> None:
    """Old collections that hold nothing: no map, no rename, and no default Type stored"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}-empty'
    client = database_manager.connector.client
    client.drop_database(scratch)
    client[scratch].create_collection(module.PERSONS)
    client[scratch].create_collection(module.PERSON_GROUPS)
    client[scratch][module.USER_GROUPS].insert_many([dict(row) for row in USER_GROUPS])

    try:
        _run(database_manager, scratch)

        assert not {module.ID_MAP, f'{module.PERSONS}_migrated'} & set(client[scratch].list_collection_names())
        assert not client[scratch][module.TYPES].count_documents({})
    finally:
        client.drop_database(scratch)
