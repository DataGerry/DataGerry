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
(a missing right must not surface as a 500), and the static levels endpoint.
"""
from http import HTTPStatus

import pytest

from werkzeug.exceptions import NotFound

from cmdb.manager import RightsManager
from cmdb.interface.rest_api.routes.user_management_routes import rights_routes
from cmdb.models.right_model.all_rights import ALL_RIGHTS, flat_rights_tree
from cmdb.models.right_model.levels_enum import Levels
from cmdb.errors.manager.rights_manager import RightsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/rights'

# A right guaranteed to exist in ALL_RIGHTS (also referenced by the bootstrap user group)
KNOWN_RIGHT_NAME: str = 'base.framework.type.view'
MISSING_RIGHT_NAME: str = 'base.does.not.exist'

PAGE_LIMIT: int = 5
ORDER_DESC: int = -1

# The number of rights the tree declares - what BOTH views have to report as their total. The tree
# the view must not report len(ALL_RIGHTS) instead, i.e. the number of top-level groups
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
        """A missing right name returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_RIGHT_NAME}')

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestGetLevels:
    """Tests for GET /rights/levels"""

    def test_returns_levels_mapping(self, rest_api) -> None:
        """The levels endpoint returns the non-empty name->level mapping."""
        response = rest_api.get(f'{ROUTE_URL}/levels')

        assert response.status_code == HTTPStatus.OK
        assert len(response.get_json()['result']) > 0

    def test_serves_every_level_with_its_number(self, rest_api) -> None:
        """
        The catalogue itself, not just its size

        This assertion is the wire contract: a client renders the names and works with the numbers,
        so a renamed key or a renumbered level is a breaking change wherever it is consumed.
        """
        result = rest_api.get(f'{ROUTE_URL}/levels').get_json()['result']

        assert result == {level.name: int(level) for level in Levels}

    def test_keeps_the_declaration_order(self, rest_api) -> None:
        """
        CRITICAL first, descending - a JSON object preserves the order it was built in

        The catalogue is derived from the enum (`Levels.as_name_map`), so the order is the enum's.
        A hand-written dict whose order happens to match is not enough; a member inserted
        between two others appears where it was declared instead of where someone remembered to
        type it.
        """
        response = rest_api.get(f'{ROUTE_URL}/levels')

        assert list(response.get_json()['result']) == [level.name for level in Levels]


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


# -------------------------------------------------------------------------------------------------------------------- #
#                                            GET /rights/overview                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetRightsOverview:
    """A page of rights, each carrying the CmdbUserGroups that hold it.

    The column this feeds would otherwise take one count request PER RIGHT - ~200 of them for a
    catalogue of ~200 rights, because the page loads the whole thing unpaginated. The route answers
    the same data in two queries, whatever the page size.
    """

    def test_every_entry_carries_both_group_keys(self, rest_api) -> None:
        """Filled for every right, so an empty list is an answer and not a missing one"""
        results = rest_api.get(f'{ROUTE_URL}/overview').get_json()['results']

        assert results
        assert all('groups' in entry and 'groups_count' in entry for entry in results)

    def test_the_count_matches_the_group_list(self, rest_api) -> None:
        """The number beside the list and the list itself come from one answer"""
        results = rest_api.get(f'{ROUTE_URL}/overview?limit=0').get_json()['results']

        assert all(entry['groups_count'] == len(entry['groups']) for entry in results)

    def test_the_seeded_user_group_is_reported_for_a_right_it_holds(self, rest_api) -> None:
        """The bootstrap 'user' group holds base.framework.type.view - it has to show up"""
        results = rest_api.get(f'{ROUTE_URL}/overview?limit=0').get_json()['results']
        entry = next(right for right in results if right['name'] == KNOWN_RIGHT_NAME)

        assert entry['groups_count'] >= 1
        assert all({'public_id', 'name', 'label'} <= set(group) for group in entry['groups'])

    def test_membership_is_literal_not_inherited(self, rest_api) -> None:
        """The bootstrap 'admin' group holds only the master right, and is counted only for it

        Deliberate: a wildcard grants the right at request time through `has_extended_right`, but
        counting it here would make the number disagree with the listing behind it, which matches
        on the stored name.
        """
        results = rest_api.get(f'{ROUTE_URL}/overview?limit=0').get_json()['results']
        by_name = {right['name']: right for right in results}

        admin_holds_master = any(group['name'] == 'admin' for group in by_name['base.*']['groups'])
        admin_holds_a_leaf = any(
            group['name'] == 'admin' for group in by_name[KNOWN_RIGHT_NAME]['groups']
        )

        assert admin_holds_master
        assert not admin_holds_a_leaf

    def test_a_right_no_group_holds_reports_zero(self, rest_api) -> None:
        """Absent from the aggregation, present in the payload"""
        results = rest_api.get(f'{ROUTE_URL}/overview?limit=0').get_json()['results']
        unheld = [entry for entry in results if entry['groups_count'] == 0]

        assert unheld
        assert all(entry['groups'] == [] for entry in unheld)

    def test_it_paginates(self, rest_api) -> None:
        """The page is a window on the catalogue, and the total is the whole of it"""
        response = rest_api.get(f'{ROUTE_URL}/overview?limit={PAGE_LIMIT}&sort=name&order=1&page=1')
        body = response.get_json()

        assert response.status_code == HTTPStatus.OK
        assert len(body['results']) == PAGE_LIMIT
        assert body['total'] == DECLARED_RIGHTS_COUNT

    def test_a_second_page_carries_different_rights(self, rest_api) -> None:
        """Paging moves the window rather than repeating it"""
        first = rest_api.get(f'{ROUTE_URL}/overview?limit=3&sort=name&order=1&page=1').get_json()
        second = rest_api.get(f'{ROUTE_URL}/overview?limit=3&sort=name&order=1&page=2').get_json()

        assert [entry['name'] for entry in first['results']] != \
            [entry['name'] for entry in second['results']]

    def test_it_sorts(self, rest_api) -> None:
        """Same ordering contract as the plain list route"""
        names = [entry['name'] for entry in
                 rest_api.get(f'{ROUTE_URL}/overview?limit=0&sort=name&order=1').get_json()['results']]

        assert names == sorted(names)

    def test_it_requires_authentication(self, rest_api) -> None:
        """A token is required, like every route of this blueprint"""
        response = rest_api.get(f'{ROUTE_URL}/overview', environ_overrides={'HTTP_AUTHORIZATION': ''})

        assert response.status_code == HTTPStatus.UNAUTHORIZED


