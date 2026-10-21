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
Integration tests for the best-effort Port step of an object delete against a real MongoDB

The Port hook undoes its own cascade (`cascade.delete_ports_with_dependents` under `undone_on_failure`). Run through
`run_delete_cleanup_step` after the object is gone, a failure part-way therefore leaves the object's ports and their
connections whole - never half - is logged under the marker, and does not raise
"""
import logging
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.models.port_connection_model import CmdbPortConnection, ConnectionType, PortConnectionKey
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    DELETE_CLEANUP_INCOMPLETE_MARKER,
    DeleteCleanupStep,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_delete_cleanup import (
    run_delete_cleanup_step,
)
from cmdb.interface.rest_api.routes.port_routes.port_object_hooks import handle_object_deleted
from cmdb.errors.manager.ports_manager import PortsManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

pytestmark = pytest.mark.usefixtures('rest_api_app_context')

OBJECT_ID: int = 96501
PEER_OBJECT_ID: int = 96502
PORT_IDS: list[int] = [96511, 96512]
PEER_PORT_ID: int = 96513
CONNECTION_ID: int = 96521


def _port(public_id: int, object_id: int, name: str) -> dict[str, Any]:
    """A stored single-sided port"""
    return {
        PortKey.PUBLIC_ID.value: public_id, PortKey.OBJECT_ID.value: object_id, PortKey.NAME.value: name,
        PortKey.SIDE.value: PortSide.SINGLE.value, 'author_id': 1, 'creation_time': datetime.now(timezone.utc),
    }


@pytest.fixture(name='stored')
def fixture_stored(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[dict[str, Any]]:
    """The object's two ports, a peer port, and a cable from the first one to the peer; removed afterwards"""
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    connections = database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)

    def _purge() -> None:
        ports.delete_many({PortKey.PUBLIC_ID.value: {'$in': [*PORT_IDS, PEER_PORT_ID]}})
        connections.delete_many({PortConnectionKey.PUBLIC_ID.value: CONNECTION_ID})

    _purge()
    ports.insert_many([_port(PORT_IDS[0], OBJECT_ID, 'eth0'), _port(PORT_IDS[1], OBJECT_ID, 'eth1'),
                       _port(PEER_PORT_ID, PEER_OBJECT_ID, 'eth0')])
    connections.insert_one({
        PortConnectionKey.PUBLIC_ID.value: CONNECTION_ID,
        PortConnectionKey.ENDPOINTS.value: sorted([PORT_IDS[0], PEER_PORT_ID]),
        PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.CABLE.value,
        'author_id': 1, 'creation_time': datetime.now(timezone.utc),
    })

    yield {'ports': ports, 'connections': connections}

    _purge()


def _hook(database_manager: MongoDatabaseManager) -> Any:
    """The Port step of the object delete, on real managers"""
    return lambda: handle_object_deleted(
        None, {'public_id': OBJECT_ID}, PortsManager(database_manager), PortConnectionsManager(database_manager),
        PortInterfaceLinksManager(database_manager),
    )


def test_a_port_step_failing_part_way_leaves_everything_whole_and_is_logged(
        stored: dict[str, Any], database_manager: MongoDatabaseManager, monkeypatch, caplog) -> None:
    """The connection was already gone when the ports' delete failed: the undo put it back, and nothing raised"""
    def _failing(*_args: Any, **_kwargs: Any) -> int:
        raise PortsManagerDeleteError('the ports could not be deleted')

    monkeypatch.setattr(PortsManager, 'delete_ports_by_ids', _failing)

    with caplog.at_level(logging.ERROR):
        assert run_delete_cleanup_step(DeleteCleanupStep.PORTS, [OBJECT_ID], _hook(database_manager)) is False

    assert stored['ports'].count_documents({PortKey.OBJECT_ID.value: OBJECT_ID}) == 2
    assert stored['connections'].count_documents({PortConnectionKey.PUBLIC_ID.value: CONNECTION_ID}) == 1
    assert f'{DELETE_CLEANUP_INCOMPLETE_MARKER} step={DeleteCleanupStep.PORTS.value} objects=[{OBJECT_ID}]' \
        in caplog.text


def test_a_port_step_that_runs_through_removes_everything(
        stored: dict[str, Any], database_manager: MongoDatabaseManager) -> None:
    """The control: without a failure the ports and their cable go, and the peer port stays"""
    assert run_delete_cleanup_step(DeleteCleanupStep.PORTS, [OBJECT_ID], _hook(database_manager)) is True

    assert stored['ports'].count_documents({PortKey.OBJECT_ID.value: OBJECT_ID}) == 0
    assert stored['connections'].count_documents({PortConnectionKey.PUBLIC_ID.value: CONNECTION_ID}) == 0
    assert stored['ports'].count_documents({PortKey.PUBLIC_ID.value: PEER_PORT_ID}) == 1
