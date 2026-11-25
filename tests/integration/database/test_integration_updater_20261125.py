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
Integration tests for cmdb.database.updater.versions.updater_20261125 against a real MongoDB

A scratch database with three groups, Types whose ACL is on (one naming a deleted group, one granting nobody), off and
absent, and a role an administrator stored under a name the translation would take. Asserts: the roles and
assignments stored decide as the ACLs did and skip the taken name; the report is complete and names each Type's
roles, assignments and dropped groups; the stored ACLs are untouched; a second run writes nothing; a run stopped after
the pending report finishes with exactly the planned documents; an ACL the translation would read otherwise stops the
migration before anything is written; a database without groups (a staging database) keeps its locked Types locked;
a database without an activated ACL gets nothing - no report, no role, no id drawn
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261125 import Update20261125
from cmdb.errors.updater import UpdaterException
from cmdb.framework.access_engine import AccessGrants, build_grants
from cmdb.models.access_model import ScopeOperation
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-updater-20261125'
TYPES: str = 'framework.types'
GROUPS: str = 'management.groups'
ROLES: str = 'access.scopeRoles'
ASSIGNMENTS: str = 'access.assignments'
REPORT: str = 'access.migrationReport'
SETTINGS: str = 'settings.conf'
COUNTERS: str = 'datastorage.counter'
REPORT_ID: str = 'type_acl_migration'

ADMIN_GROUP_ID: int = 1
OPERATORS_GROUP_ID: int = 21
AUDITORS_GROUP_ID: int = 22
GONE_GROUP_ID: int = 29
SERVER_TYPE_ID: int = 11
ROUTER_TYPE_ID: int = 12
FREE_TYPE_ID: int = 13
LOCKED_TYPE_ID: int = 14
PLAIN_TYPE_ID: int = 15
STORED_ROLE_ID: int = 7
TAKEN_NAME: str = 'view on 1 Type (translated from the type ACL)'
FIRST_ROLE_AFTER_STORED: int = STORED_ROLE_ID + 1
VERSION: int = 20261125


def _type(public_id: int, includes: dict[int, list[str]] | None, activated: Any = True) -> dict[str, Any]:
    """A stored Type; includes None stores no acl"""
    document: dict[str, Any] = {'public_id': public_id, 'name': f'type-{public_id}'}

    if includes is not None:
        document['acl'] = {'activated': activated,
                           'groups': {'includes': {str(group): values for group, values in includes.items()}}}

    return document


