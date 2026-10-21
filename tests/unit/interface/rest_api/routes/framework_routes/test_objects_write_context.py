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
Unit tests for cmdb_objects.objects_write_context

The context an object update runs with and the location change it validates are frozen values: they carry
handles, are never reassigned mid-write, and a fresh context starts with its own empty type cache.
`for_request` resolves each manager once, bound to the caller
"""
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, call, patch

import pytest

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import (
    LocationChange,
    ObjectWriteContext,
)
# -------------------------------------------------------------------------------------------------------------------- #

CONTEXT_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context'
LOCATION_PARENT_ID: int = 42


def _context() -> ObjectWriteContext:
    """A context of MagicMock handles."""
    return ObjectWriteContext(MagicMock(), MagicMock(), MagicMock(), MagicMock())


def test_the_context_is_frozen() -> None:
    """A step cannot swap the caller or a manager under the next one"""
    context = _context()

    with pytest.raises(FrozenInstanceError):
        context.request_user = MagicMock()  # type: ignore[misc]


def test_every_context_starts_with_its_own_empty_type_cache() -> None:
    """Two requests never share resolved types"""
    first, second = _context(), _context()

    first.type_cache[1] = MagicMock()

    assert not second.type_cache
    assert first.type_cache is not second.type_cache


def test_for_request_resolves_each_manager_once_for_the_caller() -> None:
    """Objects, types and logs, each bound to the caller"""
    request_user = MagicMock()

    with patch(f'{CONTEXT_PATH}.ManagerProvider.get_manager', side_effect=lambda kind, _user: kind) as get_manager:
        context = ObjectWriteContext.for_request(request_user)

    assert get_manager.call_args_list == [
        call(ManagerType.OBJECTS, request_user),
        call(ManagerType.TYPES, request_user),
        call(ManagerType.LOGS, request_user),
    ]
    assert (context.objects_manager, context.types_manager, context.logs_manager) == (
        ManagerType.OBJECTS, ManagerType.TYPES, ManagerType.LOGS,
    )
    assert context.request_user is request_user
    assert not context.type_cache


def test_a_location_change_is_frozen_and_may_clear_the_parent() -> None:
    """None is a valid parent - the location field was emptied"""
    cleared = LocationChange(None, MagicMock())

    assert cleared.parent is None
    with pytest.raises(FrozenInstanceError):
        cleared.parent = LOCATION_PARENT_ID  # type: ignore[misc]
