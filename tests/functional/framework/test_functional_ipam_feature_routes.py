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
Functional smoke tests for the IPAM REST routes through the real Flask + Mongo stack

One request per route that no other functional module covers: the sidebar tree trio, the
family-filterable subnet options list (incl. the 400 on an invalid family token), the subnet
overview family (main / invalid / sector / export / unassign), the supernet overview family
(main / children / invalid / export / unassign) and the four inline pre-validation routes.
Assertions stay at the wire-contract level (status code + envelope keys + one shape detail);
the substantive behaviour is pinned by the framework-layer unit and integration tests
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.models.object_model import CmdbObject, CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SupernetField,
    SubnetField,
    InterfaceField,
    IpamSection,
    IpAddressFamily,
)
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TREE_URL: str = '/ipam/tree/'
SUBNET_URL: str = '/ipam/subnet/'
SUBNET_OVERVIEW_URL: str = '/ipam/subnet/overview'
SUPERNET_OVERVIEW_URL: str = '/ipam/supernet/overview'
VALIDATE_URL: str = '/ipam/validate'

SUPERNET_TYPE_ID: int = 46
SUBNET_TYPE_ID: int = 47
CARRIER_TYPE_ID: int = 48

SUPERNET_ID: int = 4601
SUBNET_PARENT_ID: int = 4602   # 10.1.0.0/16
SUBNET_CHILD_ID: int = 4603    # 10.1.4.0/24
SUBNET_ORPHAN_ID: int = 4604   # no supernet ref
CARRIER_ID: int = 4605

SUPERNET_RANGE: str = '10.0.0.0/8'
SUBNET_PARENT_RANGE: str = '10.1.0.0/16'
SUBNET_CHILD_RANGE: str = '10.1.4.0/24'
SUBNET_ORPHAN_RANGE: str = '192.168.0.0/16'
ASSIGNED_IP: str = '10.1.4.5'

UNKNOWN_PUBLIC_ID: int = 49999

TYPE_IDS: list[int] = [SUPERNET_TYPE_ID, SUBNET_TYPE_ID, CARRIER_TYPE_ID]
OBJECT_IDS: list[int] = [SUPERNET_ID, SUBNET_PARENT_ID, SUBNET_CHILD_ID, SUBNET_ORPHAN_ID, CARRIER_ID]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _subnet_doc(public_id: int, name: str, cidr: str, supernet_ref: int | None) -> dict[str, Any]:
    """Builds a SUBNET object doc with an optional parent supernet reference."""
    fields = [
        make_field(SubnetField.NAME, name),
        make_field(SubnetField.TYPE, IpAddressFamily.IPV4),
        make_field(SubnetField.NETWORK_RANGE, cidr),
    ]

    if supernet_ref is not None:
        fields.append(make_field(SubnetField.PARENT_SUPERNET, supernet_ref))

    return make_object_doc(public_id, SUBNET_TYPE_ID, fields)


