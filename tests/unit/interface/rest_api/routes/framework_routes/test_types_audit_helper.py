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
Unit tests for the audit keys of a CmdbType write: the create stamps all four, the update keeps the stored author
and creation time and stamps the editor
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_audit_helper import (
    stamp_type_create_audit,
    stamp_type_update_audit,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import TYPE_AUDIT_KEYS
# -------------------------------------------------------------------------------------------------------------------- #

CALLER_ID: int = 7
STORED_AUTHOR_ID: int = 3
STORED_CREATION_TIME: datetime = datetime(2020, 5, 4, tzinfo=timezone.utc)
FORGED_ID: int = 99
FORGED_TIME: datetime = datetime(2001, 1, 1, tzinfo=timezone.utc)
CALLER = SimpleNamespace(public_id=CALLER_ID)
STORED_TYPE = SimpleNamespace(author_id=STORED_AUTHOR_ID, creation_time=STORED_CREATION_TIME)


def _forged() -> dict[str, Any]:
    """A payload carrying every audit key with a value of the client's - what the schema now drops"""
    return {'author_id': FORGED_ID, 'creation_time': FORGED_TIME, 'last_edit_time': FORGED_TIME,
            'editor_id': FORGED_ID, 'name': 'kept'}


class TestTheAuditKeys:
    """The set the request schema drops"""

    def test_the_four_keys(self) -> None:
        """Author, creation, last edit, editor - nothing else"""
        assert set(TYPE_AUDIT_KEYS) == {'author_id', 'creation_time', 'last_edit_time', 'editor_id'}


class TestStampTypeCreateAudit:
    """A new Type: the caller and now, never edited"""

    def test_every_key_is_the_servers(self) -> None:
        """Even were a value to reach it, none survives"""
        data: dict[str, Any] = _forged()
        before: datetime = datetime.now(timezone.utc)

        stamp_type_create_audit(data, CALLER)

        assert data['author_id'] == CALLER_ID
        assert before <= data['creation_time'] <= datetime.now(timezone.utc)
        assert (data['last_edit_time'], data['editor_id']) == (None, None)

    def test_the_rest_of_the_payload_is_untouched(self) -> None:
        """Only the four keys are written"""
        data: dict[str, Any] = _forged()

        stamp_type_create_audit(data, CALLER)

        assert data['name'] == 'kept'
        assert set(data) == {*TYPE_AUDIT_KEYS, 'name'}


class TestStampTypeUpdateAudit:
    """An updated Type: its history kept, the caller the editor"""

    def test_the_stored_author_and_creation_time_are_kept(self) -> None:
        """Before: the body's author_id and creation_time were stored, rewriting who made the Type and when"""
        data: dict[str, Any] = _forged()

        stamp_type_update_audit(data, STORED_TYPE, CALLER)

        assert (data['author_id'], data['creation_time']) == (STORED_AUTHOR_ID, STORED_CREATION_TIME)

    def test_the_caller_is_the_editor_now(self) -> None:
        """The edit half is the request's"""
        data: dict[str, Any] = _forged()
        before: datetime = datetime.now(timezone.utc)

        stamp_type_update_audit(data, STORED_TYPE, CALLER)

        assert data['editor_id'] == CALLER_ID
        assert before <= data['last_edit_time'] <= datetime.now(timezone.utc)

    def test_a_payload_without_them_gets_them(self) -> None:
        """The request schema drops them, so the update starts without any"""
        data: dict[str, Any] = {'name': 'kept'}

        stamp_type_update_audit(data, STORED_TYPE, CALLER)

        assert set(data) == {*TYPE_AUDIT_KEYS, 'name'}
