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
The release check of the access switch: an upgraded database answers every access question as it did before

Seeded as a database from before the switch: user groups, users in one or two of them, Types whose stored ACL is on
(one naming a deleted group, one naming only that group - locked for everyone), off or the default, an object of each,
and no scope role or assignment. What each user may do is read first by the type ACL's own frozen rule
(``acl_grants_access``) - the answers before the upgrade. Then the migration ``updater_20261125`` runs, exactly as at
boot, and the REST app - deciding through the access engine only - is asked for each user and Type: the Type by id
(200 / 403), its ``allowed_operations`` and the ``acl`` it answers, the Type listing under READ and under CREATE, the
object by id (200 / 403). Every answer must be the one before. The report must name the Types and the dropped group.
Then ``updater_20261127`` runs, as at boot after it: the group that could set a type ACL (``base.framework.type.edit``)
may view the access rules - its member opens the migration report, which names it under ``rights`` - and no other
group gains a right.

Run on the session database: the version stamp is restored and exactly the migration's documents removed afterwards
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261125 import Update20261125
from cmdb.database.updater.versions.updater_20261127 import Update20261127
from cmdb.framework.access_engine import PERMISSION_OPERATIONS, acl_allows
from cmdb.models.access_model import (
    MIGRATION_REPORT_COLLECTION,
    TYPE_ACL_MIGRATION_REPORT_ID,
    CmdbAccessAssignment,
    CmdbScopeRole,
)
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_constants import TypeRight
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_acl_helper import acl_meaning
# -------------------------------------------------------------------------------------------------------------------- #

SETTINGS: str = 'settings.conf'
UPDATER_ID: str = 'updater'

OPERATORS: int = 97801
AUDITORS: int = 97802
GUESTS: int = 97803
GONE: int = 97809
# Could set a type ACL before the switch; holds no ACL entry
EDITORS: int = 97804
EDITOR_ID: int = 97825
SHARED_TYPE: int = 97811
WRITE_TYPE: int = 97812
LOCKED_TYPE: int = 97813
OFF_TYPE: int = 97814
PLAIN_TYPE: int = 97815
TYPE_IDS: list[int] = [SHARED_TYPE, WRITE_TYPE, LOCKED_TYPE, OFF_TYPE, PLAIN_TYPE]
OBJECT_ID_OFFSET: int = 100
RIGHTS: list[str] = [TypeRight.VIEW.value, ObjectRightName.VIEW.value]
TYPE_EDIT_RIGHT: str = TypeRight.EDIT.value

USERS: dict[int, list[int]] = {
    97821: [OPERATORS],
    97822: [AUDITORS],
    97823: [GUESTS],
    97824: [OPERATORS, AUDITORS],
}


def _acl(includes: dict[int, list[str]], activated: bool = True) -> dict[str, Any]:
    """A stored acl block"""
    return {'activated': activated, 'groups': {'includes': {str(key): value for key, value in includes.items()}}}


STORED_ACLS: dict[int, dict[str, Any] | None] = {
    SHARED_TYPE: _acl({OPERATORS: ['READ', 'UPDATE'], AUDITORS: ['READ']}),
    WRITE_TYPE: _acl({AUDITORS: ['CREATE', 'READ', 'DELETE'], GONE: ['READ']}),
    LOCKED_TYPE: _acl({GONE: ['READ', 'UPDATE']}),
    OFF_TYPE: _acl({OPERATORS: ['READ']}, activated=False),
    PLAIN_TYPE: None,
}


