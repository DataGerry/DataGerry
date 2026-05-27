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
Functional tests for the IPAM grafting branch of GET /ci_explorer/items

Pins the four target-role flows (SUPERNET / SUBNET / VLAN / interface carrier) and
verifies the wire contract: IPAM neighbours land in the same parent_nodes / children_nodes
buckets as object-relation neighbours, edges carry metadata.source='ipam' and the
agreed metadata.relation_name values
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest
from pymongo.mongo_client import MongoClient

from cmdb.database.mongo_connector import MongoConnector
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/ci_explorer/items'

# Type ids (kept distinct from the other CI Explorer functional test file to avoid clashes)
TYPE_SUPERNET: int = 30
TYPE_SUBNET: int = 31
TYPE_VLAN: int = 32
TYPE_SERVER: int = 33

# Object ids
OBJ_SUPERNET: int = 300
OBJ_SUBNET_CHILD_OF_SUPERNET: int = 301
OBJ_SUBNET_ORPHAN: int = 302  # has no dg-supernet-ref; used as control / interface target
OBJ_VLAN: int = 303
OBJ_SERVER_WITH_INTERFACE: int = 304


def _type_doc(
    public_id: int,
    name: str,
    label: str,
    special_type: str | None = None,
    fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Builds a CmdbType doc; ``special_type`` marks the SpecialType when applicable."""
    doc: dict[str, Any] = {
        'public_id': public_id,
        'name': name,
        'label': label,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': fields or [{'type': 'text', 'name': 'dg-name', 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [],
            'summary': {'fields': ['dg-name']},
        },
        'ci_explorer_label': 'dg-name',
        'ci_explorer_color': '#888',
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }
    if special_type is not None:
        doc['special_type'] = special_type
    return doc


def _object_doc(
    public_id: int,
    type_id: int,
    name: str,
    fields: list[dict[str, Any]] | None = None,
    multi_data_sections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Builds a CmdbObject doc with a 'dg-name' display field plus optional extra fields / MDS rows."""
    field_list: list[dict[str, Any]] = [{'name': 'dg-name', 'value': name}]

    if fields:
        field_list.extend(fields)

    doc: dict[str, Any] = {
        'public_id': public_id,
        'type_id': type_id,
        'status': True,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': field_list,
    }
    if multi_data_sections is not None:
        doc['multi_data_sections'] = multi_data_sections
    return doc


@pytest.fixture(scope='module', name='connector')
def fixture_connector(database_manager) -> MongoConnector:
    """Shortcut to the underlying MongoConnector for direct collection access."""
    return database_manager.connector


@pytest.fixture(scope='module', autouse=True)
def setup_ipam_ci_explorer_fixture(request, connector: MongoConnector, database_name):
    """Seeds the SPECIAL-typed CmdbTypes and the IPAM objects used across every test."""
    db = connector.client.get_database(database_name)
    types = db.get_collection(CmdbType.COLLECTION)
    objects = db.get_collection(CmdbObject.COLLECTION)

    types.insert_many([
        _type_doc(TYPE_SUPERNET, 'supernet', 'Supernet', special_type='SUPERNET'),
        _type_doc(TYPE_SUBNET, 'subnet', 'Subnet', special_type='SUBNET'),
        _type_doc(TYPE_VLAN, 'vlan', 'VLAN', special_type='VLAN'),
        _type_doc(TYPE_SERVER, 'server', 'Server'),
    ])

    objects.insert_many([
        # SUPERNET
        _object_doc(OBJ_SUPERNET, TYPE_SUPERNET, 'supernet-1'),
        # SUBNET pointing at the supernet via dg-supernet-ref
        _object_doc(
            OBJ_SUBNET_CHILD_OF_SUPERNET, TYPE_SUBNET, 'subnet-child',
            fields=[{'name': 'dg-supernet-ref', 'value': OBJ_SUPERNET}],
        ),
        # SUBNET without a parent supernet; serves as target of VLAN + interface tests
        _object_doc(OBJ_SUBNET_ORPHAN, TYPE_SUBNET, 'subnet-orphan'),
        # VLAN pointing at the orphan subnet via dg-subnet-ref
        _object_doc(
            OBJ_VLAN, TYPE_VLAN, 'vlan-1',
            fields=[{'name': 'dg-subnet-ref', 'value': OBJ_SUBNET_ORPHAN}],
        ),
        # Server carrying a dg-ipam-interface MDS row referencing the orphan subnet
        _object_doc(
            OBJ_SERVER_WITH_INTERFACE, TYPE_SERVER, 'srv-with-interface',
            multi_data_sections=[
                {
                    'section_id': 'dg-ipam-interface',
                    'values': [
                        {
                            'data': [
                                {'name': 'dg-interface-subnet', 'value': OBJ_SUBNET_ORPHAN},
                                {'name': 'dg-interface-ip-address', 'value': '10.0.0.5'},
                            ],
                        },
                    ],
                },
            ],
        ),
    ])

    def _drop_all() -> None:
        types.drop()
        objects.drop()

    request.addfinalizer(_drop_all)


# -------------------------------------------------------------------------------------------------------------------- #
#                                Smoke tests for IPAM grafting via with_ipam_relations                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCiExplorerIpamRelations:
    """Pins the with_ipam_relations contract across the four target-role flows."""

    def test_omitting_flag_yields_no_ipam_nodes(self, rest_api):
        """Without with_ipam_relations the IPAM neighbours are not grafted (default-off behaviour)"""
        response = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_SUPERNET}&target_type=BOTH')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body.get('children_nodes', []) == []
        assert body.get('parent_nodes', []) == []


    def test_supernet_target_grafts_child_subnets_with_ipam_source_tag(self, rest_api):
        """target=SUPERNET sees its child SUBNETs in children_nodes with metadata.source='ipam'"""
        response = rest_api.get(
            f'{ROUTE_URL}?target_id={OBJ_SUPERNET}&target_type=BOTH&with_ipam_relations=true',
        )

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        child_ids = {node['linked_object']['public_id'] for node in body['children_nodes']}
        assert OBJ_SUBNET_CHILD_OF_SUPERNET in child_ids

        edge = next(e for e in body['child_edges'] if e['to'] == OBJ_SUBNET_CHILD_OF_SUPERNET)
        assert edge['from'] == OBJ_SUPERNET
        assert edge['metadata']['source'] == 'ipam'
        assert edge['metadata']['relation_id'] is None
        assert edge['metadata']['relation_name'] == 'ipam-subnet'


    def test_subnet_target_grafts_parent_supernet_in_parent_bucket(self, rest_api):
        """target=SUBNET (with dg-supernet-ref) sees its parent SUPERNET in parent_nodes"""
        response = rest_api.get(
            f'{ROUTE_URL}?target_id={OBJ_SUBNET_CHILD_OF_SUPERNET}'
            f'&target_type=BOTH&with_ipam_relations=true',
        )

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        parent_ids = {node['linked_object']['public_id'] for node in body['parent_nodes']}
        assert OBJ_SUPERNET in parent_ids

        edge = next(e for e in body['parent_edges'] if e['from'] == OBJ_SUPERNET)
        assert edge['to'] == OBJ_SUBNET_CHILD_OF_SUPERNET
        assert edge['metadata']['source'] == 'ipam'
        assert edge['metadata']['relation_name'] == 'ipam-supernet'


    def test_orphan_subnet_target_grafts_vlan_and_interface_children(self, rest_api):
        """target=SUBNET (parent of a VLAN + an interface carrier) sees both as children with the right names"""
        response = rest_api.get(
            f'{ROUTE_URL}?target_id={OBJ_SUBNET_ORPHAN}'
            f'&target_type=BOTH&with_ipam_relations=true',
        )

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        child_ids = {node['linked_object']['public_id'] for node in body['children_nodes']}
        assert OBJ_VLAN in child_ids
        assert OBJ_SERVER_WITH_INTERFACE in child_ids

        vlan_edge = next(e for e in body['child_edges'] if e['to'] == OBJ_VLAN)
        assert vlan_edge['metadata']['relation_name'] == 'ipam-vlan'

        iface_edge = next(e for e in body['child_edges'] if e['to'] == OBJ_SERVER_WITH_INTERFACE)
        assert iface_edge['metadata']['relation_name'] == 'ipam-interface'


    def test_vlan_target_grafts_parent_subnet(self, rest_api):
        """target=VLAN sees its parent SUBNET in parent_nodes"""
        response = rest_api.get(
            f'{ROUTE_URL}?target_id={OBJ_VLAN}&target_type=BOTH&with_ipam_relations=true',
        )

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        parent_ids = {node['linked_object']['public_id'] for node in body['parent_nodes']}
        assert OBJ_SUBNET_ORPHAN in parent_ids

        edge = next(e for e in body['parent_edges'] if e['from'] == OBJ_SUBNET_ORPHAN)
        assert edge['to'] == OBJ_VLAN
        assert edge['metadata']['relation_name'] == 'ipam-subnet'
        assert edge['metadata']['source'] == 'ipam'


    def test_interface_carrier_target_grafts_referenced_subnets_as_parents(self, rest_api):
        """target=Server with dg-ipam-interface rows sees the referenced SUBNET in parent_nodes"""
        response = rest_api.get(
            f'{ROUTE_URL}?target_id={OBJ_SERVER_WITH_INTERFACE}'
            f'&target_type=BOTH&with_ipam_relations=true',
        )

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        parent_ids = {node['linked_object']['public_id'] for node in body['parent_nodes']}
        assert OBJ_SUBNET_ORPHAN in parent_ids

        edge = next(e for e in body['parent_edges'] if e['from'] == OBJ_SUBNET_ORPHAN)
        assert edge['to'] == OBJ_SERVER_WITH_INTERFACE
        assert edge['metadata']['relation_name'] == 'ipam-subnet'


    def test_target_type_child_only_drops_ipam_parent_neighbours(self, rest_api):
        """target_type=CHILD on a SUBNET hides its IPAM parent SUPERNET (only children bucket emitted)"""
        response = rest_api.get(
            f'{ROUTE_URL}?target_id={OBJ_SUBNET_CHILD_OF_SUPERNET}'
            f'&target_type=CHILD&with_ipam_relations=true',
        )

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'parent_nodes' not in body
        assert 'parent_edges' not in body
