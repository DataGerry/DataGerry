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
Unit tests for cmdb.interface.rest_api.routes.rack_routes.rack_access_helper

The object ACL on the Rack routes, function by function: the Rack (READ for a read, READ and UPDATE for a
membership write), the member a write moves, the rack a cross-rack move leaves, and the object a mount-of-object
read names. The shared write rule (``location_helper.object_write_blocker``) is patched where a function only
hands on to it, and run for real where the arguments it gets are the point
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.rack_routes.rack_access_helper import (
    ACCESS_DENIED_STATUS,
    authorize_member_or_abort,
    authorize_move_source_or_abort,
    authorize_object_read_or_abort,
    authorize_rack_or_abort,
    member_access_blocker,
    rack_access_blocker,
)
from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackAccessError
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.interface.rest_api.routes.rack_routes.rack_access_helper'
RACK_ID: int = 61
RACK_TYPE_ID: int = 51
MEMBER_ID: int = 71
MEMBER_TYPE_ID: int = 52
USER: MagicMock = MagicMock(name='request_user')


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app so abort resolves inside a request context."""
    return Flask(__name__)


def _rack() -> dict[str, Any]:
    """A Rack document"""
    return {'public_id': RACK_ID, 'type_id': RACK_TYPE_ID}


def _member() -> dict[str, Any]:
    """A member document"""
    return {'public_id': MEMBER_ID, 'type_id': MEMBER_TYPE_ID}


def _objects_manager(found: dict[int, dict[str, Any]] | None = None) -> MagicMock:
    """Answers the given documents by id and a type for any type id"""
    objects_manager = MagicMock(name='objects_manager')
    objects_manager.get_object.side_effect = lambda public_id: (found or {}).get(public_id)
    objects_manager.get_object_type.return_value = MagicMock(name='object_type')

    return objects_manager


class TestRackAccessBlocker:
    """READ for a read, the write rule with the Rack's own messages for a membership write."""

    def test_a_readable_rack_is_none(self) -> None:
        """READ asked on the rack's type"""
        objects_manager = _objects_manager()

        with patch(f'{MODULE}.verify_access') as read_check:
            assert rack_access_blocker(_rack(), objects_manager, USER, write=False) is None

        read_check.assert_called_once()
        objects_manager.get_object_type.assert_called_once_with(RACK_TYPE_ID)

    def test_an_unreadable_rack_names_itself(self) -> None:
        """The Rack message, not the object one"""
        with patch(f'{MODULE}.verify_access', side_effect=AccessDeniedError('no')):
            assert rack_access_blocker(_rack(), _objects_manager(), USER, write=False) == \
                RackAccessError.RACK_READ_DENIED.format(object_id=RACK_ID)

    def test_a_write_is_the_write_rule_with_the_racks_messages(self) -> None:
        """READ and UPDATE through the shared rule, the Rack named in both messages"""
        objects_manager = _objects_manager()

        with patch(f'{MODULE}.object_write_blocker', return_value='refused') as write_rule:
            assert rack_access_blocker(_rack(), objects_manager, USER, write=True) == 'refused'

        write_rule.assert_called_once_with(
            RACK_ID, RACK_TYPE_ID, objects_manager.get_object_type.return_value, objects_manager, USER,
            RackAccessError.RACK_READ_DENIED.value, RackAccessError.RACK_UPDATE_DENIED.value,
        )

    def test_a_rack_without_a_type_is_left_to_the_type_check(self) -> None:
        """The 400 that follows refuses it as no Rack"""
        objects_manager = _objects_manager()
        objects_manager.get_object_type.return_value = None

        assert rack_access_blocker(_rack(), objects_manager, USER, write=True) is None


class TestAuthorizeRackOrAbort:
    """The aborting wrapper."""

    def test_a_reason_is_a_403(self, flask_app: Flask) -> None:
        """Naming the Rack"""
        with flask_app.test_request_context(), \
             patch(f'{MODULE}.rack_access_blocker', return_value='no rack'), \
             pytest.raises(HTTPException) as raised:
            authorize_rack_or_abort(_rack(), _objects_manager(), USER, write=False)

        assert raised.value.code == ACCESS_DENIED_STATUS == 403
        assert raised.value.description == 'no rack'

    def test_no_reason_passes(self, flask_app: Flask) -> None:
        """Nothing raised"""
        with flask_app.test_request_context(), patch(f'{MODULE}.rack_access_blocker', return_value=None):
            authorize_rack_or_abort(_rack(), _objects_manager(), USER, write=True)