def _type_doc(type_id: int) -> dict[str, Any]:
    """A Type as stored before the switch"""
    document: dict[str, Any] = {
        'public_id': type_id, 'name': f'release-check-{type_id}', 'label': 'T', 'author_id': 1, 'active': True,
        'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
        'fields': [{'type': 'text', 'name': 'host', 'label': 'host'}],
        'render_meta': {'icon': 'fa-cube', 'externals': [], 'summary': {'fields': ['host']},
                        'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['host']}]},
    }

    # updater_20261003 gave every stored Type a complete block - an absent acl is stored as the default
    document['acl'] = STORED_ACLS[type_id] or {'activated': False, 'groups': {'includes': {}}}

    return document


def _user(user_id: int) -> CmdbUser:
    """A seeded user"""
    return CmdbUser(public_id=user_id, user_name=f'release-check-{user_id}', active=True, group_ids=USERS[user_id])


def _before() -> dict[tuple[int, int, AccessControlPermission], bool]:
    """What the stored ACLs answered each user, Type and permission - the oracle"""
    return {(user_id, type_id, permission): acl_allows(_type_doc(type_id), groups, permission)
            for user_id, groups in USERS.items() for type_id in TYPE_IDS for permission in PERMISSION_OPERATIONS}


@pytest.fixture(name='migrated', scope='module')
def fixture_migrated(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[dict[str, Any]]:
    """The old database seeded, the oracle read, the migration run; everything removed and the stamp restored"""
    database = database_manager.connector.client[database_name]
    assert database[CmdbAccessAssignment.COLLECTION].count_documents({}) == 0, 'an access rule left by another test'
    assert database[MIGRATION_REPORT_COLLECTION].count_documents({}) == 0
    stamp: dict[str, Any] | None = database[SETTINGS].find_one({'_id': UPDATER_ID})
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': group_id, 'name': f'release-check-{group_id}', 'label': 'G', 'rights': RIGHTS}
        for group_id in (OPERATORS, AUDITORS, GUESTS)] + [
        {'public_id': EDITORS, 'name': 'release-check-editors', 'label': 'E', 'rights': RIGHTS + [TYPE_EDIT_RIGHT]}])
    database[CmdbUser.COLLECTION].insert_one({'public_id': EDITOR_ID, 'user_name': 'release-check-editor',
                                              'active': True, 'group_ids': [EDITORS],
                                              'registration_time': datetime.now(timezone.utc)})
    database[CmdbUser.COLLECTION].insert_many([
        {'public_id': user_id, 'user_name': f'release-check-{user_id}', 'active': True, 'group_ids': groups,
         'registration_time': datetime.now(timezone.utc)} for user_id, groups in USERS.items()])
    database[CmdbType.COLLECTION].insert_many([_type_doc(type_id) for type_id in TYPE_IDS])
    database[CmdbObject.COLLECTION].insert_many([
        {'public_id': type_id + OBJECT_ID_OFFSET, 'type_id': type_id, 'active': True, 'author_id': 1,
         'version': '1.0.0', 'creation_time': datetime.now(timezone.utc),
         'fields': [{'name': 'host', 'value': 'h', 'type': 'text'}]} for type_id in TYPE_IDS])
    before = _before()

    Update20261125(database_manager, database_name).start_update()
    report: dict[str, Any] = database[MIGRATION_REPORT_COLLECTION].find_one({'_id': TYPE_ACL_MIGRATION_REPORT_ID})
    Update20261127(database_manager, database_name).start_update()

    yield {'before': before, 'report': report}

    database[CmdbScopeRole.COLLECTION].delete_many({'public_id': {'$in': [
        role['public_id'] for role in report['roles']]}})
    database[CmdbAccessAssignment.COLLECTION].delete_many({'public_id': {'$in': [
        assignment['public_id'] for assignment in report['assignments']]}})
    database[MIGRATION_REPORT_COLLECTION].delete_many({})
    database[CmdbObject.COLLECTION].delete_many({'public_id': {'$in': [t + OBJECT_ID_OFFSET for t in TYPE_IDS]}})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': TYPE_IDS}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': {'$in': [*USERS, EDITOR_ID]}})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [OPERATORS, AUDITORS, GUESTS, EDITORS]}})
    if stamp is None:
        database[SETTINGS].delete_one({'_id': UPDATER_ID})
    else:
        database[SETTINGS].replace_one({'_id': UPDATER_ID}, stamp)


def _allowed(before: dict[Any, bool], user_id: int, type_id: int) -> list[str]:
    """The operations the stored ACL allowed, in operation order"""
    return [operation.value for permission, operation in PERMISSION_OPERATIONS.items()
            if before[(user_id, type_id, permission)]]


@pytest.mark.parametrize('user_id', list(USERS))
def test_each_type_by_id_answers_as_before(rest_api, migrated: dict[str, Any], user_id: int) -> None:
    """200 exactly where READ was granted; there the operations and the acl the stored ACL meant"""
    before = migrated['before']

    for type_id in TYPE_IDS:
        response = rest_api.get(f'/types/{type_id}', user=_user(user_id))
        readable: bool = before[(user_id, type_id, AccessControlPermission.READ)]

        assert response.status_code == (HTTPStatus.OK if readable else HTTPStatus.FORBIDDEN), (user_id, type_id)

        if readable:
            result: dict[str, Any] = response.get_json()['result']
            expected_operations = _allowed(before, user_id, type_id)
            assert sorted(result['allowed_operations']) == sorted(expected_operations), (user_id, type_id)
            stored_meaning = acl_meaning(STORED_ACLS[type_id])
            existing_only = (stored_meaning[0], {group: values for group, values in stored_meaning[1].items()
                                                 if group != GONE})
            assert acl_meaning(result['acl']) == existing_only, (user_id, type_id)


