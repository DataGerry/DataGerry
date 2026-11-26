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
The release check of the access change history through the real routes

Pinned: every access write records one entry with its diff, comment and the groups it concerns - a create, an update,
a delete with ``?comment=``, a Field Protection update; the cascades of a user group delete and a Type delete record
theirs under their source; the list filters by group and kind (400 for an unknown kind), one entry reads back, a missing
one is a 404; the export answers JSON and CSV with ``base.access.history.export`` and 403 without; the retention sets,
changes and drops the TTL index and records its own change; an entry that cannot be written undoes the change
"""
import csv
import io
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.access_history_manager import AccessHistoryManager
from cmdb.models.access_model import (
    HISTORY_TTL_INDEX_NAME,
    CmdbAccessAssignment,
    CmdbAccessHistory,
    CmdbFieldClass,
    CmdbFieldRule,
    CmdbScopeRole,
)
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.errors.manager.access_history_manager import AccessHistoryManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID, VIEWERS, VIEWER = 96901, 96902, 96911
SERVER, SPARE = 96921, 96922
HISTORY: str = '/access/history'
CLASSES: str = '/access/field_classes'
ROLES: str = '/access/scope_roles'
ASSIGNMENTS: str = '/access/assignments'
COMMENT: str = 'ISO change 42'
SECONDS_PER_DAY: int = 86400
RETENTION_DAYS: int = 30
UNRESTRICT: dict[str, str] = {'unrestrict': 'true'}


def _type(type_id: int) -> dict[str, Any]:
    """A Type with one field"""
    return {'public_id': type_id, 'name': f'history-{type_id}', 'label': 'T', 'author_id': 1, 'active': True,
            'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'global_template_ids': [],
            'fields': [{'type': 'text', 'name': 'host', 'label': 'Host'}],
            'render_meta': {'icon': '', 'externals': [], 'summary': {'fields': ['host']},
                            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['host']}]},
            'acl': {'activated': False, 'groups': {'includes': {}}}}


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Two Types, a group, a viewing group and its user; the access documents and the history removed after"""
    database = database_manager.connector.client[database_name]
    assert database[CmdbAccessAssignment.COLLECTION].count_documents({}) == 0, 'an access rule left by another test'
    database[CmdbAccessHistory.COLLECTION].delete_many({})
    database[CmdbType.COLLECTION].insert_many([_type(SERVER), _type(SPARE)])
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': GROUP_ID, 'name': 'history-group', 'label': 'G', 'rights': []},
        {'public_id': VIEWERS, 'name': 'history-viewers', 'label': 'V', 'rights': ['base.access.view']}])
    database[CmdbUser.COLLECTION].insert_one({'public_id': VIEWER, 'user_name': 'history-viewer', 'active': True,
                                              'group_ids': [VIEWERS],
                                              'registration_time': datetime.now(timezone.utc)})

    yield database

    for model in (CmdbAccessAssignment, CmdbScopeRole, CmdbFieldClass, CmdbFieldRule, CmdbAccessHistory):
        database[model.COLLECTION].delete_many({})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [SERVER, SPARE]}})
    database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [GROUP_ID, VIEWERS]}})
    database[CmdbUser.COLLECTION].delete_many({'public_id': VIEWER})
    database[SettingsManager.COLLECTION].delete_many({'_id': 'access_history'})
    database[CmdbAccessHistory.COLLECTION].drop_indexes()


def _entries(db: Any, **criteria: Any) -> list[dict[str, Any]]:
    """The stored entries matching, oldest first"""
    return list(db[CmdbAccessHistory.COLLECTION].find(criteria, {'_id': 0}).sort('public_id', 1))


def _role(rest_api: Any, types: list[int] | None = None) -> int:
    """POST a view role on the server Type"""
    response = rest_api.post(ROLES, json={'name': 'history-role', 'types': types or [SERVER],
                                          'operations': ['view'], 'write_regular_fields': True,
                                          'field_classes': []})
    assert response.status_code == HTTPStatus.CREATED, response.get_json()

    return response.get_json()['result_id']


