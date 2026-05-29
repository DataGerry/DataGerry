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
Functional tests for the relaxed IPAM range-change behaviour

Pins the contract that a SUPERNET or SUBNET CIDR edit now goes through even when the new
range would push existing child rows (child subnets / interface IPs) outside it. The
orphaned children stay on disk untouched - the FE surfaces them as is_valid=False in the
respective overview routes, but the save-side never aborts on this scenario any more.

Exercised via PATCH /rest/objects/<id> against a real Flask + Mongo stack so the full
enforcement pipeline (enforce_object_invariants → format_errors_for_abort → 400) is
covered end-to-end
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database.mongo_connector import MongoConnector
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_ROUTE: str = '/objects'

# Type ids (kept distinct from other functional fixtures to avoid clashes)
TYPE_SUPERNET: int = 50
TYPE_SUBNET: int = 51
TYPE_SERVER: int = 52

# Object ids - Scenario A: supernet CIDR change orphans child subnet
OBJ_SUPERNET_A: int = 5001
OBJ_CHILD_SUBNET_A: int = 5002

# Object ids - Scenario B: subnet CIDR change orphans an interface IP
OBJ_ORPHAN_SUBNET_B: int = 5003
OBJ_SERVER_WITH_IP_B: int = 5004

# CIDR constants
SUPERNET_A_OLD_CIDR: str = '10.0.0.0/8'
SUPERNET_A_NEW_CIDR: str = '11.0.0.0/8'   # disjoint from old: child no longer fits
CHILD_SUBNET_A_CIDR: str = '10.1.0.0/16'  # inside SUPERNET_A_OLD_CIDR, outside SUPERNET_A_NEW_CIDR

SUBNET_B_OLD_CIDR: str = '10.2.0.0/16'
SUBNET_B_NEW_CIDR: str = '11.2.0.0/16'    # disjoint from old: interface IP no longer fits
INTERFACE_IP_B: str = '10.2.0.5'          # inside SUBNET_B_OLD_CIDR, outside SUBNET_B_NEW_CIDR


