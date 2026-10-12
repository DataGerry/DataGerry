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
Unit tests for the port clone half of cmdb.interface.rest_api.routes.port_routes.port_object_hooks

The source parameter is a positive integer or absent. The plan refuses in order - an unreadable or missing
source, then (only for a source with ports) the licence, the right, the port count and the new object's Type -
and reads the source's ports and INTERNAL pairs. The cloud API key, closed to the port routes, is refused
before the licence. The write records the object before its ports
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.port_routes.port_object_hooks import (
    insert_object_with_cloned_ports,
    plan_object_port_clone,
    read_port_clone_source,
)
from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PortCloneError, PortRight
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectQueryParam
from cmdb.framework.port.clone import PortClonePlan
from cmdb.framework.port.name_syntax_constants import MAX_BULK_PORT_COUNT
from cmdb.framework.write_ledger_constants import WriteKind
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.port_connection_model import ConnectionType, PortConnectionKey
from cmdb.models.port_model import PortKey
from cmdb.errors.security import AccessDeniedError
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

HOOK_PATH: str = 'cmdb.interface.rest_api.routes.port_routes.port_object_hooks'
PARAM: str = ObjectQueryParam.CLONE_PORTS_FROM.value
SOURCE_ID: int = 42
NEW_OBJECT_ID: int = 43
FRONT_ID: int = 7
REAR_ID: int = 8
CABLE_PEER_ID: int = 9
PORT_COUNT: int = 2


class TestReadPortCloneSource:
    """read_port_clone_source"""

    def test_absent_clones_nothing(self) -> None:
        """An ordinary create"""
        assert read_port_clone_source({}) is None

    def test_a_positive_integer_is_the_source(self) -> None:
        """Read as an int"""
        assert read_port_clone_source({PARAM: str(SOURCE_ID)}) == SOURCE_ID

    @pytest.mark.parametrize('value', ['', 'abc', '0', '-1', '1.5', ' 3', '3 ', chr(0x0663)],
                             ids=['empty', 'text', 'zero', 'negative', 'decimal', 'leading-space',
                                  'trailing-space', 'non-ascii-digit'])
    def test_anything_else_is_refused(self, value: str) -> None:
        """400 naming the parameter and the value"""
        with pytest.raises(HTTPException) as caught:
            read_port_clone_source({PARAM: value})

        assert caught.value.code == 400
        assert caught.value.description == PortCloneError.SOURCE_INVALID.format(param=PARAM, value=value)


def _target_type(uses_ports: bool = True) -> MagicMock:
    """The new object's CmdbType."""
    target_type = MagicMock()
    target_type.uses_ports = uses_ports

    return target_type


def _managers(port_count: int = PORT_COUNT) -> tuple[MagicMock, MagicMock]:
    """A ports manager holding a front + rear pair; a connections manager answering their links."""
    ports_manager = MagicMock()
    ports_manager.count_documents.return_value = port_count
    ports_manager.get_ports_of_object.return_value = [
        {PortKey.PUBLIC_ID.value: FRONT_ID}, {PortKey.PUBLIC_ID.value: REAR_ID}]
    connections_manager = MagicMock()
    connections_manager.get_connections_of_ports.return_value = [
        {PortConnectionKey.ENDPOINTS.value: [FRONT_ID, REAR_ID],
         PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value},
        {PortConnectionKey.ENDPOINTS.value: [FRONT_ID, CABLE_PEER_ID],
         PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.CABLE.value},
    ]

    return ports_manager, connections_manager


def _plan(objects_manager: MagicMock, managers: tuple[MagicMock, MagicMock], target_type: MagicMock | None = None,
          has_right: bool = True, locked: Exception | None = None, api_key: bool = False) -> PortClonePlan | None:
    """Runs plan_object_port_clone with the managers, the right and the licence patched."""
    by_type = {ManagerType.PORTS: managers[0], ManagerType.PORT_CONNECTIONS: managers[1]}

    def _has_right(right: str, _user: Any) -> bool:
        return has_right and right == PortRight.ADD

    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager', side_effect=lambda kind, _user: by_type[kind]), \
            patch(f'{HOOK_PATH}.user_has_right', side_effect=_has_right), \
            patch(f'{HOOK_PATH}.request_authenticates_by_api_key', return_value=api_key), \
            patch(f'{HOOK_PATH}.abort_if_feature_locked', side_effect=locked):
        return plan_object_port_clone(MagicMock(), SOURCE_ID, target_type or _target_type(), objects_manager)


def _readable_source() -> MagicMock:
    """An ObjectsManager that finds the source."""
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = {'public_id': SOURCE_ID}

    return objects_manager


def _refusal(*args: Any, **kwargs: Any) -> HTTPException:
    """The HTTPException a plan aborts with."""
    with pytest.raises(HTTPException) as caught:
        _plan(*args, **kwargs)

    return caught.value