@pytest.mark.parametrize('user_id', list(USERS))
@pytest.mark.parametrize('permission', ['READ', 'CREATE'])
def test_the_type_listing_answers_as_before(rest_api, migrated: dict[str, Any], user_id: int,
                                            permission: str) -> None:
    """The Types listed under the permission are the ones it was granted on"""
    response = rest_api.get('/types/', user=_user(user_id), query_string={
        'filter': f'{{"public_id": {{"$in": {TYPE_IDS}}}}}', 'limit': 0, 'acl': permission})
    listed: set[int] = {item['public_id'] for item in response.get_json()['results']}

    assert listed == {type_id for type_id in TYPE_IDS
                      if migrated['before'][(user_id, type_id, AccessControlPermission[permission])]}


@pytest.mark.parametrize('user_id', list(USERS))
def test_each_object_answers_as_before(rest_api, migrated: dict[str, Any], user_id: int) -> None:
    """GET /objects/<id>: 200 exactly where READ on its Type was granted"""
    for type_id in TYPE_IDS:
        response = rest_api.get(f'/objects/{type_id + OBJECT_ID_OFFSET}', user=_user(user_id))
        readable: bool = migrated['before'][(user_id, type_id, AccessControlPermission.READ)]

        assert response.status_code == (HTTPStatus.OK if readable else HTTPStatus.FORBIDDEN), (user_id, type_id)


def test_the_locked_type_stays_locked_for_the_administrator(rest_api, migrated: dict[str, Any]) -> None:
    """Its ACL granted only a deleted group - nobody, administrators included, as before"""
    assert rest_api.get(f'/types/{LOCKED_TYPE}').status_code == HTTPStatus.FORBIDDEN
    assert rest_api.get(f'/types/{PLAIN_TYPE}').status_code == HTTPStatus.OK


def test_the_report_names_the_types_and_the_dropped_group(rest_api, migrated: dict[str, Any]) -> None:
    """Complete; the three activated Types; the deleted group dropped where it was named; the others inactive"""
    report: dict[str, Any] = rest_api.get('/access/migration_report').get_json()['result']
    entries: dict[int, dict[str, Any]] = {entry['type_id']: entry for entry in report['types']}

    assert report['status'] == 'complete'
    assert {SHARED_TYPE, WRITE_TYPE, LOCKED_TYPE} <= set(entries)
    assert (entries[SHARED_TYPE]['dropped_group_ids'], entries[WRITE_TYPE]['dropped_group_ids'],
            entries[LOCKED_TYPE]['dropped_group_ids']) == ([], [GONE], [GONE])
    assert {OFF_TYPE, PLAIN_TYPE} <= set(report['inactive_type_ids'])


def test_the_former_type_acl_editors_may_view_the_access_rules(rest_api, migrated: dict[str, Any],
                                                               database_manager: MongoDatabaseManager,
                                                               database_name: str) -> None:
    """The editors' group gained the view right, no other group anything; its member reads the report's rights"""
    groups = database_manager.connector.client[database_name][CmdbUserGroup.COLLECTION]
    rights: dict[int, list[str]] = {group['public_id']: group['rights'] for group in groups.find(
        {'public_id': {'$in': [OPERATORS, AUDITORS, GUESTS, EDITORS]}})}
    editor = CmdbUser(public_id=EDITOR_ID, user_name='release-check-editor', active=True, group_ids=[EDITORS])

    response = rest_api.get('/access/migration_report', user=editor)

    assert rights == {OPERATORS: RIGHTS, AUDITORS: RIGHTS, GUESTS: RIGHTS,
                      EDITORS: RIGHTS + [TYPE_EDIT_RIGHT, 'base.access.view']}
    assert response.status_code == HTTPStatus.OK
    assert response.get_json()['result']['rights']['groups'] == [{'group_id': EDITORS,
                                                                  'granted': ['base.access.view']}]

