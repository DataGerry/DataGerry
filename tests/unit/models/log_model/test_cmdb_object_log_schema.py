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
Unit tests for CmdbObjectLog.SCHEMA - the contract of a stored object change-log entry

Nothing validates an entry at write time (it is written best-effort after the object write), so the
schema is kept honest here: every entry shape the write paths produce must validate against it, and the
shapes they never produce must not. The entries are built by the real chain - `build_object_log_data`,
then `LogsManager.insert_log`, whose stored document is captured instead of written - so a change to the
writer that the schema does not follow fails this module.
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from cerberus import Validator  # type: ignore

from cmdb.framework.rendering.render_result import RenderResult
from cmdb.manager.logs_manager import LogsManager
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE, ObjectLogKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectLogComment
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper import (
    build_object_log_data,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 42
LOG_ID: int = 900
VERSION: str = '1.0.1'
TYPE_ID: int = 7


def _render() -> RenderResult:
    """A RenderResult of the module's object, naming its type"""
    render = RenderResult()
    render.object_information = {'object_id': OBJECT_ID}
    render.type_information = {'type_id': TYPE_ID}

    return render


RENDER: RenderResult = _render()
FIELD_DIFF: dict[str, Any] = {'old': [{'name': 'dg-name', 'value': 'a'}], 'new': [{'name': 'dg-name', 'value': 'b'}]}

#: Display names as `CmdbUser.get_display_name` answers them - first + last name, a plain user name, a cloud e-mail
DISPLAY_NAMES: list[str] = ['John Doe', 'admin', 'john.doe@acme.com']


def _user(display_name: str = DISPLAY_NAMES[0]) -> SimpleNamespace:
    """The two things build_object_log_data reads off the request user"""
    return SimpleNamespace(get_public_id=lambda: 1, get_display_name=lambda: display_name)


def _stored(action: LogAction, comment: str, changes: Any = None, display_name: str = DISPLAY_NAMES[0]) -> dict:
    """Runs the real write chain and answers the document LogsManager.insert_log would store"""
    manager = LogsManager(Mock(name='dbm'))
    captured: list[dict[str, Any]] = []
    manager.get_next_public_id = lambda inc_id=False: LOG_ID
    manager.insert = lambda document: captured.append(document) or LOG_ID

    log_data: dict[str, Any] = build_object_log_data(_user(display_name), OBJECT_ID, VERSION, comment, RENDER, changes)
    manager.insert_log(action=action, log_type=CmdbObjectLog.__name__, **log_data)

    return captured[0]


def _errors(document: dict[str, Any]) -> dict[str, Any]:
    """The schema's complaints about a document; empty when it validates"""
    validator = Validator(CmdbObjectLog.SCHEMA)
    validator.validate(document)

    return validator.errors


# The shapes the write paths store: one per call site of build_object_log_data
WRITTEN_SHAPES: dict[str, tuple[LogAction, str, Any]] = {
    'create': (LogAction.CREATE, ObjectLogComment.CREATED.value, None),
    'edit': (LogAction.EDIT, 'the user\'s edit comment', FIELD_DIFF),
    'activation-change': (LogAction.ACTIVE_CHANGE, ObjectLogComment.ACTIVE_CHANGED.value, {'old': False, 'new': True}),
    'delete': (LogAction.DELETE, ObjectLogComment.DELETED.value, None),
    'import': (LogAction.CREATE, ObjectLogComment.IMPORTED.value, None),
}


class TestWhatTheWriterProduces:
    """Every stored entry validates"""

    @pytest.mark.parametrize('shape', list(WRITTEN_SHAPES), ids=list(WRITTEN_SHAPES))
    def test_a_written_entry_validates(self, shape: str) -> None:
        """Create / edit / activation change / delete / import, each through the real chain"""
        assert _errors(_stored(*WRITTEN_SHAPES[shape])) == {}

    @pytest.mark.parametrize('display_name', DISPLAY_NAMES)
    def test_every_display_name_validates(self, display_name: str) -> None:
        """user_name is the display name - a first + last name and a cloud e-mail included"""
        assert _errors(_stored(*WRITTEN_SHAPES['edit'], display_name=display_name)) == {}

    def test_the_stored_shapes_are_what_the_schema_describes(self) -> None:
        """render_state is bytes, version a string, changes a dict on edit and [] on create"""
        edit: dict[str, Any] = _stored(*WRITTEN_SHAPES['edit'])
        create: dict[str, Any] = _stored(*WRITTEN_SHAPES['create'])

        assert isinstance(edit['render_state'], bytes)
        assert edit['version'] == VERSION
        assert edit['changes'] == FIELD_DIFF
        assert create['changes'] == []
        assert edit['log_type'] == OBJECT_LOG_TYPE

    def test_the_entry_is_stamped_with_the_rendered_type(self) -> None:
        """What the log reads are judged by - the type the render names, on every action"""
        for shape in WRITTEN_SHAPES.values():
            assert _stored(*shape)[ObjectLogKey.TYPE_ID.value] == TYPE_ID

    def test_an_entry_whose_type_is_unknown_validates(self) -> None:
        """The backfill stores null for a snapshot that names no type, and an entry older than the key has none"""
        document: dict[str, Any] = _stored(*WRITTEN_SHAPES['edit'])

        assert _errors({**document, ObjectLogKey.TYPE_ID.value: None}) == {}
        assert _errors({key: value for key, value in document.items() if key != ObjectLogKey.TYPE_ID.value}) == {}

    def test_the_type_reads_back_through_the_model(self) -> None:
        """from_data / to_json carry it, so the list reads answer it"""
        document: dict[str, Any] = _stored(*WRITTEN_SHAPES['edit'])

        assert CmdbObjectLog.to_json(CmdbObjectLog.from_data(document))[ObjectLogKey.TYPE_ID.value] == TYPE_ID

    def test_the_log_type_constant_is_the_model_name(self) -> None:
        """The write paths pass CmdbObjectLog.__name__; the schema allows OBJECT_LOG_TYPE - they are one value"""
        assert CmdbObjectLog.__name__ == OBJECT_LOG_TYPE


class TestWhatItRefuses:
    """The shapes the writer never produces"""

    @pytest.mark.parametrize('key', ['public_id', 'object_id', 'version', 'user_id', 'user_name', 'render_state',
                                     'log_type', 'log_time', 'action', 'action_name'])
    def test_a_field_every_entry_carries_is_required(self, key: str) -> None:
        """The chain always writes these - and none has a default that would fill a missing one in"""
        document: dict[str, Any] = _stored(*WRITTEN_SHAPES['edit'])
        del document[key]

        assert key in _errors(document)

    @pytest.mark.parametrize('key, value', [
        ('action', 9), ('action_name', 'RENAME'), ('log_type', 'CmdbMetaLog'),
        ('render_state', '{"a": 1}'), ('version', 101), ('changes', 'old->new'), ('type_id', '7'),
    ], ids=['unknown-action', 'unknown-action-name', 'other-log-type', 'string-render-state', 'integer-version',
            'text-changes', 'text-type-id'])
    def test_a_value_the_writer_never_stores_is_refused(self, key: str, value: Any) -> None:
        """Each field is held to the type and values the chain produces"""
        assert key in _errors({**_stored(*WRITTEN_SHAPES['edit']), key: value})
