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
Unit tests for the delete guard of cmdb.interface.rest_api.routes.port_routes.port_object_hooks

The cascade half of the module (what a deleted object's ports take with them) is covered by
tests/unit/framework/port/test_cascade.py; this module covers the half that runs BEFORE anything is
deleted: the refusal of a Cable CI a CmdbPortConnection still uses.

What is pinned here: a selection is filtered to CABLE-typed targets first, so an ordinary delete never
reaches the connection lookup (and needs no PortConnections manager at all), an installation without a
cable type asks nothing, a target without an int public_id is not looked up, and a blocked cable
aborts with 400 carrying the blocker message verbatim.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.port_routes.port_object_hooks import (
    cable_object_ids,
    guard_cable_objects_delete,
)
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #

HOOK_PATH: str = 'cmdb.interface.rest_api.routes.port_routes.port_object_hooks'

CABLE_TYPE_ID: int = 11
PLAIN_TYPE_ID: int = 12
CABLE_CI_ID: int = 501
OTHER_CABLE_CI_ID: int = 502
PLAIN_OBJECT_ID: int = 503
BLOCKER: str = 'Deletion refused - resolve the Port connection(s) first'


def _object(public_id: Any, type_id: Any = CABLE_TYPE_ID) -> dict[str, Any]:
    """A CmdbObject document as the delete routes read it."""
    return {CmdbObjectKey.PUBLIC_ID.value: public_id, CmdbObjectKey.TYPE_ID.value: type_id}


def _types_manager(*cable_type_ids: int) -> MagicMock:
    """A TypesManager answering which CmdbTypes carry the CABLE marker."""
    manager = MagicMock()
    manager.get_type_ids_of_special_type.return_value = list(cable_type_ids)

    return manager


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 cable_object_ids                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_only_the_cable_typed_targets_are_returned() -> None:
    """The connection lookup asks about Cable CIs; every other target is irrelevant to it"""
    types_manager = _types_manager(CABLE_TYPE_ID)

    assert cable_object_ids(
        types_manager, [_object(CABLE_CI_ID), _object(PLAIN_OBJECT_ID, PLAIN_TYPE_ID)],
    ) == [CABLE_CI_ID]
    types_manager.get_type_ids_of_special_type.assert_called_once_with(SpecialType.CABLE)


def test_an_empty_selection_asks_nothing() -> None:
    """Not even the cheap type read is worth paying for an empty list"""
    types_manager = _types_manager(CABLE_TYPE_ID)

    assert cable_object_ids(types_manager, []) == []
    types_manager.get_type_ids_of_special_type.assert_not_called()


def test_an_installation_without_a_cable_type_has_no_cables() -> None:
    """No type carries the marker, so no object can be a Cable CI"""
    assert cable_object_ids(_types_manager(), [_object(CABLE_CI_ID)]) == []


@pytest.mark.parametrize('public_id', [None, 'not-an-int'], ids=['none', 'string'])
def test_a_target_without_a_usable_public_id_is_not_looked_up(public_id: Any) -> None:
    """A document that cannot be referenced by a connection cannot be blocking one"""
    assert cable_object_ids(_types_manager(CABLE_TYPE_ID), [_object(public_id)]) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                            guard_cable_objects_delete                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_selection_without_a_cable_needs_no_connection_manager() -> None:
    """
    Every object deletion runs this guard

    A selection with no Cable CI in it must not cost a manager, let alone a read - the same reason the
    cascade hook resolves nothing for a malformed document.
    """
    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager') as get_manager, \
         patch(f'{HOOK_PATH}.collect_cable_usage') as collect:
        guard_cable_objects_delete(
            MagicMock(), _types_manager(CABLE_TYPE_ID), [_object(PLAIN_OBJECT_ID, PLAIN_TYPE_ID)],
        )

    get_manager.assert_not_called()
    collect.assert_not_called()


def test_a_free_cable_passes_the_guard() -> None:
    """Nothing in use means the deletion is allowed to proceed"""
    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         patch(f'{HOOK_PATH}.collect_cable_usage', return_value=[]):
        guard_cable_objects_delete(MagicMock(), _types_manager(CABLE_TYPE_ID), [_object(CABLE_CI_ID)])


def test_a_used_cable_aborts_with_400_and_the_blocker_message() -> None:
    """A business-rule refusal is a 400 here, and the message is what the user acts on"""
    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         patch(f'{HOOK_PATH}.collect_cable_usage', return_value=[MagicMock()]), \
         patch(f'{HOOK_PATH}.cable_usage_blocker', return_value=BLOCKER):
        with pytest.raises(HTTPException) as exc_info:
            guard_cable_objects_delete(MagicMock(), _types_manager(CABLE_TYPE_ID), [_object(CABLE_CI_ID)])

    assert exc_info.value.code == 400
    assert BLOCKER in exc_info.value.description


def test_the_whole_selections_cables_are_checked_together() -> None:
    """One read for every cable in the selection is what makes the bulk delete affordable"""
    connections_manager = MagicMock()

    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager', return_value=connections_manager) as get_manager, \
         patch(f'{HOOK_PATH}.collect_cable_usage', return_value=[]) as collect:
        guard_cable_objects_delete(
            MagicMock(),
            _types_manager(CABLE_TYPE_ID),
            [_object(CABLE_CI_ID), _object(PLAIN_OBJECT_ID, PLAIN_TYPE_ID), _object(OTHER_CABLE_CI_ID)],
        )

    collect.assert_called_once_with(connections_manager, [CABLE_CI_ID, OTHER_CABLE_CI_ID])
    assert get_manager.call_args.args[0] == ManagerType.PORT_CONNECTIONS