@pytest.fixture(scope='module', autouse=True)
def _seed_ipam_route_topology(request, database_manager, database_name):
    """Seeds the IPAM types plus a supernet / nested subnets / orphan / carrier, cleaning up after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    types.insert_many([
        make_type_doc(SUPERNET_TYPE_ID, 'fn-ipam-supernet', SpecialType.SUPERNET),
        make_type_doc(SUBNET_TYPE_ID, 'fn-ipam-subnet', SpecialType.SUBNET),
        make_type_doc(CARRIER_TYPE_ID, 'fn-ipam-carrier', None),
    ])

    objects.insert_many([
        make_object_doc(SUPERNET_ID, SUPERNET_TYPE_ID, [
            make_field(SupernetField.NAME, 'fn-sn'),
            make_field(SupernetField.TYPE, IpAddressFamily.IPV4),
            make_field(SupernetField.NETWORK_RANGE, SUPERNET_RANGE),
        ]),
        _subnet_doc(SUBNET_PARENT_ID, 'fn-parent', SUBNET_PARENT_RANGE, SUPERNET_ID),
        _subnet_doc(SUBNET_CHILD_ID, 'fn-child', SUBNET_CHILD_RANGE, SUPERNET_ID),
        _subnet_doc(SUBNET_ORPHAN_ID, 'fn-orphan', SUBNET_ORPHAN_RANGE, None),
        make_object_doc(CARRIER_ID, CARRIER_TYPE_ID, [make_field('dg-name', 'fn-host')], mds=[{
            CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
            CmdbObjectMdsKey.VALUES: [{CmdbObjectMdsRowKey.DATA: [
                make_field(InterfaceField.SUBNET, SUBNET_CHILD_ID),
                make_field(InterfaceField.IP, ASSIGNED_IP),
                make_field(InterfaceField.TYPE, IpAddressFamily.IPV4),
            ]}],
        }]),
    ])

    def _cleanup() -> None:
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})

    request.addfinalizer(_cleanup)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   TREE ROUTES                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIpamTreeRoutes:
    """Smoke-level wire contract of the three sidebar-tree routes."""

    def test_tree_root_returns_supernets_and_unassigned(self, rest_api):
        """GET /ipam/tree/ delivers both blocks with the seeded entries"""
        response = rest_api.get(TREE_URL)

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert [s['public_id'] for s in body['supernets']] == [SUPERNET_ID]
        assert body['supernets'][0]['has_children'] is True
        assert [s['public_id'] for s in body['unassigned']] == [SUBNET_ORPHAN_ID]

    def test_tree_supernet_subtree_returns_nested_children(self, rest_api):
        """GET /ipam/tree/supernets/<id> delivers the CIDR-nested children block"""
        response = rest_api.get(f'{TREE_URL}supernets/{SUPERNET_ID}')

        assert response.status_code == HTTPStatus.OK
        roots = response.get_json()['children']
        assert [n['public_id'] for n in roots] == [SUBNET_PARENT_ID]
        assert [n['public_id'] for n in roots[0]['children']] == [SUBNET_CHILD_ID]

    def test_tree_supernet_subtree_unknown_id_is_404(self, rest_api):
        """GET /ipam/tree/supernets/<unknown> returns 404"""
        response = rest_api.get(f'{TREE_URL}supernets/{UNKNOWN_PUBLIC_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_tree_unassigned_returns_the_orphan_block(self, rest_api):
        """GET /ipam/tree/unassigned delivers the flat orphan list"""
        response = rest_api.get(f'{TREE_URL}unassigned')

        assert response.status_code == HTTPStatus.OK
        assert [s['public_id'] for s in response.get_json()['unassigned']] == [SUBNET_ORPHAN_ID]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 SUBNET OPTIONS                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIpamSubnetOptionsRoute:
    """Smoke-level wire contract of the family-filterable subnet options list."""

    def test_options_filtered_by_family(self, rest_api):
        """GET /ipam/subnet/?type=ipv4 lists the v4 subnets with the picker envelope"""
        response = rest_api.get(f'{SUBNET_URL}?type={IpAddressFamily.IPV4.value}')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['type'] == IpAddressFamily.IPV4.value
        assert {r['public_id'] for r in body['rows']} == {SUBNET_PARENT_ID, SUBNET_CHILD_ID, SUBNET_ORPHAN_ID}

    def test_options_rejects_an_invalid_family_token(self, rest_api):
        """GET /ipam/subnet/?type=ipv5 is rejected with 400"""
        response = rest_api.get(f'{SUBNET_URL}?type=ipv5')

        assert response.status_code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                               SUBNET OVERVIEW ROUTES                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIpamSubnetOverviewRoutes:
    """Smoke-level wire contract of the subnet IP-table route family."""

    def test_subnet_overview_lists_the_assigned_ip(self, rest_api):
        """GET .../overview/<id> carries the KPI block and the stored interface IP"""
        response = rest_api.get(f'{SUBNET_OVERVIEW_URL}/{SUBNET_CHILD_ID}')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['subnet']['public_id'] == SUBNET_CHILD_ID
        assert body['subnet']['used_ips'] == 1

    def test_subnet_invalid_overview_responds(self, rest_api):
        """GET .../overview/<id>/invalid returns the invalid-only envelope"""
        response = rest_api.get(f'{SUBNET_OVERVIEW_URL}/{SUBNET_CHILD_ID}/invalid')

        assert response.status_code == HTTPStatus.OK
        assert 'invalid_count' in response.get_json()

    def test_subnet_sector_drilldown_responds(self, rest_api):
        """GET .../overview/<id>/sector returns the sector echo with its IP rows"""
        response = rest_api.get(
            f'{SUBNET_OVERVIEW_URL}/{SUBNET_CHILD_ID}/sector?sector_start=10.1.4.0',
        )

        assert response.status_code == HTTPStatus.OK
        assert 'sector' in response.get_json()

    def test_subnet_export_streams_a_workbook(self, rest_api):
        """GET .../overview/<id>/export answers with the xlsx attachment"""
        response = rest_api.get(f'{SUBNET_OVERVIEW_URL}/{SUBNET_CHILD_ID}/export')

        assert response.status_code == HTTPStatus.OK
        assert 'spreadsheetml' in response.headers['Content-Type']

    def test_subnet_unassign_clears_the_interface_reference(self, rest_api):
        """POST .../overview/<id>/unassign detaches the stored IP row (runs last: it writes)"""
        response = rest_api.post(
            f'{SUBNET_OVERVIEW_URL}/{SUBNET_CHILD_ID}/unassign',
            json={'ips': [ASSIGNED_IP]},
        )

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['unassigned_count'] == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                              SUPERNET OVERVIEW ROUTES                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIpamSupernetOverviewRoutes:
    """Smoke-level wire contract of the supernet overview route family."""

    def test_supernet_overview_lists_top_level_subnets(self, rest_api):
        """GET .../overview/<id> carries the KPI block and the top-level subnet row"""
        response = rest_api.get(f'{SUPERNET_OVERVIEW_URL}/{SUPERNET_ID}')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['supernet']['public_id'] == SUPERNET_ID
        assert [r['public_id'] for r in body['subnets']['rows']] == [SUBNET_PARENT_ID]

    def test_supernet_children_fetch_responds(self, rest_api):
        """GET .../subnets/children/<subnet_id> returns the lazy children rows"""
        response = rest_api.get(
            f'{SUPERNET_OVERVIEW_URL}/{SUPERNET_ID}/subnets/children/{SUBNET_PARENT_ID}',
        )

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['parent']['public_id'] == SUBNET_PARENT_ID
        assert [r['public_id'] for r in body['rows']] == [SUBNET_CHILD_ID]

    def test_supernet_invalid_overview_responds(self, rest_api):
        """GET .../subnets/invalid returns the invalid-only envelope"""
        response = rest_api.get(f'{SUPERNET_OVERVIEW_URL}/{SUPERNET_ID}/subnets/invalid')

        assert response.status_code == HTTPStatus.OK
        assert 'invalid_count' in response.get_json()

    def test_supernet_subnets_export_streams_a_workbook(self, rest_api):
        """GET .../subnets/export answers with the xlsx attachment"""
        response = rest_api.get(f'{SUPERNET_OVERVIEW_URL}/{SUPERNET_ID}/subnets/export')

        assert response.status_code == HTTPStatus.OK
        assert 'spreadsheetml' in response.headers['Content-Type']

    def test_supernet_unassign_detaches_a_subnet(self, rest_api):
        """POST .../subnets/unassign detaches the child subnet (runs last: it writes)"""
        response = rest_api.post(
            f'{SUPERNET_OVERVIEW_URL}/{SUPERNET_ID}/subnets/unassign',
            json={'subnet_ids': [SUBNET_CHILD_ID]},
        )

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['unassigned_count'] == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                                VALIDATION ROUTES                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIpamValidationRoutes:
    """Smoke-level wire contract of the four inline pre-validation routes."""

    def test_validate_subnet_route(self, rest_api):
        """POST /ipam/validate/subnet answers with the {valid, errors} envelope"""
        response = rest_api.post(f'{VALIDATE_URL}/subnet', json={
            'network_range': '10.7.0.0/24',
            'subnet_type': IpAddressFamily.IPV4.value,
        })

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {'valid': True, 'errors': []}

    def test_validate_supernet_route_reports_a_family_mismatch(self, rest_api):
        """POST /ipam/validate/supernet surfaces the validator's structured errors"""
        response = rest_api.post(f'{VALIDATE_URL}/supernet', json={
            'network_range': '2001:db8::/32',
            'supernet_type': IpAddressFamily.IPV4.value,
        })

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['valid'] is False
        assert 'does not match the address family' in body['errors'][0]['message']

    def test_validate_vlan_route(self, rest_api):
        """POST /ipam/validate/vlan accepts a reference to the seeded subnet"""
        response = rest_api.post(f'{VALIDATE_URL}/vlan', json={'subnet_id': SUBNET_PARENT_ID})

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['valid'] is True

    def test_validate_interface_route_reports_a_missing_type(self, rest_api):
        """POST /ipam/validate/interface flags a data row without the type token"""
        response = rest_api.post(f'{VALIDATE_URL}/interface', json={
            'rows': [{'row_index': 0, 'subnet_id': SUBNET_PARENT_ID, 'ip_address': '10.1.0.9'}],
        })

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['valid'] is False
        assert any('is required' in e['message'] for e in body['errors'])
