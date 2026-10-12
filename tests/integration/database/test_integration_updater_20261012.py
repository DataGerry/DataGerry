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

Seeds a user in a missing group, an auth section whose LDAP default and mapping name a missing group, a type whose
activated ACL grants only a missing group (locked) and one with a stale entry next to an existing group, runs the
migration, and asserts every one is reported - the locked type as an error - and nothing is written
"""
import logging
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261012 import Update20261012
from cmdb.manager import SettingsManager
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

MISSING_GROUP: int = 98999
EXISTING_GROUP: int = 2
GHOST_USER_ID: int = 98931
LOCKED_TYPE_ID: int = 98941
STALE_TYPE_ID: int = 98942
GHOST_NAME: str = 'report-ghost'
GROUP_DN: str = 'cn=report,dc=example,dc=com'
READ: list[str] = ['READ']
AUTH_ID: str = 'auth'


def _acl(*group_ids: int) -> dict[str, Any]:
    """An activated acl granting READ to each group."""
    return {'activated': True, 'groups': {'includes': {str(group_id): READ for group_id in group_ids}}}


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """The dangling references - all restored after"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    settings = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    stored_auth = settings.find_one({'_id': AUTH_ID})

    def _purge() -> None:
        users.delete_many({'public_id': GHOST_USER_ID})
        types.delete_many({'public_id': {'$in': [LOCKED_TYPE_ID, STALE_TYPE_ID]}})

    _purge()
    users.insert_one({'public_id': GHOST_USER_ID, 'user_name': GHOST_NAME, 'group_id': MISSING_GROUP})
    types.insert_many([{**make_type_doc(LOCKED_TYPE_ID, 'report-locked'), 'acl': _acl(MISSING_GROUP)},
                       {**make_type_doc(STALE_TYPE_ID, 'report-stale'), 'acl': _acl(EXISTING_GROUP, MISSING_GROUP)}])
    settings.replace_one({'_id': AUTH_ID}, {'_id': AUTH_ID, 'providers': [{
        'class_name': 'LdapAuthenticationProvider',
        'config': {'default_group': MISSING_GROUP,
                   'groups': {'mapping': [{'group_dn': GROUP_DN, 'group_id': MISSING_GROUP}]}},
    }]}, upsert=True)
    yield {'users': users, 'types': types, 'settings': settings}
    _purge()
    if stored_auth is None:
        settings.delete_one({'_id': AUTH_ID})
    else:
        settings.replace_one({'_id': AUTH_ID}, stored_auth)


def _snapshot(seeded: dict[str, Any]) -> list[Any]:
    """Everything the run could touch"""
    return [list(seeded['users'].find({'public_id': GHOST_USER_ID}, {'_id': 0})),
            list(seeded['types'].find({'public_id': {'$in': [LOCKED_TYPE_ID, STALE_TYPE_ID]}}, {'_id': 0})),
            seeded['settings'].find_one({'_id': AUTH_ID})]


def test_every_dangling_reference_is_reported(database_manager, database_name,
                                              caplog: pytest.LogCaptureFixture) -> None:
    """The ghost user, the LDAP default and mapping, the stale entry - and the locked type as an error"""
    caplog.set_level(logging.WARNING)

    Update20261012(database_manager, database_name).start_update()

    messages: list[tuple[str, str]] = [(record.levelname, record.getMessage()) for record in caplog.records]
    assert any(GHOST_NAME in message for _, message in messages)
    assert any('default group' in message for _, message in messages)
    assert any(GROUP_DN in message for _, message in messages)
    assert any('report-stale' in message for _, message in messages)
    assert ('ERROR', next(message for _, message in messages if 'report-locked' in message)) in messages


def test_nothing_is_written_and_a_second_run_reports_the_same(seeded, database_manager, database_name,
                                                              caplog: pytest.LogCaptureFixture) -> None:
    """A report only"""
    before = _snapshot(seeded)

    Update20261012(database_manager, database_name).start_update()
    first: list[str] = [record.getMessage() for record in caplog.records]
    caplog.clear()
    Update20261012(database_manager, database_name).start_update()

    assert _snapshot(seeded) == before
    assert [record.getMessage() for record in caplog.records] == first
