"""
Functional tests for the Service-Portal setup / teardown routes (/setup)

**This file proves the routes are absent from an on-premise process, because that absence is the
guard.**

The routes exist for the DataGerry Service Portal to tear down a tenant: drop its database, evict it
from the shared user cache. None of them carries `@insert_request_user` or `.protect` - their only
decorator is `verify_api_access`, which returns immediately when the process is not in cloud mode. So
a blueprint registered unconditionally would publish, on an on-premise installation,

    DELETE /rest/setup/subscriptions?database=<name>

with **no credentials of any kind**, and the name would go straight to `drop_database` with nothing
checking that it belonged to a subscription.

`init_rest_api` registers the blueprint only when `cmdb.__CLOUD_MODE__` is set, and **the
registration is the whole guard** - which is what these tests check. The test suite runs on-premise,
so the routes must be absent from the URL map entirely.

The handlers' own behaviour - the error mapping, the payload branches of `delete_cached_user` - is
covered by the setup routes' own unit tests.
"""
from http import HTTPStatus

import pytest

import cmdb
# -------------------------------------------------------------------------------------------------------------------- #

SUBSCRIPTIONS_ROUTE: str = '/setup/subscriptions'
CACHE_USER_ROUTE: str = '/setup/cache/user'
CACHE_USER_ALL_ROUTE: str = '/setup/cache/user/all'

SETUP_ROUTES: list[str] = [SUBSCRIPTIONS_ROUTE, CACHE_USER_ROUTE, CACHE_USER_ALL_ROUTE]


class TestTheSetupSurfaceIsAbsentOnPremise:
    """The registration is the guard: on-premise the routes do not exist to be called."""

    def test_the_test_process_is_not_in_cloud_mode(self) -> None:
        """The premise of every assertion below - without it they would prove nothing."""
        assert not cmdb.__CLOUD_MODE__

    @pytest.mark.parametrize('route', SETUP_ROUTES)
    def test_no_setup_route_is_in_the_url_map(self, rest_api, route: str) -> None:
        """Not reachable, rather than reachable and refused."""
        rules = {str(rule) for rule in rest_api.application.url_map.iter_rules()}

        assert route not in rules

    @pytest.mark.parametrize('route', SETUP_ROUTES)
    def test_calling_a_setup_route_answers_404(self, rest_api, route: str) -> None:
        """What a caller sees: the surface is not there."""
        assert rest_api.delete(route).status_code == HTTPStatus.NOT_FOUND

    def test_an_unauthenticated_teardown_is_not_reachable(self, rest_api) -> None:
        """
        An unauthenticated teardown cannot reach the handler

        **The Authorization header has to be cleared explicitly.** `rest_api.open` is not enough:
        the test client sets `environ_base['HTTP_AUTHORIZATION']` at construction, so every request
        it makes - `open` included - carries the full-access user's token unless the environ is
        overridden. A test that only skipped `inject_auth` would be testing an authenticated call
        while claiming otherwise.
        """
        response = rest_api.open(
            f'{SUBSCRIPTIONS_ROUTE}?database=definitely-not-a-real-database',
            method='DELETE',
            content_type='application/json',
            environ_overrides={'HTTP_AUTHORIZATION': ''},
        )

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_no_route_under_the_setup_prefix_survives(self, rest_api) -> None:
        """A future route added to that blueprint inherits the guard rather than needing its own."""
        under_setup = [
            str(rule) for rule in rest_api.application.url_map.iter_rules()
            if str(rule).startswith('/setup')
        ]

        assert under_setup == []
