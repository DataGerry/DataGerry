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
The change-log entry each object write leaves behind

Every action - create, edit through PUT and PATCH, the activation toggle, delete - writes one
CmdbObjectLog, and every entry stores the object **as rendered** in ``render_state``: the log view draws
that value with the object renderer, so an entry holding the stored document instead (no type, section
or summary information) renders empty. What is pinned here is the stored entry itself, read straight
from the collection after the real route ran.
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.logs_manager import LogsManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import OBJECT_LOG_LOST_MARKER
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.object_log_constants import ObjectLogKey

from tests.functional.framework.objects.objects_route_helpers import (
    NAME_FIELD,
    ORIGINAL_VALUE,
    ROUTE_URL,
    TYPE_ID,
    UPDATED_VALUE,
    UPDATE_VERSION,
    drop_object,
    insert_object_doc,
    object_payload,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 9431

# The keys only a render carries - the stored document has none of them
RENDERED_KEYS: set[str] = {'object_information', 'type_information', 'sections', 'summary_line'}


@pytest.fixture(name='logs')
def fixture_logs(database_manager: MongoDatabaseManager, database_name: str):
    """The change-log collection, cleared of this module's object before and after the test."""
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    logs.delete_many({ObjectLogKey.OBJECT_ID.value: OBJECT_ID})

    yield logs

    logs.delete_many({ObjectLogKey.OBJECT_ID.value: OBJECT_ID})
    drop_object(database_manager, database_name, OBJECT_ID)


def _entry(logs, action: LogAction) -> dict[str, Any]:
    """The newest entry of one action for the module's object."""
    entries = list(logs.find({ObjectLogKey.OBJECT_ID.value: OBJECT_ID, 'action': action.value}).sort('public_id', -1))

    assert entries, f'no {action.name} log entry was written'

    return entries[0]


def _render_state(entry: dict[str, Any]) -> dict[str, Any]:
    """The entry's render_state, decoded the way the log view decodes it."""
    raw: Any = entry[ObjectLogKey.RENDER_STATE.value]

    return json.loads(raw.decode('UTF-8') if isinstance(raw, bytes) else raw)


def _assert_rendered(entry: dict[str, Any]) -> None:
    """The entry's render_state is a render of the module's object."""
    state: dict[str, Any] = _render_state(entry)

    assert RENDERED_KEYS <= set(state)
    assert state['object_information']['object_id'] == OBJECT_ID
    assert state['type_information']['type_id'] == TYPE_ID


class TestEveryActionStoresTheRenderedObject:
    """One entry per write, each drawable by the log view."""

    def test_create(self, rest_api, logs) -> None:
        """POST /objects/"""
        response = rest_api.post(f'{ROUTE_URL}/', json=object_payload(OBJECT_ID, ORIGINAL_VALUE))
        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        _assert_rendered(_entry(logs, LogAction.CREATE))

    def test_edit_through_put(self, rest_api, logs, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """PUT /objects/<id> - the entry carries the diff, the bumped version and the render"""
        insert_object_doc(database_manager, database_name, OBJECT_ID, ORIGINAL_VALUE)
        payload = object_payload(OBJECT_ID, UPDATED_VALUE)
        payload['version'] = UPDATE_VERSION

        assert rest_api.put(f'{ROUTE_URL}/{OBJECT_ID}', json=payload).status_code == HTTPStatus.ACCEPTED

        entry = _entry(logs, LogAction.EDIT)
        _assert_rendered(entry)
        assert entry[ObjectLogKey.CHANGES.value]
        rendered_value = next(
            field['value'] for field in _render_state(entry)['fields'] if field['name'] == NAME_FIELD
        )
        assert rendered_value == UPDATED_VALUE

    def test_edit_through_patch(
        self, rest_api, logs, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """PATCH /objects/<id> takes the same path"""
        insert_object_doc(database_manager, database_name, OBJECT_ID, ORIGINAL_VALUE)

        response = rest_api.patch(
            f'{ROUTE_URL}/{OBJECT_ID}', json={'fields': [{'name': NAME_FIELD, 'value': UPDATED_VALUE}]},
        )
        assert response.status_code == HTTPStatus.ACCEPTED

        _assert_rendered(_entry(logs, LogAction.EDIT))

    def test_activation_toggle(
        self, rest_api, logs, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """PUT /objects/state/<id>"""
        insert_object_doc(database_manager, database_name, OBJECT_ID, ORIGINAL_VALUE)

        assert rest_api.put(f'{ROUTE_URL}/state/{OBJECT_ID}', json=False).status_code == HTTPStatus.ACCEPTED

        entry = _entry(logs, LogAction.ACTIVE_CHANGE)
        _assert_rendered(entry)
        assert entry[ObjectLogKey.CHANGES.value] == {'old': True, 'new': False}

    def test_delete(self, rest_api, logs, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """DELETE /objects/<id>"""
        insert_object_doc(database_manager, database_name, OBJECT_ID, ORIGINAL_VALUE)

        assert rest_api.delete(f'{ROUTE_URL}/{OBJECT_ID}').status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        _assert_rendered(_entry(logs, LogAction.DELETE))


def test_a_failing_log_write_does_not_fail_the_edit(
        rest_api, logs, database_manager: MongoDatabaseManager, database_name: str,
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """The edit is stored and answered as usual; the lost entry is reported under the marker"""
    def _failing_insert(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError('logs collection down')

    insert_object_doc(database_manager, database_name, OBJECT_ID, ORIGINAL_VALUE)
    monkeypatch.setattr(LogsManager, 'insert_log', _failing_insert)
    payload = object_payload(OBJECT_ID, UPDATED_VALUE)
    payload['version'] = UPDATE_VERSION

    assert rest_api.put(f'{ROUTE_URL}/{OBJECT_ID}', json=payload).status_code == HTTPStatus.ACCEPTED
    assert not list(logs.find({ObjectLogKey.OBJECT_ID.value: OBJECT_ID}))
    assert f'{OBJECT_LOG_LOST_MARKER} action=EDIT object_id={OBJECT_ID}' in caplog.text