class TestRightsOverviewSearch:
    """`?search=` narrows the catalogue before the page is cut."""

    def test_it_narrows_the_results(self, rest_api) -> None:
        """A term matches against name, label and description"""
        body = rest_api.get(f'{ROUTE_URL}/overview?limit=0&search=docapi').get_json()

        assert body['results']
        assert all('docapi' in entry['name'] for entry in body['results'])

    def test_the_total_counts_matches_not_the_catalogue(self, rest_api) -> None:
        """Otherwise a pager built on it offers pages that come back empty"""
        body = rest_api.get(f'{ROUTE_URL}/overview?limit=0&search=docapi').get_json()

        assert body['total'] == len(body['results'])
        assert body['total'] < DECLARED_RIGHTS_COUNT

    def test_it_paginates_the_matches(self, rest_api) -> None:
        """The window is cut out of the matches, and the total stays the match count"""
        body = rest_api.get(f'{ROUTE_URL}/overview?limit=2&page=1&sort=name&order=1&search=docapi').get_json()
        unpaged = rest_api.get(f'{ROUTE_URL}/overview?limit=0&search=docapi').get_json()

        assert len(body['results']) == 2
        assert body['total'] == unpaged['total']

    def test_it_matches_the_label_too(self, rest_api) -> None:
        """The term is what a human reads in the table, not only the identifier"""
        body = rest_api.get(f'{ROUTE_URL}/overview?limit=0&search=View type').get_json()

        assert any(entry['name'] == KNOWN_RIGHT_NAME for entry in body['results'])

    def test_it_is_case_insensitive(self, rest_api) -> None:
        """Same contract as every other list route's search"""
        lower = rest_api.get(f'{ROUTE_URL}/overview?limit=0&search=docapi').get_json()
        upper = rest_api.get(f'{ROUTE_URL}/overview?limit=0&search=DOCAPI').get_json()

        assert lower['total'] == upper['total'] > 0

    def test_the_term_is_literal_text_not_a_pattern(self, rest_api) -> None:
        """A dot is a dot: `base.docapi` must not match as `base<any char>docapi`"""
        dotted = rest_api.get(f'{ROUTE_URL}/overview?limit=0&search=base.docapi').get_json()
        wildcarded = rest_api.get(f'{ROUTE_URL}/overview?limit=0&search=base%5Bacdipo%5D%2Bdocapi').get_json()

        assert dotted['total'] > 0
        assert wildcarded['total'] == 0

    @pytest.mark.parametrize('query', ['', '   '])
    def test_a_blank_term_narrows_nothing(self, rest_api, query: str) -> None:
        """An unsearched listing is exactly what it was"""
        body = rest_api.get(f'{ROUTE_URL}/overview?limit=0&search={query}').get_json()

        assert body['total'] == DECLARED_RIGHTS_COUNT

    def test_no_match_is_an_empty_page_not_an_error(self, rest_api) -> None:
        """A term nothing matches answers 200 with nothing in it"""
        response = rest_api.get(f'{ROUTE_URL}/overview?limit=0&search=zzz-no-such-right')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['total'] == 0

    def test_the_group_data_survives_a_search(self, rest_api) -> None:
        """The column the route exists for is filled on a searched page too"""
        body = rest_api.get(f'{ROUTE_URL}/overview?limit=0&search=docapi').get_json()

        assert all('groups' in entry and 'groups_count' in entry for entry in body['results'])
