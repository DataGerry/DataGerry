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
Integration tests for the bulk PATCH merge against a real MongoDB

The field subset is merged into each stored object: the document read back keeps every field the subset does not
name - value and type - and gets one version bump and one edit log per target. A failed target leaves every object
key for key as it was stored
"""
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest
from werkzeug.exceptions import NotFound

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_bulk_update_helper import (
    apply_object_updates,
    bulk_patch_payload,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import ObjectWriteContext
# -------------------------------------------------------------------------------------------------------------------- #

# Every test here reaches the database through ManagerProvider, which reads the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

TYPE_ID: int = 9700
OBJECT_IDS: list[int] = [9701, 9702]
MISSING_OBJECT_ID: int = 9709
AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'
BUMPED_VERSION: str = '1.0.1'
KEEP_FIELD: str = 'ip-keep'
CHANGE_FIELD: str = 'ip-change'
KEEP_VALUE_FORMAT: str = 'kept-{public_id}'
OLD_VALUE: str = 'before'
NEW_VALUE: str = 'after'
WHOLE_DOCUMENT_BUT_ID: dict[str, int] = {'_id': 0}

ADMIN: CmdbUser = CmdbUser(public_id=AUTHOR_ID, user_name='admin', active=True, group_id=1)


def _type_document() -> dict[str, Any]:
    """An active type with two text fields"""
    return {
        'public_id': TYPE_ID, 'name': 'bulk-patch-integration', 'label': 'Bulk Patch Integration',
        'author_id': AUTHOR_ID, 'creation_time': datetime.now(timezone.utc), 'active': True, 'version': SEED_VERSION,
        'fields': [{'type': 'text', 'name': KEEP_FIELD, 'label': 'Keep'},
                   {'type': 'text', 'name': CHANGE_FIELD, 'label': 'Change'}],
        'render_meta': {
            'icon': 'fa-cube', 'summary': {'fields': [KEEP_FIELD]},
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [KEEP_FIELD, CHANGE_FIELD]}],
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[dict[str, Any]]:
    """The type and two objects stored; their logs cleared before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
        logs.delete_many({'object_id': {'$in': OBJECT_IDS}})

    _purge()
    types.insert_one(_type_document())
    objects.insert_many([{
        'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': AUTHOR_ID, 'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc), 'multi_data_sections': [],
        'fields': [{'type': 'text', 'name': KEEP_FIELD, 'value': KEEP_VALUE_FORMAT.format(public_id=public_id)},
                   {'type': 'text', 'name': CHANGE_FIELD, 'value': OLD_VALUE}],
    } for public_id in OBJECT_IDS])

    yield {'objects': objects, 'logs': logs}

    _purge()


def _subset() -> dict[str, Any]:
    """The bulk change: one field"""
    return {'fields': [{'name': CHANGE_FIELD, 'value': NEW_VALUE}]}


def test_the_unnamed_field_is_stored_as_it_was(collections: dict[str, Any]) -> None:
    """Value and type of the field the subset does not name; the named one changed; one bump, one log each"""
    apply_object_updates(OBJECT_IDS, bulk_patch_payload(_subset()), None, ObjectWriteContext.for_request(ADMIN))

    for public_id in OBJECT_IDS:
        stored = collections['objects'].find_one({'public_id': public_id}, WHOLE_DOCUMENT_BUT_ID)
        assert stored['fields'] == [
            {'type': 'text', 'name': KEEP_FIELD, 'value': KEEP_VALUE_FORMAT.format(public_id=public_id)},
            {'type': 'text', 'name': CHANGE_FIELD, 'value': NEW_VALUE},
        ]
        assert stored['version'] == BUMPED_VERSION
        assert collections['logs'].count_documents({'object_id': public_id,
                                                     'action_name': LogAction.EDIT.name}) == 1


def test_a_missing_target_leaves_every_object_as_stored(collections: dict[str, Any]) -> None:
    """All or nothing for the merge too"""
    before = {pid: collections['objects'].find_one({'public_id': pid}, WHOLE_DOCUMENT_BUT_ID) for pid in OBJECT_IDS}

    with pytest.raises(NotFound):
        apply_object_updates([OBJECT_IDS[0], MISSING_OBJECT_ID], bulk_patch_payload(_subset()), None,
                             ObjectWriteContext.for_request(ADMIN))

    assert {pid: collections['objects'].find_one({'public_id': pid}, WHOLE_DOCUMENT_BUT_ID)
            for pid in OBJECT_IDS} == before