SEEDED_TYPES: list[dict[str, Any]] = [
    _type(SERVER_TYPE_ID, {OPERATORS_GROUP_ID: ['READ', 'UPDATE'], GONE_GROUP_ID: ['READ']}),
    _type(ROUTER_TYPE_ID, {AUDITORS_GROUP_ID: ['READ']}),
    _type(FREE_TYPE_ID, {OPERATORS_GROUP_ID: ['READ']}, activated=False),
    _type(LOCKED_TYPE_ID, {GONE_GROUP_ID: ['READ']}),
    _type(PLAIN_TYPE_ID, None),
]


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The seeded database, its role counter past the stored role; dropped before and after"""
    name: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(name)
    database = client[name]
    database[TYPES].insert_many([dict(document) for document in SEEDED_TYPES])
    database[GROUPS].insert_many([{'public_id': group_id, 'name': f'group-{group_id}'}
                                  for group_id in (ADMIN_GROUP_ID, OPERATORS_GROUP_ID, AUDITORS_GROUP_ID)])
    database[ROLES].insert_one({'public_id': STORED_ROLE_ID, 'name': TAKEN_NAME, 'description': '', 'types': [],
                                'operations': [], 'write_regular_fields': False, 'field_classes': []})
    database[COUNTERS].insert_many([{'_id': ROLES, 'counter': STORED_ROLE_ID}, {'_id': ASSIGNMENTS, 'counter': 0}])

    yield name, database

    client.drop_database(name)


def _run(database_manager: MongoDatabaseManager, name: str) -> None:
    """One run of the migration"""
    Update20261125(database_manager, name).start_update()


def _stored(database: Any, collection: str) -> list[dict[str, Any]]:
    """A collection without _id, ascending by public_id"""
    return list(database[collection].find({}, {'_id': 0}).sort('public_id', 1))


def _grants(database: Any, group_ids: tuple[int, ...]) -> AccessGrants:
    """What the engine reads from the stored roles and assignments for a user in those groups"""
    assignments = _stored(database, ASSIGNMENTS)
    assigned: set[int] = {assignment['role_id'] for assignment in assignments}

    return build_grants(assignments, [role for role in _stored(database, ROLES) if role['public_id'] in assigned],
                        group_ids)


class TestMigration:
    """One run over the seeded database"""

    def test_the_stored_rules_decide_as_the_acls_did(self, database_manager, scratch) -> None:
        """Operators view + edit servers, auditors view routers, the locked Type nobody, the free ones everybody"""
        name, database = scratch

        _run(database_manager, name)

        operators: AccessGrants = _grants(database, (OPERATORS_GROUP_ID,))
        auditors: AccessGrants = _grants(database, (AUDITORS_GROUP_ID,))
        nobody: AccessGrants = _grants(database, ())
        assert operators.allows(ScopeOperation.EDIT, SERVER_TYPE_ID)
        assert not operators.allows(ScopeOperation.DELETE, SERVER_TYPE_ID)
        assert not operators.allows(ScopeOperation.VIEW, ROUTER_TYPE_ID)
        assert auditors.allows(ScopeOperation.VIEW, ROUTER_TYPE_ID)
        assert not _grants(database, (ADMIN_GROUP_ID,)).allows(ScopeOperation.VIEW, LOCKED_TYPE_ID)
        assert nobody.allows(ScopeOperation.DELETE, FREE_TYPE_ID)
        assert nobody.allows(ScopeOperation.DELETE, PLAIN_TYPE_ID)

    def test_the_taken_name_is_skipped_and_ids_follow_the_counter(self, database_manager, scratch) -> None:
        """The view role numbers on; every new role id after the stored one"""
        name, database = scratch

        _run(database_manager, name)

        made = [role for role in _stored(database, ROLES) if role['public_id'] != STORED_ROLE_ID]
        assert TAKEN_NAME not in [role['name'] for role in made]
        assert f'{TAKEN_NAME} #2' in [role['name'] for role in made]
        assert min(role['public_id'] for role in made) == FIRST_ROLE_AFTER_STORED

    def test_the_report_is_complete_and_names_each_type(self, database_manager, scratch) -> None:
        """Status, groups, entries, inactive Types, the documents as stored"""
        name, database = scratch

        _run(database_manager, name)

        report = database[REPORT].find_one({'_id': REPORT_ID}, {'_id': 0})
        entries = {entry['type_id']: entry for entry in report['types']}
        assert (report['status'], report['existing_group_ids'], report['inactive_type_ids']) == (
            'complete', [ADMIN_GROUP_ID, OPERATORS_GROUP_ID, AUDITORS_GROUP_ID], [FREE_TYPE_ID, PLAIN_TYPE_ID])
        assert sorted(entries) == [SERVER_TYPE_ID, ROUTER_TYPE_ID, LOCKED_TYPE_ID]
        assert entries[SERVER_TYPE_ID]['dropped_group_ids'] == [GONE_GROUP_ID]
        assert entries[LOCKED_TYPE_ID]['dropped_group_ids'] == [GONE_GROUP_ID]
        assert report['roles'] == [role for role in _stored(database, ROLES) if role['public_id'] != STORED_ROLE_ID]
        assert report['assignments'] == _stored(database, ASSIGNMENTS)
        assert 'completed_at' in report

    def test_the_stored_acls_are_untouched_and_the_version_bumped(self, database_manager, scratch) -> None:
        """The blocks stay as they were"""
        name, database = scratch

        _run(database_manager, name)

        assert _stored(database, TYPES) == SEEDED_TYPES
        assert database[SETTINGS].find_one({'_id': 'updater'})['version'] == VERSION


class TestRerun:
    """Re-run safety"""

    def test_a_second_run_writes_nothing(self, database_manager, scratch) -> None:
        """Same roles, assignments, report; the counters not drawn again"""
        name, database = scratch
        _run(database_manager, name)
        before = (_stored(database, ROLES), _stored(database, ASSIGNMENTS),
                  database[REPORT].find_one({'_id': REPORT_ID}), list(database[COUNTERS].find()))

        _run(database_manager, name)

        assert (_stored(database, ROLES), _stored(database, ASSIGNMENTS),
                database[REPORT].find_one({'_id': REPORT_ID}), list(database[COUNTERS].find())) == before

    def test_a_run_stopped_after_the_pending_report_finishes_with_its_plan(self, database_manager, scratch) -> None:
        """One role stored, the rest missing: the plan is completed, nothing translated again, no duplicate"""
        name, database = scratch
        _run(database_manager, name)
        report = database[REPORT].find_one({'_id': REPORT_ID})
        planned_roles, planned_assignments = report['roles'], report['assignments']
        database[ROLES].delete_many({'public_id': {'$in': [role['public_id'] for role in planned_roles[1:]]}})
        database[ASSIGNMENTS].delete_many({})
        database[REPORT].update_one({'_id': REPORT_ID}, {'$set': {'status': 'pending'},
                                                         '$unset': {'completed_at': ''}})
        counters = list(database[COUNTERS].find())

        _run(database_manager, name)

        assert [role for role in _stored(database, ROLES) if role['public_id'] != STORED_ROLE_ID] == planned_roles
        assert _stored(database, ASSIGNMENTS) == planned_assignments
        assert database[REPORT].find_one({'_id': REPORT_ID})['status'] == 'complete'
        assert list(database[COUNTERS].find()) == counters


class TestRefusal:
    """The self-check"""

    def test_an_acl_read_otherwise_stops_before_anything_is_written(self, database_manager, scratch) -> None:
        """activated: 1 - the error names the Type; no role, assignment, report or version"""
        name, database = scratch
        database[TYPES].update_one({'public_id': ROUTER_TYPE_ID}, {'$set': {'acl.activated': 1}})

        with pytest.raises(UpdaterException) as caught:
            _run(database_manager, name)

        assert f'[{ROUTER_TYPE_ID}]' in str(caught.value)
        assert [role['public_id'] for role in _stored(database, ROLES)] == [STORED_ROLE_ID]
        assert not _stored(database, ASSIGNMENTS)
        assert database[REPORT].count_documents({}) == 0
        assert database[SETTINGS].find_one({'_id': 'updater'}) is None


def test_a_database_without_groups_keeps_its_types_locked(database_manager, scratch) -> None:
    """A staging database: every activated ACL grants nobody - one role without operations for the administrators"""
    name, database = scratch
    database[GROUPS].delete_many({})

    _run(database_manager, name)

    made = [role for role in _stored(database, ROLES) if role['public_id'] != STORED_ROLE_ID]
    assert [(role['types'], role['operations']) for role in made] == [
        ([SERVER_TYPE_ID, ROUTER_TYPE_ID, LOCKED_TYPE_ID], [])]
    assert [assignment['group_id'] for assignment in _stored(database, ASSIGNMENTS)] == [ADMIN_GROUP_ID]
    assert not _grants(database, (OPERATORS_GROUP_ID,)).allows(ScopeOperation.VIEW, SERVER_TYPE_ID)


def test_a_database_without_an_activated_acl_gets_nothing(database_manager, scratch) -> None:
    """Nothing to translate - only the version moves"""
    name, database = scratch
    database[TYPES].update_many({}, {'$set': {'acl.activated': False}})
    counters = list(database[COUNTERS].find())

    _run(database_manager, name)

    assert [role['public_id'] for role in _stored(database, ROLES)] == [STORED_ROLE_ID]
    assert not _stored(database, ASSIGNMENTS) and database[REPORT].count_documents({}) == 0
    assert list(database[COUNTERS].find()) == counters
    assert database[SETTINGS].find_one({'_id': 'updater'})['version'] == VERSION
