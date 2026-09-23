"""
No route may be reachable without credentials

Two guards that answer different questions run on most routes: `.protect` decides whether the caller
may do the thing, and `insert_request_user` decides whether there is a caller at all. `verify_api_access`
looks like a third but is not - it gates the external API **channel**, and it opens with

    if not current_app.cloud_mode:
        return func(*args, **kwargs)

so outside cloud mode it is a pass-through. A route guarded by it alone is therefore **unauthenticated
on-premise**, whatever `required_api_level` it names.

A repo-wide scan finds exactly two route files in that state: `setup_routes.py`, whose
blueprint is now registered only in cloud mode, and `rights_routes.py`, which gained
`insert_request_user` (no ACL right, deliberately - the catalogue is product metadata).

This file keeps both closed: the rights routes are checked by calling them, and the family is checked
by scanning the source, so a third one cannot appear unnoticed.

**Clearing the Authorization header takes an explicit environ override.** The test client sets
`environ_base['HTTP_AUTHORIZATION']` at construction, so every request it makes carries the
full-access user's token - `open()` included. A test that merely avoided `inject_auth` would be
exercising an authenticated call while claiming the opposite; that mistake was made once here already.
"""
from http import HTTPStatus
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

RIGHTS_ROUTES: list[str] = [
    '/rights/',
    '/rights/base.framework.object.view',
    '/rights/levels',
]

ROUTES_FOLDER: Path = Path('cmdb/interface/rest_api/routes')

NO_CREDENTIALS: dict[str, str] = {'HTTP_AUTHORIZATION': ''}


def _without_credentials(rest_api, route: str):
    """Issues a GET carrying no Authorization header at all."""
    return rest_api.open(
        route,
        method='GET',
        content_type='application/json',
        environ_overrides=NO_CREDENTIALS,
    )


class TestTheRightsCatalogueIsAuthenticated:
    """The catalogue must not answer to anyone who can reach the port."""

    @pytest.mark.parametrize('route', RIGHTS_ROUTES)
    def test_no_credentials_is_refused(self, rest_api, route: str) -> None:
        """401, not 200 - `insert_request_user` is what makes these routes authenticated."""
        assert _without_credentials(rest_api, route).status_code == HTTPStatus.UNAUTHORIZED

    @pytest.mark.parametrize('route', RIGHTS_ROUTES)
    def test_an_authenticated_caller_still_gets_the_catalogue(self, rest_api, route: str) -> None:
        """
        No ACL right was added, deliberately

        The rights tree is product metadata, identical for every installation and already public in
        the source of an AGPL product, and the group-edit screen needs it for anyone who may manage a
        group. The fix was authentication, not authorization - so an ordinary authenticated read must
        keep working.
        """
        assert rest_api.get(route).status_code == HTTPStatus.OK


class TestNoRouteFileIsUnauthenticatedOnPremise:
    """The family guard, so a third member cannot appear without anyone noticing."""

    @staticmethod
    def _route_files() -> list[Path]:
        """Every module that declares at least one route."""
        return [
            path for path in ROUTES_FOLDER.rglob('*.py')
            if '__pycache__' not in str(path) and 'blueprint.route(' in path.read_text(encoding='utf-8')
        ]

    def test_the_scan_finds_route_files_at_all(self) -> None:
        """A guard that matches nothing would pass forever."""
        assert len(self._route_files()) > 30

    def test_every_route_file_authenticates_or_authorizes(self) -> None:
        """
        `verify_api_access` alone is not a guard outside cloud mode

        A file carrying it with neither `insert_request_user` nor `.protect` publishes its routes to
        anyone who can reach the port on an on-premise installation. `setup_routes.py` is exempt: its
        blueprint is registered only in cloud mode, which is that surface's guard.
        """
        offenders: list[str] = []

        for path in self._route_files():
            source = path.read_text(encoding='utf-8')

            if path.name == 'setup_routes.py':
                continue

            if '@verify_api_access' not in source:
                continue

            if '@insert_request_user' not in source and '.protect(' not in source:
                offenders.append(str(path))

        assert offenders == []
