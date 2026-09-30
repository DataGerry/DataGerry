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
Unit tests for the SPA host app (`cmdb.interface.net_app`) and its blueprint

The package needs
no database, no token and no frontend build: `index.html`, `_static/favicon.ico` and
`_static/browserconfig.xml` are tracked in git (only the compiled bundle is gitignored), so
`create_app().test_client()` answers every route here.

The behaviours under test, in the order they matter:

* **the fallback distinguishes a client route from a file.** Answering a missing `.js` chunk with
  `index.html` and a 200 is the post-deploy failure mode to avoid - the browser gets HTML where it
  asked for a script and reports a MIME error instead of a 404
* **a missing bundle is a 503, not a 500.** `send_static_file` raising inside the 404 handler is an
  exception Flask cannot handle, so every URL answered 500 and logged two tracebacks per request
* **cache lifetimes differ by file.** `index.html` names the content-hashed chunks, so it must not
  be cached; the chunks themselves may be
* **config selection**, which must not diverge between this factory and `create_rest_api`
"""
from http import HTTPStatus
from unittest.mock import patch

import pytest
from werkzeug.exceptions import NotFound

import cmdb
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.config import (
    DEFAULT_CONFIG_NAME,
    DevelopmentConfig,
    ProductionConfig,
    TestingConfig,
    app_config,
    config_name_for_mode,
)
from cmdb.interface.net_app import create_app
from cmdb.interface.net_app.app_routes import (
    ASSET_MAX_AGE,
    BROWSER_CONFIG_FILE,
    FAVICON_FILE,
    INDEX_FILE,
    MISSING_BUNDLE_STATUS,
    STATIC_DIR,
    _names_a_file,
    app_pages,
)
# -------------------------------------------------------------------------------------------------------------------- #

SPA_APPLICATION_ROOT: str = '/'


@pytest.fixture(name='client')
def fixture_client():
    """A test client for the SPA host - no database, no token, no frontend build."""
    return create_app().test_client()


class TestCreateApp:
    """What create_app wires onto the app object."""

    def test_builds_a_cmdb_app(self) -> None:
        """The SPA host is the same Flask subclass as the REST app, minus the database handle."""
        app = create_app()

        assert isinstance(app, BaseCmdbApp)
        assert app.database_manager is None

    def test_registers_the_spa_routes_and_nothing_else(self) -> None:
        """A rule that only ever 404s into the fallback is noise in the map."""
        rules = {rule.rule for rule in create_app().url_map.iter_rules()}

        assert rules == {'/', '/favicon.ico', '/browserconfig.xml', '/<path:filename>'}

    def test_has_no_dead_static_rule(self) -> None:
        """Flask's default static folder does not exist in this package, so the rule must not exist."""
        endpoints = {rule.endpoint for rule in create_app().url_map.iter_rules()}

        assert 'static' not in endpoints

    def test_is_mounted_at_the_root_not_at_the_api(self) -> None:
        """APPLICATION_ROOT must not be inherited as '/rest/' - the OTHER app's mount point."""
        assert create_app().config['APPLICATION_ROOT'] == SPA_APPLICATION_ROOT

    def test_registers_the_spa_fallback_for_404(self) -> None:
        """Without the handler a deep link after a hard reload is a bare 404, not the SPA."""
        handlers = create_app().error_handler_spec[None][HTTPStatus.NOT_FOUND]

        assert NotFound in handlers


class TestConfigSelection:
    """Both app factories select their config through one shared mapping."""

    @pytest.mark.parametrize('mode, expected', [
        ('DEBUG', 'development'),
        ('TESTING', 'testing'),
        ('INFO', DEFAULT_CONFIG_NAME),
        ('anything-else', DEFAULT_CONFIG_NAME),
    ], ids=str)
    def test_maps_the_mode_to_a_config_name(self, mode: str, expected: str) -> None:
        """An unrecognised mode is production - the safe default, never a crash."""
        assert config_name_for_mode(mode) == expected

    @pytest.mark.parametrize('mode, expected', [
        ('DEBUG', DevelopmentConfig),
        ('TESTING', TestingConfig),
        ('INFO', ProductionConfig),
    ], ids=str)
    def test_every_variant_is_reachable_from_this_factory(self, mode: str, expected: type) -> None:
        """TestingConfig is live here: create_app needs the TESTING branch create_rest_api has."""
        with patch.object(cmdb, '__MODE__', mode):
            app = create_app()

        assert app.config['DEBUG'] is expected.DEBUG
        assert app.config['TESTING'] is expected.TESTING

    def test_no_config_class_names_a_mount_point(self) -> None:
        """The two apps are mounted at different prefixes, so this cannot be a shared value."""
        assert all(not hasattr(config, 'APPLICATION_ROOT') for config in app_config.values())


