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
Unit tests for the location read scope (location_read_scope)

The denied Types are resolved once with READ; a read naming one node is refused (403) when the node or a node above
it is hidden, and costs nothing when nothing is denied, for the root, and for a node without an id
"""
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations import location_read_scope
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    LOCATION_NOT_READABLE_MSG,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_read_scope import (
    abort_unless_location_readable,
    read_denied_type_ids,
)
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

NODE_ID: int = 40
DENIED_TYPE: int = 7
OTHER_TYPE: int = 8


def _manager(*chain_types: int) -> MagicMock:
    """A stub LocationsManager whose chain read answers nodes of the given types."""
    manager = MagicMock()
    manager.get_location_chain.return_value = [{'public_id': index, 'type_id': type_id}
                                               for index, type_id in enumerate(chain_types)]
    return manager


def test_the_denied_types_are_read_with_read() -> None:
    """One resolution per request"""
    user = MagicMock()

    with patch.object(location_read_scope, 'resolve_denied_type_ids', return_value=[DENIED_TYPE]) as resolve:
        assert read_denied_type_ids(user) == [DENIED_TYPE]

    resolve.assert_called_once_with(user, AccessControlPermission.READ)


def test_a_hidden_chain_is_a_403() -> None:
    """An ancestor of a denied type"""
    manager = _manager(OTHER_TYPE, DENIED_TYPE, 0)

    with pytest.raises(HTTPException) as exc_info:
        abort_unless_location_readable(manager, NODE_ID, [DENIED_TYPE])

    assert exc_info.value.code == 403
    assert exc_info.value.description == LOCATION_NOT_READABLE_MSG.format(public_id=NODE_ID)
    manager.get_location_chain.assert_called_once_with(NODE_ID)


def test_a_readable_chain_passes() -> None:
    """Nothing denied on it"""
    abort_unless_location_readable(_manager(OTHER_TYPE, 0), NODE_ID, [DENIED_TYPE])


def test_a_missing_node_passes() -> None:
    """The route answers that case as it always did"""
    abort_unless_location_readable(_manager(), NODE_ID, [DENIED_TYPE])


@pytest.mark.parametrize('public_id, denied', [
    (NODE_ID, []), (RootLocationDefault.PUBLIC_ID, [DENIED_TYPE]), (None, [DENIED_TYPE]),
], ids=['nothing-denied', 'root', 'no-id'])
def test_reads_nothing_when_nothing_can_be_hidden(public_id: int | None, denied: list[int]) -> None:
    """The admin's read costs no chain"""
    manager = _manager(DENIED_TYPE)

    abort_unless_location_readable(manager, public_id, denied)

    manager.get_location_chain.assert_not_called()
