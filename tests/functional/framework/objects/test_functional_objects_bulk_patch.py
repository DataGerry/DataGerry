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
Functional tests for the bulk change - ``PATCH /objects/?objectIDs=`` - and the full-object PUT's field rule

The bulk change's subset is merged into each object, so a field it does not name keeps its stored value: an
optional field (the data loss the full-replace PUT caused), a required field (which made the PUT a 400) and the
location field (whose loss left the tree out of step). The body rules - ``objectIDs`` required, only ``fields`` /
``comment`` / ``active``, a change required - and all-or-nothing. And the other half: a PUT that would drop a
field the stored object carries is refused, while a stale field the type no longer declares may go
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from tests.functional.framework.objects.objects_route_helpers import ROOT_LOCATION_ID, ROUTE_URL
# -------------------------------------------------------------------------------------------------------------------- #

BULK_URL: str = f'{ROUTE_URL}/'
TYPE_ID: int = 9680
OBJECT_IDS: list[int] = [9681, 9682]
MISSING_OBJECT_ID: int = 9689
NODE_IDS: dict[int, int] = {9681: 9691, 9682: 9692}
AUTHOR_ID: int = 1
VERSION: str = '1.0.0'

KEEP_FIELD: str = 'bp-keep'
CHANGE_FIELD: str = 'bp-change'
REQUIRED_FIELD: str = 'bp-required'
LOCATION_FIELD: str = 'bp-location'
STALE_FIELD: str = 'bp-stale'
NEW_VALUE: str = 'changed-in-bulk'
OLD_CHANGE_VALUE: str = 'before'
KEEP_VALUE_FORMAT: str = 'kept-{public_id}'
REQUIRED_VALUE_FORMAT: str = 'required-{public_id}'
BULK_COMMENT: str = 'bulk changed'
WHOLE_DOCUMENT_BUT_ID: dict[str, int] = {'_id': 0}