class TestMemberAccessBlocker:
    """The member a write moves gets the placement rule, with the location writes' messages."""

    def test_the_write_rule_on_the_members_type(self) -> None:
        """Its id and stored type id; the default (linked object) messages"""
        objects_manager = _objects_manager()

        with patch(f'{MODULE}.object_write_blocker', return_value=None) as write_rule:
            assert member_access_blocker(_member(), objects_manager, USER) is None

        write_rule.assert_called_once_with(
            MEMBER_ID, MEMBER_TYPE_ID, objects_manager.get_object_type.return_value, objects_manager, USER,
        )

    def test_a_member_without_a_type_is_left_to_the_mount_rules(self) -> None:
        """They refuse it as having no location field"""
        objects_manager = _objects_manager()
        objects_manager.get_object_type.return_value = None

        assert member_access_blocker(_member(), objects_manager, USER) is None


class TestAuthorizeMemberOrAbort:
    """A membership write on an existing mount."""

    def test_an_occupant_names_no_object(self, flask_app: Flask) -> None:
        """Nothing read, nothing judged"""
        objects_manager = _objects_manager()

        with flask_app.test_request_context():
            authorize_member_or_abort(None, objects_manager, USER)

        objects_manager.get_object.assert_not_called()

    def test_a_vanished_member_has_nothing_to_move(self, flask_app: Flask) -> None:
        """The write goes on"""
        with flask_app.test_request_context(), patch(f'{MODULE}.member_access_blocker') as blocker:
            authorize_member_or_abort(MEMBER_ID, _objects_manager(), USER)

        blocker.assert_not_called()

    def test_a_permitted_member_passes(self, flask_app: Flask) -> None:
        """Nothing raised"""
        with flask_app.test_request_context(), patch(f'{MODULE}.member_access_blocker', return_value=None):
            authorize_member_or_abort(MEMBER_ID, _objects_manager({MEMBER_ID: _member()}), USER)

    def test_a_refused_member_is_a_403(self, flask_app: Flask) -> None:
        """With the member's reason"""
        with flask_app.test_request_context(), \
             patch(f'{MODULE}.member_access_blocker', return_value='no member'), \
             pytest.raises(HTTPException) as raised:
            authorize_member_or_abort(MEMBER_ID, _objects_manager({MEMBER_ID: _member()}), USER)

        assert raised.value.code == 403 and raised.value.description == 'no member'


class TestAuthorizeMoveSourceOrAbort:
    """The rack a cross-rack move leaves."""

    def test_no_move_no_check(self, flask_app: Flask) -> None:
        """An object in no rack"""
        with flask_app.test_request_context(), patch(f'{MODULE}.authorize_rack_or_abort') as rack_check:
            authorize_move_source_or_abort(None, _objects_manager(), USER)

        rack_check.assert_not_called()

    def test_the_source_rack_is_judged_as_a_write(self, flask_app: Flask) -> None:
        """READ and UPDATE on the rack the object leaves"""
        objects_manager = _objects_manager({RACK_ID: _rack()})

        with flask_app.test_request_context(), patch(f'{MODULE}.authorize_rack_or_abort') as rack_check:
            authorize_move_source_or_abort({'rack_id': RACK_ID}, objects_manager, USER)

        rack_check.assert_called_once_with(_rack(), objects_manager, USER, write=True)

    def test_a_vanished_source_rack_is_not_judged(self, flask_app: Flask) -> None:
        """Nothing to leave"""
        with flask_app.test_request_context(), patch(f'{MODULE}.authorize_rack_or_abort') as rack_check:
            authorize_move_source_or_abort({'rack_id': RACK_ID}, _objects_manager(), USER)

        rack_check.assert_not_called()


class TestAuthorizeObjectReadOrAbort:
    """The object a mount-of-object read names."""

    def test_an_unreadable_object_is_a_403(self, flask_app: Flask) -> None:
        """Its own message"""
        with flask_app.test_request_context(), \
             patch(f'{MODULE}.verify_access', side_effect=AccessDeniedError('no')), \
             pytest.raises(HTTPException) as raised:
            authorize_object_read_or_abort(MEMBER_ID, _objects_manager({MEMBER_ID: _member()}), USER)

        assert raised.value.code == 403
        assert raised.value.description == RackAccessError.OBJECT_READ_DENIED.format(object_id=MEMBER_ID)

    def test_a_missing_object_passes(self, flask_app: Flask) -> None:
        """It is in no rack - the read answers nothing"""
        with flask_app.test_request_context(), patch(f'{MODULE}.verify_access') as read_check:
            authorize_object_read_or_abort(MEMBER_ID, _objects_manager(), USER)

        read_check.assert_not_called()

    def test_a_readable_object_passes(self, flask_app: Flask) -> None:
        """Nothing raised"""
        with flask_app.test_request_context(), patch(f'{MODULE}.verify_access'):
            authorize_object_read_or_abort(MEMBER_ID, _objects_manager({MEMBER_ID: _member()}), USER)
