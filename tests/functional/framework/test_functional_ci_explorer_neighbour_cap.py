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
Functional tests: `item_limit` on `GET /ci_explorer/items` keeps the same, lowest-id neighbours, through the real app

Every document is stored highest id first, so a natural-order read would answer the highest neighbours:

  - a busy switch (port connections): two calls with `item_limit=2` answer the same two lowest-id devices
  - doubled cabling: `item_limit=1` answers one node with both its cable edges - a slot is a neighbour, not a cable
  - a busy supernet (IPAM): two calls with `item_limit=2` answer the same two lowest-id subnets
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_connection_model import CmdbPortConnection, PortConnectionKey
from cmdb.models.port_model import CmdbPort, PortKey
from cmdb.models.special_type_model.ipam_constants import SubnetField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
from tests.utils.port_doc_builders import cable_doc, device_doc, port_doc
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/ci_explorer/items'
TYPE_DEVICE: int = 47010
TYPE_SUPERNET: int = 47011
TYPE_SUBNET: int = 47012
TYPE_IDS: list[int] = [TYPE_DEVICE, TYPE_SUPERNET, TYPE_SUBNET]
SWITCH: int = 47100
DEVICES: list[int] = [47101, 47102, 47103]
SUPERNET: int = 47200
SUBNETS: list[int] = [47201, 47202, 47203]
OBJECT_IDS: list[int] = [SWITCH, *DEVICES, SUPERNET, *SUBNETS]
SWITCH_PORTS: list[int] = [47301, 47302, 47303, 47304]
# One far port per device, a second on the lowest device
FAR_PORTS: dict[int, int] = {47311: DEVICES[0], 47312: DEVICES[1], 47313: DEVICES[2], 47314: DEVICES[0]}
PORT_IDS: list[int] = SWITCH_PORTS + list(FAR_PORTS)
# (connection id, switch port, far port)
CABLES: list[tuple[int, int, int]] = [(47401, 47301, 47311), (47402, 47302, 47312), (47403, 47303, 47313),
                                      (47404, 47304, 47314)]
CONNECTION_IDS: list[int] = [cable[0] for cable in CABLES]
MONGO_ID_INDEX: str = '_id_'


@pytest.fixture(autouse=True)
def _licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The port source needs the IPAM licence"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The switch, its devices and cables, the supernet and its subnets - each stored highest id first"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    connections = database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
        ports.delete_many({PortKey.PUBLIC_ID.value: {'$in': PORT_IDS}})
        connections.delete_many({PortConnectionKey.PUBLIC_ID.value: {'$in': CONNECTION_IDS}})

    _purge()
    had_indexes: dict[Any, set[str]] = {collection: set(collection.index_information())
                                        for collection in (ports, connections)}
    database_manager.create_indexes(CmdbPortConnection.COLLECTION, database_name, CmdbPortConnection.get_index_keys())
    database_manager.create_indexes(CmdbPort.COLLECTION, database_name, CmdbPort.get_index_keys())

    types.insert_many([make_type_doc(TYPE_DEVICE, 'cap-device'),
                       make_type_doc(TYPE_SUPERNET, 'cap-supernet', SpecialType.SUPERNET),
                       make_type_doc(TYPE_SUBNET, 'cap-subnet', SpecialType.SUBNET)])
    objects.insert_many([device_doc(object_id, TYPE_DEVICE) for object_id in reversed([SWITCH, *DEVICES])]
                        + [make_object_doc(SUPERNET, TYPE_SUPERNET, [make_field('dg-name', 'cap-supernet')])]
                        + [make_object_doc(subnet, TYPE_SUBNET,
                                           [make_field(SubnetField.PARENT_SUPERNET.value, SUPERNET)])
                           for subnet in reversed(SUBNETS)])
    ports.insert_many([port_doc(port_id, SWITCH) for port_id in SWITCH_PORTS]
                      + [port_doc(port_id, owner) for port_id, owner in FAR_PORTS.items()])
    connections.insert_many([cable_doc(connection_id, [near, far]) for connection_id, near, far in reversed(CABLES)])

    yield

    _purge()

    for collection, existing in had_indexes.items():
        for index_name in set(collection.index_information()) - existing - {MONGO_ID_INDEX}:
            collection.drop_index(index_name)


def _children(rest_api, target_id: int, item_limit: int, **flags: str) -> tuple[list[int], int]:
    """The child node ids, sorted, and how many child edges the graph answers"""
    response = rest_api.get(ROUTE_URL, query_string={'target_id': target_id, 'item_limit': item_limit,
                                                     'target_type': 'CHILD', **flags})

    assert response.status_code == HTTPStatus.OK
    body: dict[str, Any] = response.get_json()

    return (sorted(node['linked_object']['public_id'] for node in body['children_nodes']),
            len(body['child_edges']))


def test_a_busy_switch_shows_the_same_lowest_devices(rest_api) -> None:
    """Port connections, two slots: the two lowest devices, every time"""
    first = _children(rest_api, SWITCH, 2, with_port_connections='true')

    assert first[0] == DEVICES[:2]
    assert _children(rest_api, SWITCH, 2, with_port_connections='true') == first


def test_doubled_cabling_is_one_node_with_both_edges(rest_api) -> None:
    """One slot: the lowest device, reached by two cables"""
    assert _children(rest_api, SWITCH, 1, with_port_connections='true') == ([DEVICES[0]], 2)


def test_a_busy_supernet_shows_the_same_lowest_subnets(rest_api) -> None:
    """IPAM, two slots: the two lowest subnets, every time"""
    first = _children(rest_api, SUPERNET, 2, with_ipam_relations='true', with_port_connections='false')

    assert first[0] == SUBNETS[:2]
    assert _children(rest_api, SUPERNET, 2, with_ipam_relations='true', with_port_connections='false') == first
