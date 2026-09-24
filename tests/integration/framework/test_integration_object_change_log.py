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
Integration tests for the shared change-log writer against a real MongoDB

`build_object_log_data` + `write_object_log` are what every object write path stores its entry
through. What only a real collection shows: that a real `RenderResult` survives the JSON encoding the
entry is stored with, that the stored entry is a CmdbObjectLog the log reads find by object id, and that
an entry the database refuses answers False instead of raising.
"""
import json
from unittest.mock import MagicMock

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.manager.logs_manager import LogsManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.object_log_constants import ObjectLogKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import OBJECT_LOG_LOST_MARKER
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper import (
    build_object_log_data,
    write_object_log,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 9441
TYPE_ID: int = 9442
VERSION: str = '1.2.3'


@pytest.fixture(name='logs_manager')
def fixture_logs_manager(database_manager: MongoDatabaseManager, database_name: str):
    """A LogsManager on the test database; the module's entries are removed afterwards."""
    yield LogsManager(database_manager)

    database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).delete_many(
        {ObjectLogKey.OBJECT_ID.value: OBJECT_ID},
    )


def _render() -> RenderResult:
    """A real RenderResult of the module's object."""
    render = RenderResult()
    render.object_information = {'object_id': OBJECT_ID, 'version': VERSION, 'active': True}
    render.type_information = {'type_id': TYPE_ID, 'type_label': 'Integration'}
    render.fields = [{'name': 'a', 'value': 'x', 'type': 'text', 'label': 'A'}]
    render.summary_line = 'x'

    return render


def _user() -> MagicMock:
    """The user credited with the change."""
    user = MagicMock()
    user.get_public_id.return_value = 1
    user.get_display_name.return_value = 'admin'

    return user


def test_a_written_entry_is_stored_and_findable(
        logs_manager: LogsManager, database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """The entry lands as a CmdbObjectLog with its version, diff and the encoded render"""
    log_data = build_object_log_data(_user(), OBJECT_ID, VERSION, 'note', _render(), {'old': 'w', 'new': 'x'})

    assert write_object_log(logs_manager, LogAction.EDIT, log_data) is True

    stored = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).find_one(
        {ObjectLogKey.OBJECT_ID.value: OBJECT_ID},
    )
    assert stored['log_type'] == CmdbObjectLog.__name__
    assert stored[ObjectLogKey.VERSION.value] == VERSION
    assert stored[ObjectLogKey.CHANGES.value] == {'old': 'w', 'new': 'x'}


def test_the_stored_render_decodes_to_the_rendered_shape(
        logs_manager: LogsManager, database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """What the log view parses is the render, with its object and type information"""
    write_object_log(logs_manager, LogAction.CREATE, build_object_log_data(_user(), OBJECT_ID, VERSION, 'c', _render()))

    stored = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).find_one(
        {ObjectLogKey.OBJECT_ID.value: OBJECT_ID},
    )
    state = json.loads(stored[ObjectLogKey.RENDER_STATE.value].decode('UTF-8'))

    assert state['object_information']['object_id'] == OBJECT_ID
    assert state['type_information']['type_id'] == TYPE_ID
    assert state['summary_line'] == 'x'


def test_an_entry_the_database_refuses_answers_false(
        logs_manager: LogsManager, database_manager: MongoDatabaseManager, database_name: str,
        caplog: pytest.LogCaptureFixture,
) -> None:
    """Too large for a document: refused, reported under the marker, never raised"""
    log_data = build_object_log_data(_user(), OBJECT_ID, VERSION, 'x' * (17 * 1024 * 1024), _render())

    assert write_object_log(logs_manager, LogAction.EDIT, log_data) is False
    assert f'{OBJECT_LOG_LOST_MARKER} action=EDIT object_id={OBJECT_ID}' in caplog.text
    assert database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name).count_documents(
        {ObjectLogKey.OBJECT_ID.value: OBJECT_ID},
    ) == 0
