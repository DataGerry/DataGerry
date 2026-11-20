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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Functional tests of the sync's keys on the ``/objects`` routes

``system_ref`` and ``sync_hash`` are written by the sync alone: a create body cannot set them, a PUT or PATCH of a
synced object keeps the stored ones whatever the body says, and an object that is not synced gains neither. The
native read shows the link but never the fingerprint
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.object_model import CmdbObject

from tests.functional.framework.objects.objects_route_helpers import (
    NAME_FIELD,
    ORIGINAL_VALUE,
    ROUTE_URL,
    UPDATED_VALUE,
    object_doc,
    object_payload,
)
# -------------------------------------------------------------------------------------------------------------------- #

SYNCED_OBJECT_ID: int = 9471
PLAIN_OBJECT_ID: int = 9472
CREATED_OBJECT_ID: int = 9473
SEEDED_IDS: list[int] = [SYNCED_OBJECT_ID, PLAIN_OBJECT_ID, CREATED_OBJECT_ID]

SYSTEM_REF_KEY: str = 'system_ref'
SYNC_HASH_KEY: str = 'sync_hash'
STORED_SYSTEM_REF: dict[str, Any] = {'kind': 'user', 'id': 9481}
SENT_SYSTEM_REF: dict[str, Any] = {'kind': 'user', 'id': 9482}
STORED_SYNC_HASH: str = 'stored-fingerprint'
SENT_SYNC_HASH: str = 'sent-fingerprint'


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds a synced object (link + fingerprint) and an ordinary one; removes them and their logs afterwards"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.insert_one({**object_doc(SYNCED_OBJECT_ID, ORIGINAL_VALUE),
                        SYSTEM_REF_KEY: STORED_SYSTEM_REF, SYNC_HASH_KEY: STORED_SYNC_HASH})
    objects.insert_one(object_doc(PLAIN_OBJECT_ID, ORIGINAL_VALUE))
    yield objects
    objects.delete_many({'public_id': {'$in': SEEDED_IDS}})
    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
        {'object_id': {'$in': SEEDED_IDS}},
    )


def _stored(objects: Any, public_id: int) -> dict[str, Any]:
    """The stored document"""
    return objects.find_one({'public_id': public_id})


def _sync_keys(document: dict[str, Any]) -> tuple[Any, Any]:
    """The link and the fingerprint a document carries, None for a missing one"""
    return document.get(SYSTEM_REF_KEY), document.get(SYNC_HASH_KEY)


def _changed_fields() -> list[dict[str, Any]]:
    """The one field with a new value"""
    return [{'type': 'text', 'name': NAME_FIELD, 'value': UPDATED_VALUE}]


class TestCreate:
    """A create body cannot link an object."""

    def test_the_sync_keys_of_a_create_body_are_not_stored(self, rest_api, objects: Any) -> None:
        """The validator purges both keys: the object is created as an ordinary one"""
        body = {**object_payload(CREATED_OBJECT_ID, ORIGINAL_VALUE),
                SYSTEM_REF_KEY: SENT_SYSTEM_REF, SYNC_HASH_KEY: SENT_SYNC_HASH}

        response = rest_api.post(f'{ROUTE_URL}/', json=body)

        assert response.status_code == HTTPStatus.OK
        assert SYSTEM_REF_KEY not in _stored(objects, CREATED_OBJECT_ID)
        assert SYNC_HASH_KEY not in _stored(objects, CREATED_OBJECT_ID)

    def test_an_ordinary_create_stores_no_null_link(self, rest_api, objects: Any) -> None:
        """No ``system_ref: null`` on every new object"""
        response = rest_api.post(f'{ROUTE_URL}/', json=object_payload(CREATED_OBJECT_ID, ORIGINAL_VALUE))

        assert response.status_code == HTTPStatus.OK
        assert SYSTEM_REF_KEY not in _stored(objects, CREATED_OBJECT_ID)


class TestUpdate:
    """PUT and PATCH keep the stored sync keys and cannot add any."""

    @pytest.mark.parametrize('extra', [{}, {SYSTEM_REF_KEY: SENT_SYSTEM_REF, SYNC_HASH_KEY: SENT_SYNC_HASH}],
                             ids=['omitted', 'sent'])
    def test_a_put_keeps_the_stored_sync_keys(self, rest_api, objects: Any, extra: dict[str, Any]) -> None:
        """The edit lands; the link and fingerprint are the stored ones"""
        response = rest_api.put(f'{ROUTE_URL}/{SYNCED_OBJECT_ID}', json={'fields': _changed_fields(), **extra})

        assert response.status_code == HTTPStatus.ACCEPTED
        stored = _stored(objects, SYNCED_OBJECT_ID)
        assert stored['fields'][0]['value'] == UPDATED_VALUE
        assert _sync_keys(stored) == (STORED_SYSTEM_REF, STORED_SYNC_HASH)

    def test_a_put_cannot_link_an_ordinary_object(self, rest_api, objects: Any) -> None:
        """A link sent for an ordinary object is not stored"""
        body = {'fields': _changed_fields(), SYSTEM_REF_KEY: SENT_SYSTEM_REF, SYNC_HASH_KEY: SENT_SYNC_HASH}

        response = rest_api.put(f'{ROUTE_URL}/{PLAIN_OBJECT_ID}', json=body)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _sync_keys(_stored(objects, PLAIN_OBJECT_ID)) == (None, None)

    def test_a_patch_keeps_the_stored_sync_keys(self, rest_api, objects: Any) -> None:
        """The subset edit lands; the link and fingerprint stay"""
        response = rest_api.patch(f'{ROUTE_URL}/{SYNCED_OBJECT_ID}',
                                  json={'fields': [{'name': NAME_FIELD, 'value': UPDATED_VALUE}]})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _sync_keys(_stored(objects, SYNCED_OBJECT_ID)) == (STORED_SYSTEM_REF, STORED_SYNC_HASH)

    def test_a_bulk_put_keeps_each_targets_own_link(self, rest_api, objects: Any) -> None:
        """One payload for both: the synced object keeps its link, the ordinary one gains none"""
        response = rest_api.put(f'{ROUTE_URL}/{SYNCED_OBJECT_ID}',
                                json={'fields': _changed_fields(), SYSTEM_REF_KEY: SENT_SYSTEM_REF},
                                query_string={'objectIDs': [SYNCED_OBJECT_ID, PLAIN_OBJECT_ID]})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _sync_keys(_stored(objects, SYNCED_OBJECT_ID)) == (STORED_SYSTEM_REF, STORED_SYNC_HASH)
        assert _sync_keys(_stored(objects, PLAIN_OBJECT_ID)) == (None, None)


class TestRead:
    """The link is shown, the fingerprint is not."""

    def test_the_native_read_shows_the_link_only(self, rest_api, objects: Any) -> None:
        """What a client may know: which record the object mirrors - not the sync's internal fingerprint"""
        response = rest_api.get(f'{ROUTE_URL}/native/{SYNCED_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert _sync_keys(response.get_json()) == (STORED_SYSTEM_REF, None)

    def test_an_ordinary_object_reads_without_a_link(self, rest_api, objects: Any) -> None:
        """No null link in the response either"""
        response = rest_api.get(f'{ROUTE_URL}/native/{PLAIN_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert SYSTEM_REF_KEY not in response.get_json()