def _type_document() -> dict[str, Any]:
    """Two optional text fields, a required one and a location field, all in the one section"""
    names: list[str] = [KEEP_FIELD, CHANGE_FIELD, REQUIRED_FIELD, LOCATION_FIELD]

    return {
        'public_id': TYPE_ID, 'name': 'bulk-patch-functional', 'label': 'Bulk Patch', 'author_id': AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc), 'active': True, 'version': VERSION,
        'fields': [
            {'type': 'text', 'name': KEEP_FIELD, 'label': 'Keep'},
            {'type': 'text', 'name': CHANGE_FIELD, 'label': 'Change'},
            {'type': 'text', 'name': REQUIRED_FIELD, 'label': 'Required', 'required': True},
            {'type': 'location', 'name': LOCATION_FIELD, 'label': 'Location'},
        ],
        'render_meta': {
            'icon': 'fa-cube', 'summary': {'fields': [KEEP_FIELD]},
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': names}],
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _stored_fields(public_id: int) -> list[dict[str, Any]]:
    """Every field one seeded object stores - placed under the root location"""
    return [
        {'type': 'text', 'name': KEEP_FIELD, 'value': KEEP_VALUE_FORMAT.format(public_id=public_id)},
        {'type': 'text', 'name': CHANGE_FIELD, 'value': OLD_CHANGE_VALUE},
        {'type': 'text', 'name': REQUIRED_FIELD, 'value': REQUIRED_VALUE_FORMAT.format(public_id=public_id)},
        {'type': 'location', 'name': LOCATION_FIELD, 'value': ROOT_LOCATION_ID},
    ]


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[dict[str, Any]]:
    """The type, two objects placed under the root with their nodes; logs of the objects cleared around the test"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
        locations.delete_many({'object_id': {'$in': OBJECT_IDS}})
        logs.delete_many({'object_id': {'$in': OBJECT_IDS}})

    _purge()
    types.insert_one(_type_document())
    for public_id in OBJECT_IDS:
        objects.insert_one({
            'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': AUTHOR_ID, 'version': VERSION,
            'creation_time': datetime.now(timezone.utc), 'multi_data_sections': [], 'fields': _stored_fields(public_id),
        })
        locations.insert_one({
            'public_id': NODE_IDS[public_id], 'name': KEEP_VALUE_FORMAT.format(public_id=public_id),
            'parent': ROOT_LOCATION_ID, 'object_id': public_id, 'type_id': TYPE_ID, 'type_label': 'Bulk Patch',
        })

    yield {'objects': objects, 'locations': locations, 'logs': logs}

    _purge()


def _fields_of(objects: Any, public_id: int) -> dict[str, Any]:
    """The stored fields of one object, by name"""
    stored = objects.find_one({'public_id': public_id}, WHOLE_DOCUMENT_BUT_ID)

    return {field['name']: field['value'] for field in stored['fields']}


def _bulk_patch(rest_api, body: Any, object_ids: list[int] | None = None):
    """PATCH /objects/ with objectIDs as repeated parameters"""
    query: dict[str, Any] = {} if object_ids is None else {'objectIDs': object_ids}

    return rest_api.patch(BULK_URL, json=body, query_string=query)


class TestTheSubsetIsMerged:
    """A field the bulk change does not name keeps its value"""

    def test_the_named_field_changes_and_every_other_field_keeps_its_value(self, rest_api, collections) -> None:
        """B1: the optional field, the required field and the location field are all still there, unchanged"""
        response = _bulk_patch(rest_api, {'fields': [{'name': CHANGE_FIELD, 'value': NEW_VALUE}]}, OBJECT_IDS)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert [entry['public_id'] for entry in response.get_json()['results']] == OBJECT_IDS
        for public_id in OBJECT_IDS:
            expected = {field['name']: field['value'] for field in _stored_fields(public_id)}
            expected[CHANGE_FIELD] = NEW_VALUE
            assert _fields_of(collections['objects'], public_id) == expected

    def test_an_unticked_required_field_is_no_refusal(self, rest_api, collections) -> None:
        """B2: the required field keeps its stored value, so the change goes through"""
        response = _bulk_patch(rest_api, {'fields': [{'name': KEEP_FIELD, 'value': NEW_VALUE}]}, OBJECT_IDS)

        assert response.status_code == HTTPStatus.ACCEPTED
        for public_id in OBJECT_IDS:
            stored = _fields_of(collections['objects'], public_id)
            assert stored[REQUIRED_FIELD] == REQUIRED_VALUE_FORMAT.format(public_id=public_id)

    def test_an_unticked_location_field_leaves_the_tree_alone(self, rest_api, collections) -> None:
        """B3: the location field is kept, and each object's node still hangs under the root"""
        _bulk_patch(rest_api, {'fields': [{'name': CHANGE_FIELD, 'value': NEW_VALUE}]}, OBJECT_IDS)

        for public_id in OBJECT_IDS:
            assert _fields_of(collections['objects'], public_id)[LOCATION_FIELD] == ROOT_LOCATION_ID
            node = collections['locations'].find_one({'object_id': public_id})
            assert (node['public_id'], node['parent']) == (NODE_IDS[public_id], ROOT_LOCATION_ID)

    def test_active_alone_is_a_change(self, rest_api, collections) -> None:
        """Deactivating in bulk, without a field - written, but not versioned"""
        response = _bulk_patch(rest_api, {'active': False}, OBJECT_IDS)

        assert response.status_code == HTTPStatus.ACCEPTED
        for public_id in OBJECT_IDS:
            stored: dict[str, Any] = collections['objects'].find_one({'public_id': public_id})
            assert stored['active'] is False
            assert stored['version'] == VERSION
            assert _fields_of(collections['objects'], public_id)[CHANGE_FIELD] == OLD_CHANGE_VALUE

    def test_the_comment_reaches_each_edit_log(self, rest_api, collections) -> None:
        """One edit log per object, carrying the bulk comment"""
        _bulk_patch(rest_api, {'fields': [{'name': CHANGE_FIELD, 'value': NEW_VALUE}], 'comment': BULK_COMMENT},
                    OBJECT_IDS)

        for public_id in OBJECT_IDS:
            edit_logs = list(collections['logs'].find({'object_id': public_id, 'action_name': LogAction.EDIT.name}))
            assert [log['comment'] for log in edit_logs] == [BULK_COMMENT]


class TestTheBodyRules:
    """What a bulk change must and may carry"""

    def test_without_object_ids_it_is_a_400(self, rest_api, collections) -> None:
        """No path id to fall back on"""
        response = _bulk_patch(rest_api, {'fields': [{'name': CHANGE_FIELD, 'value': NEW_VALUE}]})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'objectIDs' in response.get_json()['message']

    @pytest.mark.parametrize('body', [
        {'fields': [], 'created_mds_rows': [{'section_id': 's', 'data': []}]},
        {'fields': [{'name': CHANGE_FIELD, 'value': NEW_VALUE}], 'location_name': 'x'},
        {'fields': [{'name': CHANGE_FIELD, 'value': NEW_VALUE}], 'public_id': 1},
    ], ids=['mds-rows', 'location-name', 'public-id'])
    def test_a_per_object_or_server_owned_key_is_refused_by_name(self, rest_api, collections, body) -> None:
        """Multi-data rows and the location name belong to one object; ids are the server's"""
        response = _bulk_patch(rest_api, body, OBJECT_IDS)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'cannot be bulk-changed' in response.get_json()['message']

    @pytest.mark.parametrize('body', [{}, {'fields': []}, {'comment': BULK_COMMENT}],
                             ids=['empty', 'no-fields', 'comment-only'])
    def test_a_body_that_changes_nothing_is_refused(self, rest_api, collections, body) -> None:
        """At least one field or the active state"""
        assert _bulk_patch(rest_api, body, OBJECT_IDS).status_code == HTTPStatus.BAD_REQUEST

    def test_a_missing_target_writes_nothing(self, rest_api, collections) -> None:
        """All or nothing, like the bulk PUT: the first object is put back"""
        response = _bulk_patch(rest_api, {'fields': [{'name': CHANGE_FIELD, 'value': NEW_VALUE}]},
                               [OBJECT_IDS[0], MISSING_OBJECT_ID])

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert _fields_of(collections['objects'], OBJECT_IDS[0])[CHANGE_FIELD] == OLD_CHANGE_VALUE
        assert collections['logs'].count_documents({'object_id': {'$in': OBJECT_IDS}}) == 0


class TestThePutKeepsEveryStoredField:
    """Q2: a full-object PUT may not drop a field the object stores"""

    @staticmethod
    def _put_payload(public_id: int, fields: list[dict[str, Any]]) -> dict[str, Any]:
        """A full-object PUT body with the given fields"""
        return {'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': AUTHOR_ID,
                'version': VERSION, 'fields': fields}

    def test_a_put_carrying_only_some_fields_is_refused_naming_them(self, rest_api, collections) -> None:
        """What the old bulk change sent: refused, and nothing is written"""
        public_id = OBJECT_IDS[0]
        response = rest_api.put(
            f'{ROUTE_URL}/{public_id}',
            json=self._put_payload(public_id, [{'name': CHANGE_FIELD, 'value': NEW_VALUE}]),
            query_string={'objectIDs': OBJECT_IDS},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        message: str = response.get_json()['message']
        for dropped in (KEEP_FIELD, REQUIRED_FIELD, LOCATION_FIELD):
            assert dropped in message
        assert 'PATCH' in message
        for target in OBJECT_IDS:
            assert _fields_of(collections['objects'], target)[CHANGE_FIELD] == OLD_CHANGE_VALUE

    def test_a_complete_put_is_accepted(self, rest_api, collections) -> None:
        """Every stored field carried - the full replace it always was"""
        public_id = OBJECT_IDS[0]
        fields = _stored_fields(public_id)
        fields[1] = {'type': 'text', 'name': CHANGE_FIELD, 'value': NEW_VALUE}

        response = rest_api.put(f'{ROUTE_URL}/{public_id}', json=self._put_payload(public_id, fields))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _fields_of(collections['objects'], public_id)[CHANGE_FIELD] == NEW_VALUE

    def test_a_stale_field_the_type_no_longer_declares_may_go(self, rest_api, collections) -> None:
        """Only declared fields count: dropping a stale name is what every update does"""
        public_id = OBJECT_IDS[0]
        collections['objects'].update_one(
            {'public_id': public_id}, {'$push': {'fields': {'type': 'text', 'name': STALE_FIELD, 'value': 'old'}}},
        )

        response = rest_api.put(
            f'{ROUTE_URL}/{public_id}', json=self._put_payload(public_id, _stored_fields(public_id)),
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        assert STALE_FIELD not in _fields_of(collections['objects'], public_id)