class TestPlanObjectPortClone:
    """plan_object_port_clone"""

    def test_the_plan_holds_the_ports_and_only_the_internal_pairs(self) -> None:
        """The cable is left behind; the source is read under READ"""
        objects_manager = _readable_source()
        managers = _managers()

        plan = _plan(objects_manager, managers)

        assert plan == PortClonePlan(managers[0].get_ports_of_object.return_value, [(FRONT_ID, REAR_ID)])
        assert objects_manager.get_object.call_args.args[2] == AccessControlPermission.READ
        assert managers[0].count_documents.call_args.kwargs == {'limit': MAX_BULK_PORT_COUNT + 1}

    def test_a_source_without_ports_needs_nothing_more(self) -> None:
        """No licence, right or Type check"""
        assert _plan(_readable_source(), _managers(0), _target_type(False), has_right=False,
                     locked=HTTPException()) is None

    def test_an_unreadable_source_is_403(self) -> None:
        """Before any port is counted"""
        objects_manager = MagicMock()
        objects_manager.get_object.side_effect = AccessDeniedError('denied')
        managers = _managers()

        refusal = _refusal(objects_manager, managers)

        assert (refusal.code, refusal.description) == (
            403, PortCloneError.SOURCE_NOT_READABLE.format(object_id=SOURCE_ID))
        managers[0].count_documents.assert_not_called()

    def test_a_missing_source_is_404(self) -> None:
        """The message names the source"""
        objects_manager = MagicMock()
        objects_manager.get_object.return_value = None

        refusal = _refusal(objects_manager, _managers())

        assert (refusal.code, refusal.description) == (404, PortCloneError.SOURCE_NOT_FOUND.format(object_id=SOURCE_ID))

    def test_the_cloud_api_key_is_403_ahead_of_the_licence(self) -> None:
        """The port routes are closed to it"""
        refusal = _refusal(_readable_source(), _managers(), locked=HTTPException(), api_key=True)

        assert (refusal.code, refusal.description) == (
            403, PortCloneError.API_KEY_LOCKED.format(object_id=SOURCE_ID))

    def test_the_cloud_api_key_clones_a_source_without_ports(self) -> None:
        """Nothing of the port surface is reached"""
        assert _plan(_readable_source(), _managers(0), api_key=True) is None

    def test_a_locked_licence_refuses_first(self) -> None:
        """Ahead of the right"""
        locked = HTTPException()
        locked.code = 403

        assert _refusal(_readable_source(), _managers(), has_right=False, locked=locked) is locked

    def test_a_missing_right_is_403(self) -> None:
        """Naming the right"""
        refusal = _refusal(_readable_source(), _managers(), has_right=False)

        assert (refusal.code, refusal.description) == (403, PortCloneError.RIGHT_MISSING.format(
            object_id=SOURCE_ID, right=PortRight.ADD.value))

    def test_too_many_ports_are_400(self) -> None:
        """More than a bulk create may write"""
        refusal = _refusal(_readable_source(), _managers(MAX_BULK_PORT_COUNT + 1))

        assert (refusal.code, refusal.description) == (400, PortCloneError.TOO_MANY.format(
            object_id=SOURCE_ID, limit=MAX_BULK_PORT_COUNT))

    def test_exactly_the_limit_is_cloned(self) -> None:
        """The boundary"""
        assert _plan(_readable_source(), _managers(MAX_BULK_PORT_COUNT)) is not None

    def test_a_target_type_without_ports_is_400(self) -> None:
        """The new ports would be invisible"""
        refusal = _refusal(_readable_source(), _managers(), _target_type(False))

        assert (refusal.code, refusal.description) == (400, PortCloneError.TYPE_WITHOUT_PORTS.format(
            object_id=SOURCE_ID))


class TestInsertObjectWithClonedPorts:
    """insert_object_with_cloned_ports"""

    def test_without_a_plan_only_the_object_is_written(self) -> None:
        """The ordinary create"""
        objects_manager = MagicMock()
        objects_manager.insert_object.return_value = NEW_OBJECT_ID

        with patch(f'{HOOK_PATH}.clone_object_ports') as clone:
            assert insert_object_with_cloned_ports(objects_manager, {}, MagicMock(), None) == NEW_OBJECT_ID

        clone.assert_not_called()

    def test_the_object_is_recorded_before_its_ports_are_cloned(self) -> None:
        """So a failed clone takes the object with it"""
        objects_manager = MagicMock()
        objects_manager.insert_object.return_value = NEW_OBJECT_ID
        plan = PortClonePlan([{PortKey.PUBLIC_ID.value: FRONT_ID}], [])
        seen: list[Any] = []

        def _clone(_user: Any, given_plan: PortClonePlan, target: int, ledger: Any) -> None:
            seen.append((given_plan, target, [(entry.kind, entry.public_id) for entry in ledger.entries]))

        with patch(f'{HOOK_PATH}.clone_object_ports', side_effect=_clone):
            assert insert_object_with_cloned_ports(objects_manager, {}, MagicMock(), plan) == NEW_OBJECT_ID

        assert seen == [(plan, NEW_OBJECT_ID, [(WriteKind.INSERT, NEW_OBJECT_ID)])]
