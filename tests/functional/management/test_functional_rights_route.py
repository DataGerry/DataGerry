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
Functional smoke for the ``/rights`` REST routes

The rights are a static, in-memory tree (not database-backed), so there is no CRUD to seed.
These tests verify the route-layer contract: the list envelope + X-Total-Count, the flat vs
tree view switch, sorting/pagination, the single-right lookup, the 404 on a missing name
(regression: a missing right used to surface as a 500), and the static levels endpoint.
"""
from http import HTTPStatus

from werkzeug.exceptions import NotFound

from cmdb.manager import RightsManager
from cmdb.interface.rest_api.routes.user_management_routes import rights_routes
from cmdb.models.right_model.all_rights import ALL_RIGHTS, flat_rights_tree
from cmdb.errors.manager.rights_manager import RightsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/rights'

# A right guaranteed to exist in ALL_RIGHTS (also referenced by the bootstrap user group)
KNOWN_RIGHT_NAME: str = 'base.framework.type.view'
MISSING_RIGHT_NAME: str = 'base.does.not.exist'

PAGE_LIMIT: int = 5
ORDER_DESC: int = -1

# The number of rights the tree declares - what BOTH views have to report as their total. The tree
# view used to report len(ALL_RIGHTS) instead, i.e. the number of top-level groups
DECLARED_RIGHTS_COUNT: int = len(flat_rights_tree(ALL_RIGHTS))
TOP_LEVEL_GROUP_COUNT: int = len(ALL_RIGHTS)

# A ?sort= value that is not an attribute of BaseRight
UNKNOWN_SORT_FIELD: str = 'not_an_attribute'


class TestGetRightsList:
    """Tests for GET /rights/"""

    def test_list_returns_results_envelope(self, rest_api) -> None:
        """GET /rights/ returns a non-empty results envelope; the page never exceeds the total."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        total = int(response.headers['X-Total-Count'])
        assert total > 0
        assert 0 < len(body['results']) <= total

    def test_list_respects_limit(self, rest_api) -> None:
        """A limit caps the page size while the total still reflects every right."""
        response = rest_api.get(f'{ROUTE_URL}/?limit={PAGE_LIMIT}')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == PAGE_LIMIT
        assert int(response.headers['X-Total-Count']) > PAGE_LIMIT

    def test_list_is_sorted_by_name(self, rest_api) -> None:
        """The default flat view is sorted by right name (ascending)."""
        response = rest_api.get(f'{ROUTE_URL}/')

        names = [right['name'] for right in response.get_json()['results']]
        assert names == sorted(names)

    def test_list_descending_order(self, rest_api) -> None:
        """order=-1 reverses the name sort."""
        response = rest_api.get(f'{ROUTE_URL}/?order={ORDER_DESC}')

        names = [right['name'] for right in response.get_json()['results']]
        assert names == sorted(names, reverse=True)

    def test_tree_view_returns_nested_structure(self, rest_api) -> None:
        """The tree view returns the nesting-preserving structure (contains nested lists)."""
        response = rest_api.get(f'{ROUTE_URL}/?view=tree')

        assert response.status_code == HTTPStatus.OK
        results = response.get_json()['results']
        assert any(isinstance(node, list) for node in results)

    def test_tree_view_total_counts_rights_not_groups(self, rest_api) -> None:
        """The tree view reports the number of rights, not the number of top-level groups."""
        response = rest_api.get(f'{ROUTE_URL}/?view=tree')

        assert int(response.headers['X-Total-Count']) == DECLARED_RIGHTS_COUNT
        assert DECLARED_RIGHTS_COUNT > TOP_LEVEL_GROUP_COUNT

    def test_flat_view_total_counts_every_right(self, rest_api) -> None:
        """The flat view's total is the full number of rights, independent of the page size."""
        response = rest_api.get(f'{ROUTE_URL}/?limit={PAGE_LIMIT}')

        assert int(response.headers['X-Total-Count']) == DECLARED_RIGHTS_COUNT

    def test_both_views_report_the_same_total(self, rest_api) -> None:
        """Flat and tree are two renderings of one collection, so their totals must agree."""
        flat = rest_api.get(f'{ROUTE_URL}/')
        tree = rest_api.get(f'{ROUTE_URL}/?view=tree')

        assert flat.headers['X-Total-Count'] == tree.headers['X-Total-Count']


class TestGetSingleRight:
    """Tests for GET /rights/<name>"""

    def test_returns_known_right(self, rest_api) -> None:
        """A known right name returns the matching right."""
        response = rest_api.get(f'{ROUTE_URL}/{KNOWN_RIGHT_NAME}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['name'] == KNOWN_RIGHT_NAME

    def test_missing_right_returns_404(self, rest_api) -> None:
        """A missing right name returns 404 (regression: previously surfaced as 500)."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_RIGHT_NAME}')

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestGetLevels:
    """Tests for GET /rights/levels"""

    def test_returns_levels_mapping(self, rest_api) -> None:
        """The levels endpoint returns the non-empty name->level mapping."""
        response = rest_api.get(f'{ROUTE_URL}/levels')

        assert response.status_code == HTTPStatus.OK
        assert len(response.get_json()['result']) > 0


def _raise(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The route maps manager / unexpected failures to the right HTTP status."""

    def test_unknown_sort_field_returns_500(self, rest_api) -> None:
        """An unknown ?sort= reaches BaseRight.__getitem__ as an unknown attribute."""
        response = rest_api.get(f'{ROUTE_URL}/?sort={UNKNOWN_SORT_FIELD}')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_rights_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected failure while iterating surfaces as 500."""
        monkeypatch.setattr(RightsManager, 'iterate_rights', _raise(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_right_manager_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A RightsManagerGetError surfaces as 500 (rights are static; a get failure is internal)."""
        monkeypatch.setattr(RightsManager, 'get_right', _raise(RightsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/base.*').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_right_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected failure while retrieving a single right surfaces as 500."""
        monkeypatch.setattr(RightsManager, 'get_right', _raise(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/base.*').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_rights_http_exception_passes_through(self, rest_api, monkeypatch) -> None:
        """An HTTPException raised inside the list route keeps its own status, not a 500."""
        monkeypatch.setattr(RightsManager, 'iterate_rights', _raise(NotFound()))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.NOT_FOUND

    def test_get_levels_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A failure while serialising the levels mapping surfaces as 500."""
        monkeypatch.setattr(rights_routes, 'GetSingleResponse', _raise(RuntimeError('boom')))

        response = rest_api.get(f'{ROUTE_URL}/levels')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
