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
Functional tests for GET /rest/ipam/assignable-objects

Seeds two IPAM-capable CmdbTypes (one whose schema declares the dg-ipam-interface MDS
section) and one non-IPAM type, plus a small set of objects across them. Then walks the
route's wire contract through a real Flask + Mongo stack: the result lists every object of
an IPAM-capable type, ignores objects of non-IPAM types, paginates with the IpamPagination
bounds, and applies the case-insensitive summary-line substring filter
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database.mongo_connector import MongoConnector
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/ipam/assignable-objects/'


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the IPAM feature so the gated /ipam/assignable-objects route is reachable in these tests"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)

# Type ids (kept distinct from other functional fixtures to avoid clashes)
TYPE_SERVER: int = 40   # IPAM-capable (carries dg-ipam-interface section)
TYPE_ROUTER: int = 41   # IPAM-capable (carries dg-ipam-interface section)
TYPE_LOCATION: int = 42  # non-IPAM (no dg-ipam-interface section)

# Object ids
OBJ_SERVER_ALPHA: int = 4001
OBJ_SERVER_BRAVO: int = 4002
OBJ_ROUTER_CHARLIE: int = 4003
OBJ_ROUTER_DELTA: int = 4004
OBJ_LOCATION_ECHO: int = 4005


def _type_doc(
    public_id: int,
    name: str,
    label: str,
    with_ipam_interface_section: bool,
) -> dict[str, Any]:
    """Builds a CmdbType doc; adds the dg-ipam-interface MDS section when requested."""
    sections: list[dict[str, Any]] = []

    if with_ipam_interface_section:
        sections.append({
            'name': 'dg-ipam-interface',
            'type': 'multi-data-section',
            'label': 'IPAM Interface',
        })

    return {
        'public_id': public_id,
        'name': name,
        'label': label,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': 'dg-name', 'label': 'Name'}],
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


def _object_doc(public_id: int, type_id: int, name: str) -> dict[str, Any]:
    """Builds a CmdbObject doc carrying just the dg-name field used to render the summary line."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'status': True,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [{'name': 'dg-name', 'value': name}],
    }


@pytest.fixture(scope='module', name='connector')
def fixture_connector(database_manager) -> MongoConnector:
    """Shortcut to the underlying MongoConnector for direct collection access."""
    return database_manager.connector


@pytest.fixture(scope='module', autouse=True)
def setup_assignable_objects_fixture(request, connector: MongoConnector, database_name):
    """Seeds two IPAM-capable types, one non-IPAM type, and 5 objects across them."""
    db = connector.client.get_database(database_name)
    types = db.get_collection(CmdbType.COLLECTION)
    objects = db.get_collection(CmdbObject.COLLECTION)

    types.insert_many([
        _type_doc(TYPE_SERVER, 'server', 'Server', with_ipam_interface_section=True),
        _type_doc(TYPE_ROUTER, 'router', 'Router', with_ipam_interface_section=True),
        _type_doc(TYPE_LOCATION, 'location', 'Location', with_ipam_interface_section=False),
    ])

    objects.insert_many([
        _object_doc(OBJ_SERVER_ALPHA, TYPE_SERVER, 'web-alpha'),
        _object_doc(OBJ_SERVER_BRAVO, TYPE_SERVER, 'web-bravo'),
        _object_doc(OBJ_ROUTER_CHARLIE, TYPE_ROUTER, 'edge-charlie'),
        _object_doc(OBJ_ROUTER_DELTA, TYPE_ROUTER, 'edge-delta'),
        # non-IPAM-type object - must never appear in any assignable-objects response
        _object_doc(OBJ_LOCATION_ECHO, TYPE_LOCATION, 'site-echo'),
    ])

    def _drop_all() -> None:
        types.drop()
        objects.drop()

    request.addfinalizer(_drop_all)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TESTS                                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIpamAssignableObjectsRoute:
    """Pins the /ipam/assignable-objects wire contract end-to-end."""

    def test_lists_only_objects_of_ipam_capable_types(self, rest_api):
        """Objects of types lacking dg-ipam-interface MDS section are excluded; the other four survive"""
        response = rest_api.get(ROUTE_URL)

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        ids = {row['public_id'] for row in body['rows']}

        assert ids == {OBJ_SERVER_ALPHA, OBJ_SERVER_BRAVO, OBJ_ROUTER_CHARLIE, OBJ_ROUTER_DELTA}
        assert OBJ_LOCATION_ECHO not in ids
        assert body['total'] == 4

    def test_row_payload_carries_public_id_type_info_and_summary_line(self, rest_api):
        """Each row has {public_id, type_info: {public_id, label}, summary_line}; nothing else expected"""
        response = rest_api.get(ROUTE_URL)

        assert response.status_code == HTTPStatus.OK
        rows = response.get_json()['rows']
        row = next(r for r in rows if r['public_id'] == OBJ_SERVER_ALPHA)

        assert row['type_info'] == {'public_id': TYPE_SERVER, 'label': 'Server'}
        assert row['summary_line'].startswith('Server #')
        assert 'web-alpha' in row['summary_line']

    def test_envelope_includes_pagination_metadata(self, rest_api):
        """Response envelope carries page/page_size/total/search/rows; defaults are page=1, page_size=50"""
        response = rest_api.get(ROUTE_URL)

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        assert body['page'] == 1
        assert body['page_size'] == 50
        assert body['search'] == ''
        assert isinstance(body['rows'], list)

    def test_page_size_is_clamped_and_pagination_slices_correctly(self, rest_api):
        """page_size=2 + page=1 returns 2 rows; page=2 returns the remaining 2; both echo total=4"""
        page_one = rest_api.get(f'{ROUTE_URL}?page=1&page_size=2').get_json()
        page_two = rest_api.get(f'{ROUTE_URL}?page=2&page_size=2').get_json()

        assert len(page_one['rows']) == 2
        assert len(page_two['rows']) == 2
        assert page_one['total'] == 4
        assert page_two['total'] == 4

        ids_one = {r['public_id'] for r in page_one['rows']}
        ids_two = {r['public_id'] for r in page_two['rows']}
        assert ids_one.isdisjoint(ids_two)
        assert ids_one | ids_two == {OBJ_SERVER_ALPHA, OBJ_SERVER_BRAVO, OBJ_ROUTER_CHARLIE, OBJ_ROUTER_DELTA}

    def test_search_filter_narrows_to_matching_summary_lines(self, rest_api):
        """search='edge' matches only Router rows (their dg-name values start with 'edge-')"""
        response = rest_api.get(f'{ROUTE_URL}?search=edge')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        ids = {row['public_id'] for row in body['rows']}

        assert ids == {OBJ_ROUTER_CHARLIE, OBJ_ROUTER_DELTA}
        assert body['total'] == 2
        assert body['search'] == 'edge'

    def test_search_filter_is_case_insensitive(self, rest_api):
        """search='WEB' matches the Server rows just as 'web' would"""
        response = rest_api.get(f'{ROUTE_URL}?search=WEB')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        ids = {row['public_id'] for row in body['rows']}

        assert ids == {OBJ_SERVER_ALPHA, OBJ_SERVER_BRAVO}

    def test_short_search_query_is_ignored_and_full_list_returned(self, rest_api):
        """A 1-char search is below IpamSearch.MIN_QUERY_LENGTH and is treated as no filter"""
        response = rest_api.get(f'{ROUTE_URL}?search=w')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        assert body['total'] == 4
        assert body['search'] == 'w'
