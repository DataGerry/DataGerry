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
A rendered object says what its render could not build

A render degrades rather than failing: a piece it cannot build is left out and the object is still
answered. What is pinned here is that the client can tell - ``render_problems`` on the rendered object
names each loss - on the single read, on the listing, and in the change-log entry, which stores the
render as it was answered. The broken shapes are written straight into the collections: the write routes
refuse them today, but a database can still hold them
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.rendering.render_constants import RenderProblemCode, RenderProblemKey
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.object_log_constants import ObjectLogKey
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType

from tests.functional.framework.objects.objects_route_helpers import (
    NAME_FIELD,
    ORIGINAL_VALUE,
    ROUTE_URL,
    TYPE_ID,
    insert_object_doc,
    object_doc,
    type_doc,
)
# -------------------------------------------------------------------------------------------------------------------- #

GHOST_TYPE_ID: int = 9451
GHOST_TYPE_NAME: str = 'render-problems-ghost-type'
GHOST_FIELD: str = 'declared-by-no-type'
DROPPED_FIELD: str = 'dropped-from-the-type'
SECTION_NAME: str = 'main'

GHOST_OBJECT_ID: int = 9461
CLEAN_OBJECT_ID: int = 9462
DROPPED_OBJECT_ID: int = 9463

FIELD_NOT_ON_TYPE_PROBLEM: dict[str, Any] = {
    RenderProblemKey.CODE.value: RenderProblemCode.FIELD_NOT_ON_TYPE.value,
    RenderProblemKey.SECTION.value: SECTION_NAME,
    RenderProblemKey.FIELD.value: GHOST_FIELD,
    RenderProblemKey.EXTERNAL_LINK.value: None,
}


def _ghost_type_doc() -> dict[str, Any]:
    """The package's type, but with a section listing a field no type declares."""
    doc: dict[str, Any] = type_doc()
    doc['public_id'] = GHOST_TYPE_ID
    doc['name'] = GHOST_TYPE_NAME
    doc['render_meta']['sections'][0]['fields'] = [NAME_FIELD, GHOST_FIELD]

    return doc


def _object_doc_of(public_id: int, type_id: int, extra_fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A stored object of `type_id` carrying the name field plus `extra_fields`."""
    doc: dict[str, Any] = object_doc(public_id, ORIGINAL_VALUE)
    doc['type_id'] = type_id
    doc['fields'].extend(extra_fields or [])

    return doc


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the broken type and the three objects; removes them and their log entries after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    object_ids: list[int] = [GHOST_OBJECT_ID, CLEAN_OBJECT_ID, DROPPED_OBJECT_ID]

    def _purge() -> None:
        types.delete_one({'public_id': GHOST_TYPE_ID})
        objects.delete_many({'public_id': {'$in': object_ids}})
        logs.delete_many({ObjectLogKey.OBJECT_ID.value: {'$in': object_ids}})

    _purge()
    types.insert_one(_ghost_type_doc())
    objects.insert_one(_object_doc_of(GHOST_OBJECT_ID, GHOST_TYPE_ID))
    insert_object_doc(database_manager, database_name, CLEAN_OBJECT_ID, ORIGINAL_VALUE)
    objects.insert_one(_object_doc_of(DROPPED_OBJECT_ID, TYPE_ID, [{'name': DROPPED_FIELD, 'value': CLEAN_OBJECT_ID}]))
    yield
    _purge()


class TestTheSingleRead:
    """GET /objects/<id>"""

    def test_a_degraded_render_names_what_it_lost(self, rest_api) -> None:
        """The undeclared field is left out, and the response says so"""
        response = rest_api.get(f'{ROUTE_URL}/{GHOST_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        body: dict[str, Any] = response.get_json()
        assert [field['name'] for field in body['fields']] == [NAME_FIELD]
        assert body['render_problems'] == [FIELD_NOT_ON_TYPE_PROBLEM]

    def test_a_complete_render_answers_an_empty_list(self, rest_api) -> None:
        """The key is always there; empty means complete"""
        response = rest_api.get(f'{ROUTE_URL}/{CLEAN_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['render_problems'] == []

    def test_a_legacy_field_its_type_dropped_does_not_fail_the_read(self, rest_api) -> None:
        """
        An untyped stored row naming a dropped field is skipped, not fatal

        Resolving its kind from the type raised in the renderer's constructor, which turned the whole
        read into a 500 for an object whose visible data is intact
        """
        response = rest_api.get(f'{ROUTE_URL}/{DROPPED_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['render_problems'] == []


class TestTheListing:
    """GET /objects/ - each row carries its own problems."""

    def test_each_row_carries_its_own_problems(self, rest_api) -> None:
        """The degraded row names its loss; the complete row beside it has none"""
        seeded: list[int] = [GHOST_OBJECT_ID, CLEAN_OBJECT_ID]
        response = rest_api.get(f'{ROUTE_URL}/?view=render&limit=0&filter={{"public_id":{{"$in":{seeded}}}}}')

        assert response.status_code == HTTPStatus.OK
        rows: dict[int, dict[str, Any]] = {
            row['object_information']['object_id']: row for row in response.get_json()['results']
        }
        assert rows[GHOST_OBJECT_ID]['render_problems'] == [FIELD_NOT_ON_TYPE_PROBLEM]
        assert rows[CLEAN_OBJECT_ID]['render_problems'] == []


class TestTheChangeLog:
    """A write's log entry stores the render - and with it, what the render lost."""

    def test_the_log_entry_marks_a_degraded_render(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        A degraded render is stored as degraded, not as if the object had no such field

        The log view draws the stored render; without the marker, a temporary loss would read as the
        object's state at that time
        """
        response = rest_api.put(f'{ROUTE_URL}/state/{GHOST_OBJECT_ID}', json=False)
        assert response.status_code == HTTPStatus.ACCEPTED

        logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
        entry: dict[str, Any] | None = logs.find_one(
            {ObjectLogKey.OBJECT_ID.value: GHOST_OBJECT_ID, 'action': LogAction.ACTIVE_CHANGE.value},
        )

        assert entry is not None
        raw: Any = entry[ObjectLogKey.RENDER_STATE.value]
        state: dict[str, Any] = json.loads(raw.decode('UTF-8') if isinstance(raw, bytes) else raw)
        assert state['render_problems'] == [FIELD_NOT_ON_TYPE_PROBLEM]