def _assign(rest_api: Any, role_id: int) -> int:
    """POST the group's unconditional assignment of the role"""
    response = rest_api.post(ASSIGNMENTS, json={'group_id': GROUP_ID, 'role_id': role_id, 'scope': '*'},
                             query_string=UNRESTRICT)
    assert response.status_code == HTTPStatus.CREATED, response.get_json()

    return response.get_json()['result_id']


class TestRecording:
    """Every access write records its entries"""

    def test_a_create_with_its_comment(self, rest_api, db) -> None:
        """The document after, every key changed, the comment, no group yet; the comment is not stored on it"""
        response = rest_api.post(CLASSES, json={'name': 'history-class', 'label': 'H', 'comment': COMMENT})

        assert response.status_code == HTTPStatus.CREATED, response.get_json()
        class_id: int = response.get_json()['result_id']
        [entry] = _entries(db, kind='field_class')
        assert (entry['action'], entry['document_id'], entry['before'], entry['comment'], entry['group_ids'],
                entry['source'], entry['user_id']) == ('create', class_id, None, COMMENT, [], 'route', 1)
        assert entry['after']['name'] == 'history-class' and 'name' in entry['changed']
        assert 'comment' not in db[CmdbFieldClass.COLLECTION].find_one({'public_id': class_id})

    def test_an_update_concerns_the_groups_holding_the_role(self, rest_api, db) -> None:
        """The role's update names the group of its assignment; the assignment its group"""
        role_id: int = _role(rest_api)
        _assign(rest_api, role_id)
        response = rest_api.put(f'{ROLES}/{role_id}', json={'operations': ['view', 'edit']},
                                query_string=UNRESTRICT)

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        update: dict[str, Any] = _entries(db, kind='scope_role', action='update')[0]
        assert (update['changed'], update['group_ids']) == (['operations'], [GROUP_ID])
        assert _entries(db, kind='assignment')[0]['group_ids'] == [GROUP_ID]

    def test_a_delete_with_a_query_comment(self, rest_api, db) -> None:
        """The document before, none after"""
        assignment_id: int = _assign(rest_api, _role(rest_api))
        response = rest_api.delete(f'{ASSIGNMENTS}/{assignment_id}',
                                   query_string={'comment': COMMENT, **UNRESTRICT})

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        entry: dict[str, Any] = _entries(db, kind='assignment', action='delete')[0]
        assert (entry['before']['public_id'], entry['after'], entry['comment']) == (assignment_id, None, COMMENT)

    def test_a_field_protection_update(self, rest_api, db) -> None:
        """Keyed by source, id and field"""
        response = rest_api.put('/access/field_protection', json={
            'source': 'type', 'source_id': SERVER, 'name': 'host', 'audit_relevant': True})

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        [entry] = _entries(db, kind='field_protection')
        assert (entry['document_id'], entry['changed']) == (f'type:{SERVER}:host', ['audit_relevant'])

    def test_a_group_delete_records_its_assignments(self, rest_api, db) -> None:
        """Under its source"""
        _assign(rest_api, _role(rest_api))
        response = rest_api.delete(f'/groups/{GROUP_ID}', query_string=UNRESTRICT)

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        [entry] = _entries(db, source='group_delete')
        assert (entry['kind'], entry['action'], entry['group_ids']) == ('assignment', 'delete', [GROUP_ID])

    def test_a_type_delete_records_the_roles_it_changes(self, rest_api, db) -> None:
        """The spare Type leaves the role"""
        role_id: int = _role(rest_api, [SERVER, SPARE])
        response = rest_api.delete(f'/types/{SPARE}')

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        [entry] = _entries(db, source='type_delete')
        assert (entry['document_id'], entry['before']['types'], entry['after']['types']) == (
            role_id, [SERVER, SPARE], [SERVER])

    def test_an_entry_that_cannot_be_written_undoes_the_change(self, rest_api, db, monkeypatch) -> None:
        """500, nothing stored"""
        def fail(*_args: Any, **_kwargs: Any) -> list[int]:
            raise AccessHistoryManagerInsertError('history down')

        monkeypatch.setattr(AccessHistoryManager, 'insert_entries', fail)

        assert rest_api.post(CLASSES, json={'name': 'history-lost', 'label': 'L'}).status_code == \
            HTTPStatus.INTERNAL_SERVER_ERROR
        assert db[CmdbFieldClass.COLLECTION].count_documents({'name': 'history-lost'}) == 0


