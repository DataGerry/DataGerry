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
Integration tests for the ConfigItem sync against a real MongoDB

Seeds two types with objects and asserts what `handle_sync_config_item_count` reports through a portal stub on a
hosted cloud: the total and the per-type breakdown of one aggregation, read after the writes - a delete of some of
the objects (as a partial bulk delete leaves them) is in the next report. A portal that is not configured costs no
read at all
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework import config_item_sync
from cmdb.framework.config_item_sync import handle_sync_config_item_count
from cmdb.framework.config_item_sync_constants import ConfigItemTypeCountKey
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.errors.security import NoAccessTokenError
# -------------------------------------------------------------------------------------------------------------------- #

SERVER_TYPE_ID: int = 89901
CLIENT_TYPE_ID: int = 89902
SERVER_LABEL: str = 'Sync Server'
CLIENT_LABEL: str = 'Sync Client'
SERVER_IDS: list[int] = [89911, 89912, 89913]
CLIENT_IDS: list[int] = [89921, 89922]
PATH: str = 'cmdb.framework.config_item_sync'


def _type(public_id: int, label: str) -> dict[str, Any]:
    """A field-less stored type."""
    return {'public_id': public_id, 'name': f'sync-{public_id}', 'label': label, 'author_id': 1, 'active': True,
            'creation_time': datetime.now(timezone.utc), 'version': '1.0.0', 'fields': [],
            'render_meta': {'icon': '', 'sections': [], 'summary': {'fields': []}, 'externals': []},
            'acl': {'activated': False, 'groups': {'includes': {}}}}


def _object(public_id: int, type_id: int) -> dict[str, Any]:
    """A stored object of `type_id`."""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': [], 'multi_data_sections': []}


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str):
    """The two types and their objects - removed after; yields the object collection"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def purge() -> None:
        types.delete_many({'public_id': {'$in': [SERVER_TYPE_ID, CLIENT_TYPE_ID]}})
        objects.delete_many({'public_id': {'$in': SERVER_IDS + CLIENT_IDS}})

    purge()
    types.insert_many([_type(SERVER_TYPE_ID, SERVER_LABEL), _type(CLIENT_TYPE_ID, CLIENT_LABEL)])
    objects.insert_many([_object(public_id, SERVER_TYPE_ID) for public_id in SERVER_IDS]
                        + [_object(public_id, CLIENT_TYPE_ID) for public_id in CLIENT_IDS])
    yield objects
    purge()


def _user(database_name: str) -> CmdbUser:
    """A tenant user of the test database."""
    return CmdbUser(public_id=1, user_name='sync', active=True, group_id=ADMIN_GROUP_ID, database=database_name)


def _report(database_name: str) -> tuple[int, dict[str, int]]:
    """Runs the sync on a hosted cloud with a portal stub; the reported total and the seeded types' counts."""
    portal = MagicMock(name='DgServicePortalManager')

    with patch(f'{PATH}.is_hosted_cloud', return_value=True), \
            patch.object(config_item_sync, 'DgServicePortalManager', portal):
        handle_sync_config_item_count(_user(database_name))

    _, total, type_counts = portal.return_value.sync_config_items.call_args.args
    seeded: dict[str, int] = {
        entry[ConfigItemTypeCountKey.NAME.value]: entry[ConfigItemTypeCountKey.COUNT.value]
        for entry in type_counts if entry[ConfigItemTypeCountKey.NAME.value] in (SERVER_LABEL, CLIENT_LABEL)
    }

    return total, seeded


@pytest.mark.usefixtures('rest_api_app_context')
def test_the_report_is_the_stored_count(objects, database_name: str) -> None:
    """The total is every stored object; the breakdown names each seeded type with its count"""
    total, seeded = _report(database_name)

    assert total == objects.count_documents({})
    assert seeded == {SERVER_LABEL: len(SERVER_IDS), CLIENT_LABEL: len(CLIENT_IDS)}


@pytest.mark.usefixtures('rest_api_app_context')
def test_a_partial_delete_is_in_the_next_report(objects, database_name: str) -> None:
    """Two servers gone, as a bulk delete that failed on its third target leaves them: the report has one left"""
    before, _ = _report(database_name)
    objects.delete_many({'public_id': {'$in': SERVER_IDS[:2]}})

    after, seeded = _report(database_name)

    assert after == before - 2
    assert seeded == {SERVER_LABEL: 1, CLIENT_LABEL: len(CLIENT_IDS)}


@pytest.mark.usefixtures('rest_api_app_context')
def test_an_unconfigured_portal_reads_nothing(objects, database_name: str) -> None:
    """The portal is checked first: no aggregation for a sync that cannot be sent"""
    del objects

    with patch(f'{PATH}.is_hosted_cloud', return_value=True), \
            patch.object(config_item_sync, 'DgServicePortalManager', side_effect=NoAccessTokenError('none')), \
            patch.object(config_item_sync, 'build_type_object_counts') as counts:
        handle_sync_config_item_count(_user(database_name))

    counts.assert_not_called()