def _type_doc(
    public_id: int,
    name: str,
    label: str,
    special_type: str | None = None,
    extra_field_names: list[str] | None = None,
    with_ipam_interface_section: bool = False,
) -> dict[str, Any]:
    """
    Builds a CmdbType doc; ``extra_field_names`` lets the SUPERNET/SUBNET types declare their
    CIDR field. A 'main' section listing every declared field is added so the PUT/PATCH route's
    field-merge step (which only honors fields referenced by render_meta.sections) keeps the
    PATCHed values intact
    """
    all_field_names: list[str] = ['dg-name']
    fields: list[dict[str, Any]] = [{'type': 'text', 'name': 'dg-name', 'label': 'Name'}]

    for extra_name in extra_field_names or []:
        fields.append({'type': 'text', 'name': extra_name, 'label': extra_name})
        all_field_names.append(extra_name)

    sections: list[dict[str, Any]] = [{
        'type': 'section',
        'name': 'main',
        'label': 'Main',
        'fields': all_field_names,
    }]

    if with_ipam_interface_section:
        sections.append({
            'name': 'dg-ipam-interface',
            'type': 'multi-data-section',
            'label': 'IPAM Interface',
        })

    doc: dict[str, Any] = {
        'public_id': public_id,
        'name': name,
        'label': label,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': fields,
        'render_meta': {
            'icon': 'fa-cube',
            'sections': sections,
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
    fields: list[dict[str, Any]],
    multi_data_sections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Builds a CmdbObject doc with the given fields and optional MDS rows."""
    doc: dict[str, Any] = {
        'public_id': public_id,
        'type_id': type_id,
        'status': True,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': fields,
    }

    if multi_data_sections is not None:
        doc['multi_data_sections'] = multi_data_sections

    return doc


def _patch_payload_with_new_range(
    current_doc: dict[str, Any],
    new_range: str,
    range_field_name: str,
) -> dict[str, Any]:
    """Builds a PATCH payload from the current document with the network-range field overwritten."""
    new_fields: list[dict[str, Any]] = []

    for entry in current_doc['fields']:
        if entry['name'] == range_field_name:
            new_fields.append({'name': entry['name'], 'value': new_range})
        else:
            new_fields.append({'name': entry['name'], 'value': entry['value']})

    return {
        'public_id': current_doc['public_id'],
        'type_id': current_doc['type_id'],
        'fields': new_fields,
        'multi_data_sections': current_doc.get('multi_data_sections', []),
        'active': True,
        'author_id': current_doc['author_id'],
        'version': current_doc.get('version', '1.0.0'),
    }


@pytest.fixture(scope='module', name='connector')
def fixture_connector(database_manager) -> MongoConnector:
    """Shortcut to the underlying MongoConnector for direct collection access."""
    return database_manager.connector


@pytest.fixture(scope='module', autouse=True)
def setup_ipam_range_change_fixture(request, connector: MongoConnector, database_name):
    """Seeds the IPAM SpecialType CmdbTypes plus the four objects used across both scenarios."""
    db = connector.client.get_database(database_name)
    types = db.get_collection(CmdbType.COLLECTION)
    objects = db.get_collection(CmdbObject.COLLECTION)

    types.insert_many([
        _type_doc(
            TYPE_SUPERNET, 'supernet', 'Supernet',
            special_type='SUPERNET',
            extra_field_names=['dg-network-range'],
        ),
        _type_doc(
            TYPE_SUBNET, 'subnet', 'Subnet',
            special_type='SUBNET',
            extra_field_names=['dg-network-range', 'dg-supernet-ref'],
        ),
        _type_doc(
            TYPE_SERVER, 'server', 'Server',
            with_ipam_interface_section=True,
        ),
    ])

    objects.insert_many([
        # Scenario A: SUPERNET with a child SUBNET sitting inside its range
        _object_doc(
            OBJ_SUPERNET_A, TYPE_SUPERNET,
            fields=[
                {'name': 'dg-name', 'value': 'supernet-a'},
                {'name': 'dg-network-range', 'value': SUPERNET_A_OLD_CIDR},
            ],
        ),
        _object_doc(
            OBJ_CHILD_SUBNET_A, TYPE_SUBNET,
            fields=[
                {'name': 'dg-name', 'value': 'child-subnet-a'},
                {'name': 'dg-network-range', 'value': CHILD_SUBNET_A_CIDR},
                {'name': 'dg-supernet-ref', 'value': OBJ_SUPERNET_A},
            ],
        ),
        # Scenario B: orphan SUBNET (no parent) with a Server carrying an interface IP inside it
        _object_doc(
            OBJ_ORPHAN_SUBNET_B, TYPE_SUBNET,
            fields=[
                {'name': 'dg-name', 'value': 'orphan-subnet-b'},
                {'name': 'dg-network-range', 'value': SUBNET_B_OLD_CIDR},
            ],
        ),
        _object_doc(
            OBJ_SERVER_WITH_IP_B, TYPE_SERVER,
            fields=[{'name': 'dg-name', 'value': 'server-b'}],
            multi_data_sections=[
                {
                    'section_id': 'dg-ipam-interface',
                    'values': [
                        {
                            'data': [
                                {'name': 'dg-interface-subnet', 'value': OBJ_ORPHAN_SUBNET_B},
                                {'name': 'dg-interface-ip-address', 'value': INTERFACE_IP_B},
                                {'name': 'dg-interface-mac-address', 'value': ''},
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


def _read_object(connector: MongoConnector, database_name: str, public_id: int) -> dict[str, Any]:
    """Reads a CmdbObject document directly from Mongo (bypasses ACL / managers)."""
    db = connector.client.get_database(database_name)
    return db.get_collection(CmdbObject.COLLECTION).find_one({'public_id': public_id})


def _field_value(doc: dict[str, Any], field_name: str) -> Any:
    """Returns the 'value' of the named field in a CmdbObject document, or None when absent."""
    for entry in doc.get('fields', []):
        if entry.get('name') == field_name:
            return entry.get('value')

    return None


# -------------------------------------------------------------------------------------------------------------------- #
#                                  Scenario A: SUPERNET CIDR change orphans child SUBNET                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSupernetCidrChangeAllowedWhenChildSubnetsOrphan:
    """PATCH to a disjoint supernet CIDR is accepted; the now-orphaned child subnet survives."""

    def test_patch_succeeds_instead_of_returning_400(
        self, rest_api, connector: MongoConnector, database_name: str,
    ):
        """The PATCH is accepted (formerly 400 with 'IPAM validation failed: Child subnet ...')"""
        current = _read_object(connector, database_name, OBJ_SUPERNET_A)
        payload = _patch_payload_with_new_range(current, SUPERNET_A_NEW_CIDR, 'dg-network-range')

        response = rest_api.patch(f'{OBJECTS_ROUTE}/{OBJ_SUPERNET_A}', json=payload)

        assert response.status_code == HTTPStatus.ACCEPTED, (
            f"PATCH returned {response.status_code}; body: {response.data!r}"
        )

    def test_supernet_range_was_actually_persisted(
        self, connector: MongoConnector, database_name: str,
    ):
        """The new CIDR is the value stored on the SUPERNET after the PATCH"""
        stored = _read_object(connector, database_name, OBJ_SUPERNET_A)

        assert _field_value(stored, 'dg-network-range') == SUPERNET_A_NEW_CIDR

    def test_child_subnet_remains_untouched(
        self, connector: MongoConnector, database_name: str,
    ):
        """The orphaned child subnet's range and supernet-ref are not modified by the supernet PATCH"""
        stored = _read_object(connector, database_name, OBJ_CHILD_SUBNET_A)

        assert _field_value(stored, 'dg-network-range') == CHILD_SUBNET_A_CIDR
        assert _field_value(stored, 'dg-supernet-ref') == OBJ_SUPERNET_A


# -------------------------------------------------------------------------------------------------------------------- #
#                                Scenario B: SUBNET CIDR change orphans interface IP                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSubnetCidrChangeAllowedWhenInterfaceIpsOrphan:
    """PATCH to a disjoint subnet CIDR is accepted; the now-orphaned interface IP row survives."""

    def test_patch_succeeds_instead_of_returning_400(
        self, rest_api, connector: MongoConnector, database_name: str,
    ):
        """The PATCH is accepted (formerly 400 with 'IPAM validation failed: Interface IP ...')"""
        current = _read_object(connector, database_name, OBJ_ORPHAN_SUBNET_B)
        payload = _patch_payload_with_new_range(current, SUBNET_B_NEW_CIDR, 'dg-network-range')

        response = rest_api.patch(f'{OBJECTS_ROUTE}/{OBJ_ORPHAN_SUBNET_B}', json=payload)

        assert response.status_code == HTTPStatus.ACCEPTED, (
            f"PATCH returned {response.status_code}; body: {response.data!r}"
        )

    def test_subnet_range_was_actually_persisted(
        self, connector: MongoConnector, database_name: str,
    ):
        """The new CIDR is the value stored on the SUBNET after the PATCH"""
        stored = _read_object(connector, database_name, OBJ_ORPHAN_SUBNET_B)

        assert _field_value(stored, 'dg-network-range') == SUBNET_B_NEW_CIDR

    def test_server_interface_row_remains_untouched(
        self, connector: MongoConnector, database_name: str,
    ):
        """The orphaned interface row keeps its IP and subnet reference after the subnet PATCH"""
        stored = _read_object(connector, database_name, OBJ_SERVER_WITH_IP_B)
        section = next(
            s for s in stored.get('multi_data_sections', [])
            if s.get('section_id') == 'dg-ipam-interface'
        )
        row = section['values'][0]
        data: dict[str, Any] = {entry['name']: entry['value'] for entry in row['data']}

        assert data['dg-interface-subnet'] == OBJ_ORPHAN_SUBNET_B
        assert data['dg-interface-ip-address'] == INTERFACE_IP_B
