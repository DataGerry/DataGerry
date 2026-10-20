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
Integration tests for the all-or-nothing bulk object update against a real MongoDB

What only a real database shows: the undo puts back the document exactly as it was stored - every key, the version,
the edit time and the editor, read back by ``WriteLedger`` and compared - and a successful bulk update bumps each
target's version once and records one edit log per distinct target
"""
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest
from werkzeug.exceptions import NotFound

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.errors.manager.objects_manager import ObjectsManagerUpdateError
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_bulk_update_helper import (
    apply_object_updates,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import ObjectWriteContext
# -------------------------------------------------------------------------------------------------------------------- #

# Every test here reaches the database through ManagerProvider, which reads the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

TYPE_ID: int = 9660
OBJECT_IDS: list[int] = [9661, 9662, 9663]
MISSING_OBJECT_ID: int = 9669
AUTHOR_ID: int = 1
SEED_EDITOR_ID: int = 2
SEED_VERSION: str = '1.0.0'
BUMPED_VERSION: str = '1.0.1'
NAME_FIELD: str = 'bulk-name'
SEED_VALUE_FORMAT: str = 'seeded-{public_id}'
UPDATED_VALUE: str = 'bulk-updated'
SEED_EDIT_TIME: datetime = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
# The bulk write that fails in the write-failure test
FAILING_WRITE_NUMBER: int = 2
WHOLE_DOCUMENT_BUT_ID: dict[str, int] = {'_id': 0}

ADMIN: CmdbUser = CmdbUser(public_id=AUTHOR_ID, user_name='admin', active=True, group_id=1)


def _type_document() -> dict[str, Any]:
    """An active type with one text field, shown in its one section."""
    return {
        'public_id': TYPE_ID,
        'name': 'bulk-update-integration',
        'label': 'Bulk Update Integration',
        'author_id': AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _object_document(public_id: int) -> dict[str, Any]:
    """A stored object of the type, last edited by someone else at a fixed time."""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': AUTHOR_ID,
        'editor_id': SEED_EDITOR_ID,
        'version': SEED_VERSION,
        'creation_time': SEED_EDIT_TIME,
        'last_edit_time': SEED_EDIT_TIME,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': SEED_VALUE_FORMAT.format(public_id=public_id)}],
        'multi_data_sections': [],
    }


def _payload() -> dict[str, Any]:
    """The one full-object payload applied to every target."""
    return {
        'public_id': OBJECT_IDS[0],
        'type_id': TYPE_ID,
        'active': True,
        'author_id': AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': UPDATED_VALUE}],
    }


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[dict[str, Any]]:
    """The type and the three objects stored; the objects' logs cleared before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
        logs.delete_many({'object_id': {'$in': OBJECT_IDS}})

    _purge()
    types.insert_one(_type_document())
    objects.insert_many([_object_document(public_id) for public_id in OBJECT_IDS])

    yield {'objects': objects, 'logs': logs}

    _purge()


def _stored(objects: Any, public_id: int) -> dict[str, Any]:
    """The raw stored document, `_id` aside."""
    return objects.find_one({'public_id': public_id}, WHOLE_DOCUMENT_BUT_ID)


def test_a_refused_target_leaves_every_document_exactly_as_stored(collections: dict[str, Any]) -> None:
    """The missing middle target's 404: the first target is put back key for key, nothing is logged"""
    objects = collections['objects']
    before: dict[int, dict[str, Any]] = {public_id: _stored(objects, public_id) for public_id in OBJECT_IDS}

    with pytest.raises(NotFound):
        apply_object_updates(
            [OBJECT_IDS[0], MISSING_OBJECT_ID, OBJECT_IDS[1]], _payload(), None, ObjectWriteContext.for_request(ADMIN),
        )

    assert {public_id: _stored(objects, public_id) for public_id in OBJECT_IDS} == before
    assert collections['logs'].count_documents({'object_id': {'$in': OBJECT_IDS}}) == 0


def test_a_failed_later_write_is_undone_key_for_key(
        collections: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The second write fails at the database: the first object is its stored self again"""
    objects = collections['objects']
    before: dict[int, dict[str, Any]] = {public_id: _stored(objects, public_id) for public_id in OBJECT_IDS}
    original_update = ObjectsManager.update_object
    calls: list[int] = []

    def _second_write_fails(self: ObjectsManager, public_id: int, *args: Any, **kwargs: Any) -> None:
        calls.append(public_id)
        if len(calls) == FAILING_WRITE_NUMBER:
            raise ObjectsManagerUpdateError('write lost')
        original_update(self, public_id, *args, **kwargs)

    monkeypatch.setattr(ObjectsManager, 'update_object', _second_write_fails)

    with pytest.raises(ObjectsManagerUpdateError):
        apply_object_updates(OBJECT_IDS, _payload(), None, ObjectWriteContext.for_request(ADMIN))

    assert calls == OBJECT_IDS[:FAILING_WRITE_NUMBER]
    assert {public_id: _stored(objects, public_id) for public_id in OBJECT_IDS} == before


def test_a_successful_bulk_update_bumps_and_logs_each_target_once(collections: dict[str, Any]) -> None:
    """Every target written once: one version bump and one edit log each; an object not named is untouched"""
    objects, logs = collections['objects'], collections['logs']

    results = apply_object_updates(
        [OBJECT_IDS[0], OBJECT_IDS[1]], _payload(), None, ObjectWriteContext.for_request(ADMIN),
    )

    assert [result['public_id'] for result in results] == OBJECT_IDS[:2]
    for public_id in OBJECT_IDS[:2]:
        stored = _stored(objects, public_id)
        assert stored['fields'][0]['value'] == UPDATED_VALUE
        assert stored['version'] == BUMPED_VERSION
        assert logs.count_documents({'object_id': public_id, 'action_name': LogAction.EDIT.name}) == 1
    assert _stored(objects, OBJECT_IDS[2])['fields'][0]['value'] == SEED_VALUE_FORMAT.format(public_id=OBJECT_IDS[2])