class TestReading:
    """The list, one entry, the export"""

    def test_the_filters(self, rest_api) -> None:
        """By group and by kind, newest first; an unknown kind is a 400"""
        role_id: int = _role(rest_api)
        _assign(rest_api, role_id)

        by_group = rest_api.get(HISTORY, query_string={'group_id': GROUP_ID}).get_json()['results']
        assert [entry['kind'] for entry in by_group] == ['assignment']
        by_kind = rest_api.get(HISTORY, query_string={'kind': 'scope_role'}).get_json()['results']
        assert [entry['document_id'] for entry in by_kind] == [role_id]
        everything = rest_api.get(HISTORY).get_json()['results']
        assert [entry['kind'] for entry in everything] == ['assignment', 'scope_role']
        assert rest_api.get(HISTORY, query_string={'kind': 'nope'}).status_code == HTTPStatus.BAD_REQUEST

    def test_one_entry(self, rest_api, db) -> None:
        """Read back; a missing one is a 404"""
        _role(rest_api)
        public_id: int = _entries(db)[0]['public_id']

        assert rest_api.get(f'{HISTORY}/{public_id}').get_json()['result']['kind'] == 'scope_role'
        assert rest_api.get(f'{HISTORY}/{public_id + 1000}').status_code == HTTPStatus.NOT_FOUND

    def test_the_export(self, rest_api) -> None:
        """JSON and CSV with the export right; 403 for a viewer without it; an unknown format is a 400"""
        _role(rest_api)
        as_json = rest_api.get(f'{HISTORY}/export')
        as_csv = rest_api.get(f'{HISTORY}/export', query_string={'format': 'csv'})

        assert as_json.status_code == HTTPStatus.OK and as_json.get_json()[0]['kind'] == 'scope_role'
        rows = list(csv.DictReader(io.StringIO(as_csv.get_data(as_text=True))))
        assert [row['kind'] for row in rows] == ['scope_role'] and 'attachment' in as_csv.headers['Content-Disposition']
        viewer = {'user': CmdbUser(public_id=VIEWER, user_name='history-viewer', active=True, group_ids=[VIEWERS])}
        assert rest_api.get(f'{HISTORY}/export', **viewer).status_code == HTTPStatus.FORBIDDEN
        assert rest_api.get(HISTORY, **viewer).status_code == HTTPStatus.OK
        assert rest_api.get(f'{HISTORY}/export', query_string={'format': 'xml'}).status_code == \
            HTTPStatus.BAD_REQUEST


class TestRetention:
    """How long entries are kept"""

    def test_the_ttl_index_follows_the_setting(self, rest_api, db) -> None:
        """Set, read, dropped again; each change recorded"""
        assert rest_api.get(f'{HISTORY}/settings').get_json()['result'] == {'retention_days': 0}
        response = rest_api.put(f'{HISTORY}/settings', json={'retention_days': RETENTION_DAYS})

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        index = db[CmdbAccessHistory.COLLECTION].index_information()[HISTORY_TTL_INDEX_NAME]
        assert index['expireAfterSeconds'] == RETENTION_DAYS * SECONDS_PER_DAY
        assert rest_api.get(f'{HISTORY}/settings').get_json()['result'] == {'retention_days': RETENTION_DAYS}

        assert rest_api.put(f'{HISTORY}/settings', json={'retention_days': 0}).status_code == HTTPStatus.ACCEPTED
        assert HISTORY_TTL_INDEX_NAME not in db[CmdbAccessHistory.COLLECTION].index_information()
        assert [entry['after'] for entry in _entries(db, kind='history_settings')] == [
            {'retention_days': RETENTION_DAYS}, {'retention_days': 0}]
