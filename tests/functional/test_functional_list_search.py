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
Functional tests for ``?search=`` across the list routes that gained it

Every table in the product has a search box, and each one would otherwise implement it in the browser -
`$addFields` casting the columns it wanted, then a `$match` with an `$or` of `$regex` conditions,
posted as ``?filter=``. One helper answers all of them instead,
so this module asks every wired route the same three questions rather than repeating a bespoke test
per screen: does the parameter narrow, does a non-match empty the list, and does an absent term leave
the listing alone.

The uniform probe is the **public_id**, because every one of these entities has one and it is an
integer - so a match proves the string conversion is doing real work, which is the thing eighteen
Angular components each hard-coded for themselves.
"""
from http import HTTPStatus

import pytest

from cmdb.manager.license_manager.license_service import LicenseService
# -------------------------------------------------------------------------------------------------------------------- #

#: Every list route that gained ``?search=``, with a public_id known to exist in a seeded database
SEARCHABLE_ROUTES: list[tuple[str, str]] = [
    ('/users', '1'),
    ('/groups', '1'),
    ('/relations', None),
    ('/reports', None),
    ('/report_categories', None),
    ('/docs/template', None),  # the DocapiTemplate listing, mounted under /docs
    ('/webhook_events', None),
]

NO_SUCH_TERM: str = 'no-such-value-anywhere-xyz'


@pytest.fixture(autouse=True)
def _enable_licensed_features(monkeypatch: pytest.MonkeyPatch):
    """
    Stubs the license check so the document-generator listing is reachable

    ``/docapi/template`` is gated on `LicenseFeature.DOCUMENT_GENERATOR`, and a 403 would make every
    assertion below pass for the wrong reason.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


#: The one route served without a trailing slash, so the shared URL builder has to know
NO_TRAILING_SLASH: frozenset[str] = frozenset({'/docs/template'})


def _url(route: str, query: str = '') -> str:
    """The listing URL of a route, with the pager and an optional extra query argument."""
    base = route if route in NO_TRAILING_SLASH else f'{route}/'

    return f'{base}?limit=0' + (f'&{query}' if query else '')


def _results(response) -> list:
    """The results array of a listing response."""
    return response.get_json()['results']


@pytest.mark.parametrize('route', [route for route, _ in SEARCHABLE_ROUTES])
def test_the_route_accepts_the_search_parameter(rest_api, route: str) -> None:
    """Wired, and answering - not a 400 because the parameter is unknown to it."""
    assert rest_api.get(_url(route, 'search=anything')).status_code == HTTPStatus.OK


@pytest.mark.parametrize('route', [route for route, _ in SEARCHABLE_ROUTES])
def test_a_term_that_matches_nothing_empties_the_listing(rest_api, route: str) -> None:
    """It narrows rather than being ignored - the failure mode of an unread parameter."""
    response = rest_api.get(_url(route, f'search={NO_SUCH_TERM}'))

    assert response.status_code == HTTPStatus.OK
    assert _results(response) == []


@pytest.mark.parametrize('route', [route for route, _ in SEARCHABLE_ROUTES])
def test_a_blank_term_leaves_the_listing_alone(rest_api, route: str) -> None:
    """A cleared search box is not a search, so the totals have to agree."""
    unsearched = rest_api.get(_url(route)).get_json()['total']
    blank = rest_api.get(_url(route, 'search=')).get_json()['total']

    assert unsearched == blank


@pytest.mark.parametrize('route, public_id', [(r, p) for r, p in SEARCHABLE_ROUTES if p])
def test_a_public_id_is_searchable(rest_api, route: str, public_id: str) -> None:
    """
    The integer columns are converted before they are matched

    A `$regex` matches no number at all, which is why every one of these screens had to build its own
    `$toString` - and why the ISMS impact filter, which forgot to, silently matches nothing.
    """
    listed = [row['public_id'] for row in _results(rest_api.get(_url(route, f'search={public_id}')))]

    assert int(public_id) in listed


class TestUserSearchIsLiteralAndScoped:
    """The one route probed in depth; the machinery it exercises is shared by all of them."""

    def test_a_text_column_is_searchable(self, rest_api) -> None:
        """The seeded administrator is found by name."""
        listed = [row['user_name'] for row in _results(rest_api.get('/users/?limit=0&search=admin'))]

        assert 'admin' in listed

    def test_the_search_is_case_insensitive(self, rest_api) -> None:
        """A search box matches regardless of case."""
        listed = [row['user_name'] for row in _results(rest_api.get('/users/?limit=0&search=ADMIN'))]

        assert 'admin' in listed

    def test_a_wildcard_matches_nothing_rather_than_everything(self, rest_api) -> None:
        """``?search=`` is literal text: `.*` is two characters to look for, not a pattern."""
        response = rest_api.get('/users/?limit=0&search=.%2A')

        assert response.status_code == HTTPStatus.OK
        assert _results(response) == []

    def test_an_invalid_pattern_is_answered_not_refused(self, rest_api) -> None:
        """An unbalanced bracket would be a database error if the term were a pattern."""
        assert rest_api.get('/users/?limit=0&search=%5Bunclosed').status_code == HTTPStatus.OK

    def test_the_total_agrees_with_the_rows(self, rest_api) -> None:
        """The search is part of the criteria, so the count aggregation applies it too."""
        body = rest_api.get('/users/?limit=0&search=admin').get_json()

        assert body['total'] == len(body['results'])

    def test_the_returned_user_keeps_its_columns(self, rest_api) -> None:
        """The stages add a working field and remove it again; they do not reshape the document."""
        row = _results(rest_api.get('/users/?limit=0&search=admin'))[0]

        assert {'public_id', 'user_name', 'email'} <= set(row)