class TestServesTheBundle:
    """The three explicit routes."""

    def test_root_serves_the_index(self, client) -> None:
        """A bare `/` anchors the SPA."""
        response = client.get('/')

        assert response.status_code == HTTPStatus.OK
        assert response.headers['Content-Type'].startswith('text/html')

    @pytest.mark.parametrize('url', ['/favicon.ico', '/browserconfig.xml'], ids=str)
    def test_serves_the_top_level_browser_assets(self, client, url: str) -> None:
        """Both come from the package's `_static/`, not from the Angular bundle."""
        assert client.get(url).status_code == HTTPStatus.OK

    def test_the_literal_routes_win_over_the_bundle_catch_all(self) -> None:
        """`/favicon.ico` must reach the view, not the bundle's static handler."""
        adapter = create_app().url_map.bind('localhost')

        assert adapter.match('/favicon.ico')[0] == 'app_pages.favicon'
        assert adapter.match('/browserconfig.xml')[0] == 'app_pages.browser_config'
        assert adapter.match('/some-chunk.js')[0] == 'app_pages.static'

    def test_the_static_dir_holds_both_assets(self) -> None:
        """The path is resolved once from the blueprint root; a wrong one would 404 both routes."""
        import os  # pylint: disable=import-outside-toplevel

        assert os.path.isfile(os.path.join(STATIC_DIR, FAVICON_FILE))
        assert os.path.isfile(os.path.join(STATIC_DIR, BROWSER_CONFIG_FILE))


class TestNamesAFile:
    """The test that separates a client route from an asset request."""

    @pytest.mark.parametrize('path', [
        '/assets/logo.png', '/chunk-ABC123.js', '/styles-DEF.css', '/favicon.ico', '/a/b/c.json',
    ], ids=str)
    def test_a_path_with_an_extension_names_a_file(self, path: str) -> None:
        """Every asset the bundle references carries an extension."""
        assert _names_a_file(path) is True

    @pytest.mark.parametrize('path', [
        '/', '/objects', '/objects/42', '/framework/type/edit/7', '/deep/link/with/many/segments',
    ], ids=str)
    def test_a_path_without_one_is_a_client_route(self, path: str) -> None:
        """No Angular route in this application contains a dot, which is what makes the test exact."""
        assert _names_a_file(path) is False


class TestSpaFallback:
    """An unmatched URL: the SPA for a client route, a real 404 for a file."""

    @pytest.mark.parametrize('url', ['/deep/link', '/objects/42', '/framework/type/edit/7'], ids=str)
    def test_an_unmatched_client_route_serves_the_spa(self, client, url: str) -> None:
        """A hard reload on a client route has to load the bundle so the router can resolve it."""
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        assert response.headers['Content-Type'].startswith('text/html')

    @pytest.mark.parametrize('url', [
        '/assets/does-not-exist.png', '/chunk-STALE.js', '/missing.css',
    ], ids=str)
    def test_a_missing_asset_keeps_its_404(self, client, url: str) -> None:
        """
        Answering HTML with a 200 here is the classic post-deploy failure

        A browser holding a cached index.html asks for a hashed chunk that no longer exists; served
        the bundle instead, it reports a MIME-type or syntax error and nothing says a file was gone.
        """
        assert client.get(url).status_code == HTTPStatus.NOT_FOUND

    def test_the_fallback_does_not_redirect(self, client) -> None:
        """It returns the bundle directly, so the client keeps the URL the user asked for."""
        response = client.get('/deep/link')

        assert response.status_code == HTTPStatus.OK
        assert 'Location' not in response.headers


class TestMissingBundle:
    """`make webapp` never ran, or built somewhere else."""

    @pytest.mark.parametrize('url', ['/', '/deep/link'], ids=['root', 'fallback'])
    def test_answers_503_instead_of_raising(self, client, url: str) -> None:
        """Raising inside the 404 handler leaves Flask no handler left, which would answer 500."""
        with patch.object(app_pages, 'send_static_file', side_effect=NotFound()):
            response = client.get(url)

        assert response.status_code == MISSING_BUNDLE_STATUS

    def test_the_body_names_the_cause(self, client) -> None:
        """A bare 503 would not tell an operator that the frontend was never built."""
        with patch.object(app_pages, 'send_static_file', side_effect=NotFound()):
            body = client.get('/').get_data(as_text=True)

        assert 'make webapp' in body


class TestCacheLifetimes:
    """The entry document and the chunks it names cannot share a cache policy."""

    def test_the_index_is_never_cached(self, client) -> None:
        """It names the content-hashed chunks; a stale copy asks for files that no longer exist."""
        assert 'no-cache' in client.get('/').headers['Cache-Control']

    def test_bundle_files_are_cacheable(self) -> None:
        """Without this every chunk is revalidated against the server on every page load."""
        assert app_pages.get_send_file_max_age('chunk-ABC123.js') == ASSET_MAX_AGE

    def test_the_index_is_excluded_by_name(self) -> None:
        """Flask asks by filename, and the bundle's own static handler serves index.html too."""
        assert app_pages.get_send_file_max_age(INDEX_FILE) == 0

    def test_an_unknown_filename_is_not_cached(self) -> None:
        """Flask passes None when it cannot resolve a name - the safe answer is 'do not cache'."""
        assert app_pages.get_send_file_max_age(None) == 0
