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
Unit tests for cmdb.interface.rest_api.init_rest_api

DB-free. `create_rest_api` builds the real app - every blueprint and every licence gate - with a MagicMock
database manager and the mode globals (`cmdb.__MODE__`, `__CLOUD_MODE__`, `__LOCAL_MODE__`) monkeypatched, so
each config profile and each startup branch is exercised without a MongoDB; the factory builds as often as a
test needs, beside the session app. The startup orchestrators are called directly with `SystemConfigReader`,
`CollectionValidator`, `DatabaseUpdater` and `get_db_names_from_service_portal` patched at the module path.

The registration census is the important part: it runs the real `register_blueprints` against a recording app
and asserts that every blueprint defined under the routes package is registered, once, at its prefix, and that
every licensed group is gated behind its feature before it is registered. A blueprint that is defined but never
mounted fails silently - the feature is simply absent from the URL map with no error anywhere - which has
happened in this codebase before, so the parity is pinned rather than trusted.
"""
import importlib
import logging
import pkgutil
from http import HTTPStatus
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, call, patch

import pytest
from werkzeug.exceptions import HTTPException, MethodNotAllowed, NotFound

from flask import Blueprint
from pymongo.errors import ServerSelectionTimeoutError

import cmdb
from cmdb.errors.database import (
    DatabaseConnectionError,
    DocumentInsertError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
)
from cmdb.errors.updater import TenantUpdatesFailedError, UpdaterException
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.responses.error_handlers import DATABASE_LOCKED_MSG, DATABASE_UNAVAILABLE_MSG
from cmdb.interface.custom_converters import RegexConverter
from cmdb.interface.rest_api import routes as routes_package
from cmdb.interface.rest_api.routes.config_routes.config_file_routes import config_file_blueprint
from cmdb.interface.rest_api.routes.connection import connection_routes
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_routes import (
    docapi_blueprint,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_routes import objects_blueprint
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_routes import types_blueprint
from cmdb.interface.rest_api.routes.framework_routes.search_routes import search_blueprint
from cmdb.interface.rest_api.routes.framework_routes.special_routes import special_blueprint
from cmdb.interface.rest_api.routes.ipam_routes.ipam_subnet_routes import ipam_subnet_blueprint
from cmdb.interface.rest_api.routes.isms_routes import risk_blueprint
from cmdb.interface.rest_api.routes.media_library_routes.media_file_routes import media_file_blueprint
from cmdb.interface.rest_api.routes.open_celium_routes import oc_licenses_blueprint
from cmdb.interface.rest_api.routes.relation_routes.object_relation_logs_routes import object_relation_logs_blueprint
from cmdb.interface.rest_api.routes.relation_routes.object_relation_routes import object_relations_blueprint
from cmdb.interface.rest_api.routes.relation_routes.relations_routes import relations_blueprint
from cmdb.interface.rest_api.routes.setup_routes.setup_routes import setup_blueprint
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import GATED_FEATURE_ATTR
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.init_rest_api import (
    bring_database_up_to_date,
    create_rest_api,
    _register_gated,
    execute_update_checks,
    is_database_outage,
    register_blueprints,
    register_converters,
    register_error_pages,
    start_datagerry_setup,
    update_tenant_database,
)
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.rest_api.init_rest_api'
SOURCE_FILE: Path = Path(__file__).resolve().parents[4] / 'cmdb' / 'interface' / 'rest_api' / 'init_rest_api.py'

DB_NAME: str = 'cmdb-unit'
TENANT_DBS: list[str] = ['tenant-a', 'tenant-b']
BROKEN_TENANT: str = TENANT_DBS[0]
HEALTHY_TENANT: str = TENANT_DBS[1]

# The statuses the route layer actually aborts (`grep -c "abort(<code>"` across cmdb/), so the
# envelope is proved for every one the API really emits
RAISED_STATUS_CODES: tuple[int, ...] = (400, 401, 403, 404, 405, 500, 503)

# Statuses NOTHING in cmdb/ aborts. 415 is the one reachable in practice, because Werkzeug raises it
# while parsing a request - before any route runs, and therefore out of reach of any abort() census
UNRAISED_STATUS_CODES: tuple[int, ...] = (409, 413, 415, 422, 423, 429, 451, 501, 502)


@pytest.fixture(autouse=True, name='isolated_mode_flags')
def fixture_isolated_mode_flags(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Restores the process-wide mode globals around each test."""
    monkeypatch.setattr(cmdb, '__MODE__', 'TESTING', raising=False)
    monkeypatch.setattr(cmdb, '__CLOUD_MODE__', False, raising=False)
    monkeypatch.setattr(cmdb, '__LOCAL_MODE__', False, raising=False)

    yield


def _build(monkeypatch: pytest.MonkeyPatch, mode: str, cloud: bool = False, local: bool = False) -> Any:
    """
    Builds the real app - every blueprint, every gate - in the given mode, with both startup routines patched out

    The blueprints are module-level singletons every app in the process registers; `gate_blueprint` leaves a
    blueprint already gated behind the same feature as it is, so this builds as often as a test needs
    """
    monkeypatch.setattr(cmdb, '__MODE__', mode, raising=False)
    monkeypatch.setattr(cmdb, '__CLOUD_MODE__', cloud, raising=False)
    monkeypatch.setattr(cmdb, '__LOCAL_MODE__', local, raising=False)

    with patch(f'{MODULE_PATH}.start_datagerry_setup') as mock_setup, \
         patch(f'{MODULE_PATH}.execute_update_checks') as mock_checks:
        app = create_rest_api(MagicMock())

    return app, mock_setup, mock_checks


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  create_rest_api                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_returns_a_configured_app_bound_to_the_database_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """The factory hands back a BaseCmdbApp carrying the given manager and strict slashes"""
    monkeypatch.setattr(cmdb, '__MODE__', 'TESTING', raising=False)

    manager = MagicMock()
    app = create_rest_api(manager)

    assert isinstance(app, BaseCmdbApp)
    assert app.database_manager is manager
    assert app.url_map.strict_slashes is True


@pytest.mark.parametrize('mode, expected_debug, expected_testing', [
    ('DEBUG', True, False),
    ('TESTING', True, True),   # TestingConfig sets both so the test client sees real tracebacks
    ('PRODUCTION', False, False),
])
def test_each_mode_selects_its_config_profile(
    monkeypatch: pytest.MonkeyPatch, mode: str, expected_debug: bool, expected_testing: bool,
) -> None:
    """DEBUG / TESTING / anything else each load their own Flask config object"""
    app, _setup, _checks = _build(monkeypatch, mode)

    assert app.config['DEBUG'] is expected_debug
    assert app.config['TESTING'] is expected_testing


def test_testing_mode_runs_no_startup_routine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under TESTING neither the on-prem setup nor the update checks are executed"""
    _app, mock_setup, mock_checks = _build(monkeypatch, 'TESTING')

    mock_setup.assert_not_called()
    mock_checks.assert_not_called()


def test_on_premise_mode_runs_the_setup_routine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not cloud mode -> the single-database on-prem setup runs"""
    _app, mock_setup, mock_checks = _build(monkeypatch, 'PRODUCTION', cloud=False)

    mock_setup.assert_called_once()
    mock_checks.assert_not_called()


def test_cloud_mode_runs_the_tenant_update_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloud mode without local mode -> the multi-tenant update checks run against the portal list"""
    _app, mock_setup, mock_checks = _build(monkeypatch, 'PRODUCTION', cloud=True, local=False)

    mock_setup.assert_not_called()
    mock_checks.assert_called_once()
    assert mock_checks.call_args.kwargs == {}


def test_local_mode_runs_the_update_checks_with_the_local_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloud + local mode -> the same checks, but against the local-mode database list"""
    _app, mock_setup, mock_checks = _build(monkeypatch, 'PRODUCTION', cloud=True, local=True)

    mock_setup.assert_not_called()
    mock_checks.assert_called_once_with(mock_checks.call_args.args[0], local_mode=True)


@pytest.mark.parametrize('header', ['X-API-Version', 'X-Total-Count', 'Content-Disposition'])
def test_the_api_exposes_the_headers_a_cross_origin_frontend_reads(
    monkeypatch: pytest.MonkeyPatch, header: str,
) -> None:
    """
    A browser can only read a response header the server exposes

    `Content-Disposition` is the one that matters in practice: it carries the filename every export
    route builds, and the Angular app runs on its own origin under `ng serve`, so without it the
    frontend reads no name and falls back to inventing one.
    """
    app, _setup, _checks = _build(monkeypatch, 'TESTING')

    @app.route('/cors-probe')
    def _probe() -> str:
        return 'ok'

    response = app.test_client().get('/cors-probe', headers={'Origin': 'http://localhost:4200'})
    exposed = [value.strip() for value in response.headers['Access-Control-Expose-Headers'].split(',')]

    assert header in exposed


@pytest.mark.parametrize('local', [False, True])
def test_cloud_mode_keeps_the_failed_tenants_on_the_app(monkeypatch: pytest.MonkeyPatch, local: bool) -> None:
    """The tenants the update checks report as failed become the app's unavailable tenants"""
    monkeypatch.setattr(cmdb, '__MODE__', 'PRODUCTION', raising=False)
    monkeypatch.setattr(cmdb, '__CLOUD_MODE__', True, raising=False)
    monkeypatch.setattr(cmdb, '__LOCAL_MODE__', local, raising=False)
    failed = frozenset({BROKEN_TENANT})

    with patch(f'{MODULE_PATH}.execute_update_checks', return_value=failed):
        app = create_rest_api(MagicMock())

    assert app.unavailable_tenants == failed


def test_an_app_starts_with_no_unavailable_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the cloud update checks (TESTING, on premise) no tenant is fenced off"""
    app, _setup, _checks = _build(monkeypatch, 'TESTING')

    assert app.unavailable_tenants == frozenset()


def test_every_tenant_failing_exits_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no tenant could be brought up to date the API does not start at all"""
    monkeypatch.setattr(cmdb, '__MODE__', 'PRODUCTION', raising=False)
    monkeypatch.setattr(cmdb, '__CLOUD_MODE__', True, raising=False)
    monkeypatch.setattr(cmdb, '__LOCAL_MODE__', False, raising=False)

    with patch(f'{MODULE_PATH}.execute_update_checks', side_effect=TenantUpdatesFailedError('all failed')):
        with pytest.raises(SystemExit) as exc_info:
            create_rest_api(MagicMock())

    assert exc_info.value.code == 1


def test_a_failing_startup_routine_exits_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """A startup failure is fatal: the process exits 1 rather than serving a half-built API"""
    monkeypatch.setattr(cmdb, '__MODE__', 'PRODUCTION', raising=False)
    monkeypatch.setattr(cmdb, '__CLOUD_MODE__', False, raising=False)

    with patch(f'{MODULE_PATH}.start_datagerry_setup', side_effect=RuntimeError('boom')):
        with pytest.raises(SystemExit) as exc_info:
            create_rest_api(MagicMock())

    assert exc_info.value.code == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                                register_converters                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_register_converters_adds_the_regex_converter() -> None:
    """Routes can use <regex(...):param> after registration"""
    app = BaseCmdbApp(__name__, database_manager=MagicMock())

    register_converters(app)

    assert app.url_map.converters['regex'] is RegexConverter


def test_a_registered_regex_rule_matches_through_the_converter() -> None:
    """
    The converter is only ever constructed by Werkzeug building a rule that uses it

    No route declares a `<regex(...)>` parameter today, which is why this whole path had no coverage -
    and why nobody noticed the converter could not be constructed at all: `__init__` accepted
    `url_map` alone while Werkzeug passes the rule's arguments after it, so the first route to use one
    would have raised TypeError while the URL map was built.
    """
    app = BaseCmdbApp(__name__, database_manager=MagicMock())
    register_converters(app)
    app.add_url_rule('/probe/<regex("[0-9]{4}"):code>', 'probe', lambda code: code)

    adapter = app.url_map.bind('localhost')

    assert adapter.match('/probe/2026')[1] == {'code': '2026'}

    with pytest.raises(NotFound):
        adapter.match('/probe/not-four-digits')


def test_a_regex_rule_without_a_pattern_matches_one_segment() -> None:
    """`<regex:name>` falls back to the default converter's rule instead of failing to build."""
    app = BaseCmdbApp(__name__, database_manager=MagicMock())
    register_converters(app)
    app.add_url_rule('/plain/<regex:anything>', 'plain', lambda anything: anything)

    adapter = app.url_map.bind('localhost')

    assert adapter.match('/plain/whatever')[1] == {'anything': 'whatever'}

    with pytest.raises(NotFound):
        adapter.match('/plain/two/segments')



# -------------------------------------------------------------------------------------------------------------------- #
#                                                register_error_pages                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('status', RAISED_STATUS_CODES + UNRAISED_STATUS_CODES)
def test_every_status_answers_with_the_json_envelope(status: int) -> None:
    """
    Any status, not a whitelist of nine

    One handler is registered for the `HTTPException` class, so the second half of this
    parametrisation - the statuses nothing aborts today - is the point: without the catch-all each answers
    Flask's HTML page, and a client that reads `message` off the envelope got nothing.
    """
    app = BaseCmdbApp(__name__, database_manager=MagicMock())
    register_error_pages(app)

    @app.route('/boom')
    def _boom() -> None:
        from flask import abort  # pylint: disable=import-outside-toplevel
        abort(status, 'boom')

    response = app.test_client().get('/boom')

    assert response.status_code == status
    assert response.mimetype == 'application/json'
    assert set(response.get_json()) == {'description', 'message', 'response', 'status'}
    assert response.get_json()['status'] == status


@pytest.mark.parametrize(
    'status', [code for code in RAISED_STATUS_CODES + UNRAISED_STATUS_CODES if code != 405],
)
def test_the_abort_message_reaches_the_client(status: int) -> None:
    """The text passed to abort() is what the frontend reads out of 'message'"""
    app = BaseCmdbApp(__name__, database_manager=MagicMock())
    register_error_pages(app)

    @app.route('/boom')
    def _boom() -> None:
        from flask import abort  # pylint: disable=import-outside-toplevel
        abort(status, 'boom')

    assert app.test_client().get('/boom').get_json()['message'] == 'boom'


@pytest.mark.parametrize('error, status, message', [
    (DocumentNetworkError('connection lost'), HTTPStatus.SERVICE_UNAVAILABLE, DATABASE_UNAVAILABLE_MSG),
    (DocumentLockTimeoutError('lock timeout'), HTTPStatus.LOCKED, DATABASE_LOCKED_MSG),
], ids=['network -> 503', 'lock -> 423'])
def test_a_transient_database_error_answers_its_own_status(error: Exception, status: int, message: str,
                                                           caplog: pytest.LogCaptureFixture) -> None:
    """Registered for the app, so ANY route that lets it escape answers 'try again' in the envelope - and logs it"""
    app = BaseCmdbApp(__name__, database_manager=MagicMock())
    register_error_pages(app)

    @app.route('/boom')
    def _boom() -> None:
        raise error

    with caplog.at_level(logging.ERROR):
        response = app.test_client().get('/boom')

    assert response.status_code == status
    assert response.mimetype == 'application/json'
    assert set(response.get_json()) == {'description', 'message', 'response', 'status'}
    assert response.get_json()['message'] == message
    assert any(record.exc_info and record.exc_info[1] is error for record in caplog.records)


def test_a_subclass_of_neither_is_still_a_500() -> None:
    """Only the two transient errors are mapped: any other database error stays the generic server fault"""
    app = BaseCmdbApp(__name__, database_manager=MagicMock())
    register_error_pages(app)

    @app.route('/boom')
    def _boom() -> None:
        raise DocumentInsertError('refused')

    response = app.test_client().get('/boom')

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.get_json()['message'] not in (DATABASE_UNAVAILABLE_MSG, DATABASE_LOCKED_MSG)


def test_a_405_abort_message_is_dropped_by_werkzeug() -> None:
    """
    405 is the exception: `abort(405, "text")` passes the text as MethodNotAllowed's FIRST positional
    argument, which is `valid_methods`, so the custom message never becomes a description - the client
    gets an empty 'message' and only the generic 'description'. `search_routes.py:128` is the one
    caller in the codebase that hits this
    """
    app = BaseCmdbApp(__name__, database_manager=MagicMock())
    register_error_pages(app)

    @app.route('/boom')
    def _boom() -> None:
        from flask import abort  # pylint: disable=import-outside-toplevel
        abort(405, 'this text never reaches the client')

    body: dict[str, Any] = app.test_client().get('/boom').get_json()

    assert body['message'] == ''
    assert body['description'] == MethodNotAllowed.description


def test_an_unhandled_non_http_exception_still_answers_the_envelope() -> None:
    """
    A class handler for `HTTPException` covers a plain `ValueError` too

    Flask converts an unhandled exception to `InternalServerError` before looking for a handler, and
    that is an `HTTPException` - so the catch-all replaces the old explicit 500 registration rather
    than losing it. Worth pinning, because it is the one case where "register the class" could
    plausibly have left a hole.
    """
    app = BaseCmdbApp(__name__, database_manager=MagicMock())
    register_error_pages(app)

    @app.route('/boom')
    def _boom() -> None:
        raise ValueError('not an HTTPException')

    response = app.test_client().get('/boom')

    assert response.status_code == 500
    assert response.mimetype == 'application/json'
    assert set(response.get_json()) == {'description', 'message', 'response', 'status'}


def test_one_handler_is_registered_for_the_whole_family() -> None:
    """
    The shape of the fix, not just its effect

    Nine per-status registrations became one, so a future status needs no registration at all. A
    change that re-introduces per-code handlers fails here even if the responses still look right. Beside it,
    by exception class: the two transient database errors, which have statuses of their own (503 / 423).
    """
    app = BaseCmdbApp(__name__, database_manager=MagicMock())
    register_error_pages(app)

    by_code = app.error_handler_spec[None]
    handlers = by_code[None]

    assert set(handlers) == {HTTPException, DocumentNetworkError, DocumentLockTimeoutError}
    assert list(by_code) == [None]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                register_blueprints                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
GATE_EVENT: str = 'gate'
REGISTER_EVENT: str = 'register'

#: Every licensed group: the prefixes it is mounted under and the feature each of its blueprints is gated behind
LICENSED_PREFIXES: dict[str, LicenseFeature] = {
    '/isms/': LicenseFeature.ISMS,
    '/object_groups': LicenseFeature.ISMS,
    '/persons': LicenseFeature.ISMS,
    '/person_groups': LicenseFeature.ISMS,
    '/ipam/': LicenseFeature.IPAM,
    '/racks': LicenseFeature.IPAM,
    '/ports': LicenseFeature.IPAM,
    '/port_connections': LicenseFeature.IPAM,
    '/open_celium': LicenseFeature.AUTOMATIONS,
}


class _RecordingApp:
    """Stands in for the Flask app: records each registration instead of mounting it."""

    def __init__(self, events: list[tuple[str, str, Any]]) -> None:
        self.events = events

    def register_blueprint(self, blueprint: Blueprint, url_prefix: str | None = None) -> None:
        """Records the blueprint's name and prefix."""
        self.events.append((REGISTER_EVENT, blueprint.name, url_prefix))


def _record_registration(monkeypatch: pytest.MonkeyPatch, cloud: bool) -> list[tuple[str, str, Any]]:
    """
    Runs the real register_blueprints against a recording app, in order: every gate and every registration

    `gate_blueprint` is recorded rather than run, so the order of every gate against its registration is visible -
    a built app shows only the result
    """
    monkeypatch.setattr(cmdb, '__CLOUD_MODE__', cloud, raising=False)
    events: list[tuple[str, str, Any]] = []

    def _gate(blueprint: Blueprint, feature: LicenseFeature) -> None:
        events.append((GATE_EVENT, blueprint.name, feature))

    with patch(f'{MODULE_PATH}.gate_blueprint', side_effect=_gate):
        register_blueprints(_RecordingApp(events))

    return events


def _mounts(events: list[tuple[str, str, Any]]) -> list[tuple[str, str | None]]:
    """The registrations of a recording, in order, as (blueprint name, prefix)."""
    return [(name, prefix) for kind, name, prefix in events if kind == REGISTER_EVENT]


def _gates(events: list[tuple[str, str, Any]]) -> dict[str, LicenseFeature]:
    """The gates of a recording, as blueprint name -> feature."""
    return {name: feature for kind, name, feature in events if kind == GATE_EVENT}


def _route_blueprints() -> dict[str, str]:
    """Every Blueprint instance under the routes package, as name -> the module it was created in (import_name)."""
    found: dict[str, str] = {}

    for module_info in pkgutil.walk_packages(routes_package.__path__, f'{routes_package.__name__}.'):
        module = importlib.import_module(module_info.name)

        for value in vars(module).values():
            if isinstance(value, Blueprint):
                found.setdefault(value.name, value.import_name)

    return found


def test_every_blueprint_under_the_routes_package_is_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blueprint defined but never mounted is invisible - no error, just a missing feature"""
    registered = {name for name, _prefix in _mounts(_record_registration(monkeypatch, cloud=True))}

    assert registered == set(_route_blueprints())


def test_the_census_finds_the_route_blueprints() -> None:
    """The discovery itself is not vacuous: it finds blueprints of every domain, under their own names"""
    found = _route_blueprints()

    assert {objects_blueprint.name, risk_blueprint.name, ipam_subnet_blueprint.name, setup_blueprint.name} <= set(found)


def test_no_blueprint_is_registered_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    """A duplicate registration would shadow routes depending on prefix order"""
    names = [name for name, _prefix in _mounts(_record_registration(monkeypatch, cloud=True))]

    assert len(names) == len(set(names))


@pytest.mark.parametrize('blueprint, prefix', [
    (objects_blueprint, '/objects'),
    (types_blueprint, '/types'),
    (search_blueprint, '/search'),
    (docapi_blueprint, '/docapi'),
    (media_file_blueprint, '/media_file'),
    (special_blueprint, '/special'),
    (ipam_subnet_blueprint, '/ipam/subnet'),
    (risk_blueprint, '/isms/risks'),
    (relations_blueprint, '/relations'),
    (object_relations_blueprint, '/object_relations'),
    (object_relation_logs_blueprint, '/object_relation_logs'),
], ids=lambda value: getattr(value, 'name', value))
def test_known_mount_points_are_declared_at_the_registration_site(
    monkeypatch: pytest.MonkeyPatch, blueprint: Blueprint, prefix: str,
) -> None:
    """
    Prefixes the frontend depends on are passed at registration, not only inside the route module

    Includes the four blueprints that ALSO set url_prefix on their own APIBlueprint(...) constructor
    (search / docapi / media_file / special) - the value passed here is identical and wins, so the
    registration stays the single source of truth for the URL map
    """
    assert (blueprint.name, prefix) in _mounts(_record_registration(monkeypatch, cloud=False))


def test_the_object_relation_log_routes_live_with_the_entity_they_record() -> None:
    """
    The route package holds the entity it serves - the log routes with the relations they record

    A top-level `log_routes` package holding that one module would read as the home of every log route
    while the OBJECT logs sit elsewhere
    """
    assert _route_blueprints()[object_relation_logs_blueprint.name] == (
        'cmdb.interface.rest_api.routes.relation_routes.object_relation_logs_routes'
    )


def test_the_setup_blueprint_is_registered_only_in_cloud_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The registration IS the guard for the Service-Portal teardown routes

    Those three routes carry no `insert_request_user` and no `.protect`; their only decorator is
    `verify_api_access`, which returns immediately outside cloud mode. Registering them on-premise
    therefore published an unauthenticated `DELETE /setup/subscriptions?database=<name>` that drops
    any database on the cluster
    """
    on_premise = _mounts(_record_registration(monkeypatch, cloud=False))
    cloud = _mounts(_record_registration(monkeypatch, cloud=True))

    assert (setup_blueprint.name, '/setup') in cloud
    assert setup_blueprint.name not in {name for name, _prefix in on_premise}


def test_no_other_blueprint_registration_depends_on_the_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The setup surface is the only one whose availability depends on the mode

    Everything else is mounted in every mode and gated per route, so a second difference here would be a
    new rule that wants its own reason
    """
    on_premise = _mounts(_record_registration(monkeypatch, cloud=False))
    cloud = _mounts(_record_registration(monkeypatch, cloud=True))

    assert [mount for mount in cloud if mount[0] != setup_blueprint.name] == on_premise


def test_connection_routes_is_the_only_prefixless_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything except the /rest root probe declares where it mounts"""
    mounts = _mounts(_record_registration(monkeypatch, cloud=True))

    assert [name for name, prefix in mounts if prefix is None] == [connection_routes.name]


def test_every_blueprint_under_a_licensed_prefix_is_gated_with_its_feature(monkeypatch: pytest.MonkeyPatch) -> None:
    """A licensed group cannot be mounted without its gate - only the two named exceptions are"""
    events = _record_registration(monkeypatch, cloud=False)
    gates = _gates(events)
    ungated_by_design = {oc_licenses_blueprint.name}

    for name, prefix in _mounts(events):
        feature = next((f for p, f in LICENSED_PREFIXES.items() if prefix and prefix.startswith(p)), None)

        if feature is None or name in ungated_by_design:
            assert name not in gates, f'{name} is gated but mounted outside every licensed prefix'
        else:
            assert gates.get(name) == feature, f'{name} at {prefix} is not gated behind {feature}'


def test_every_licensed_prefix_has_gated_blueprints(monkeypatch: pytest.MonkeyPatch) -> None:
    """The prefix table is not vacuous: every licensed prefix mounts at least one gated blueprint"""
    events = _record_registration(monkeypatch, cloud=False)
    gates = _gates(events)

    for prefix in LICENSED_PREFIXES:
        assert any(name in gates and mount.startswith(prefix) for name, mount in _mounts(events) if mount), prefix


def test_the_config_file_and_open_celium_licence_routes_stay_ungated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both carry the licence per route (or none at all) - a blueprint gate would lock them wholesale"""
    gates = _gates(_record_registration(monkeypatch, cloud=False))

    assert config_file_blueprint.name not in gates
    assert oc_licenses_blueprint.name not in gates


def test_every_gate_is_attached_before_its_blueprint_is_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flask refuses a before_request hook on a registered blueprint, so the order is load-bearing"""
    events = _record_registration(monkeypatch, cloud=False)
    position = {(kind, name): index for index, (kind, name, _value) in enumerate(events)}

    for name in _gates(events):
        assert position[(GATE_EVENT, name)] < position[(REGISTER_EVENT, name)], name


def test_register_gated_gates_then_registers_each_blueprint_in_order() -> None:
    """One list drives both steps, and each blueprint is gated right before it is mounted"""
    first, second = Blueprint('first_gated', __name__), Blueprint('second_gated', __name__)
    events: list[tuple[str, str, Any]] = []

    def _gate(blueprint: Blueprint, feature: LicenseFeature) -> None:
        events.append((GATE_EVENT, blueprint.name, feature))

    with patch(f'{MODULE_PATH}.gate_blueprint', side_effect=_gate):
        _register_gated(_RecordingApp(events), LicenseFeature.ISMS, ((first, '/a'), (second, '/b')))

    assert events == [
        (GATE_EVENT, 'first_gated', LicenseFeature.ISMS),
        (REGISTER_EVENT, 'first_gated', '/a'),
        (GATE_EVENT, 'second_gated', LicenseFeature.ISMS),
        (REGISTER_EVENT, 'second_gated', '/b'),
    ]


def _gated_blueprints(app: BaseCmdbApp) -> dict[str, list[LicenseFeature]]:
    """Every gated blueprint of a built app, with the features its gate hooks record."""
    return {
        name: [getattr(hook, GATED_FEATURE_ATTR) for hook in hooks if hasattr(hook, GATED_FEATURE_ATTR)]
        for name, hooks in app.before_request_funcs.items()
        if name and any(hasattr(hook, GATED_FEATURE_ATTR) for hook in hooks)
    }


def test_the_factory_builds_more_than_one_app_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    A second and a third build carry the same URL map and the same gates as the first

    The gates are attached to module-level blueprints once; Flask replays them onto every app that registers
    the blueprint, so each app carries exactly one gate hook per gated blueprint - never one per build
    """
    first, _setup, _checks = _build(monkeypatch, 'TESTING')
    second, _setup, _checks = _build(monkeypatch, 'TESTING')
    third, _setup, _checks = _build(monkeypatch, 'TESTING')

    rules = [sorted((rule.rule, rule.endpoint) for rule in app.url_map.iter_rules()) for app in (first, second, third)]

    assert rules[0] == rules[1] == rules[2]
    assert _gated_blueprints(first) == _gated_blueprints(second) == _gated_blueprints(third)
    assert all(len(features) == 1 for features in _gated_blueprints(third).values())


def test_a_built_app_gates_every_licensed_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real build - not a recording - carries each licensed group's gates"""
    app, _setup, _checks = _build(monkeypatch, 'TESTING')
    gated = _gated_blueprints(app)

    assert gated[risk_blueprint.name] == [LicenseFeature.ISMS]
    assert gated[ipam_subnet_blueprint.name] == [LicenseFeature.IPAM]
    assert oc_licenses_blueprint.name not in gated
    assert {features[0] for features in gated.values()} == {
        LicenseFeature.ISMS, LicenseFeature.IPAM, LicenseFeature.AUTOMATIONS,
    }


def test_a_cloud_build_beside_an_on_premise_one_adds_only_the_setup_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Building in both modes in one process works, and the only difference is the /setup surface"""
    on_premise, _setup, _checks = _build(monkeypatch, 'TESTING')
    cloud, _setup, _checks = _build(monkeypatch, 'TESTING', cloud=True)

    endpoints = [{rule.endpoint for rule in app.url_map.iter_rules()} for app in (on_premise, cloud)]

    assert {endpoint.rpartition('.')[0] for endpoint in endpoints[1] - endpoints[0]} == {setup_blueprint.name}
    assert endpoints[0] < endpoints[1]


def test_register_blueprints_carries_no_pylint_suppression() -> None:
    """The split into one helper per domain is what keeps the locals / statements limits without a disable"""
    source: str = SOURCE_FILE.read_text(encoding='utf-8')

    assert 'R0914' not in source
    assert 'R0915' not in source


# -------------------------------------------------------------------------------------------------------------------- #
#                                               start_datagerry_setup                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_start_datagerry_setup_validates_then_updates() -> None:
    """The configured database is validated in local mode, then brought up to date"""
    dbm = MagicMock()

    with patch(f'{MODULE_PATH}.SystemConfigReader') as mock_reader, \
         patch(f'{MODULE_PATH}.CollectionValidator') as mock_validator, \
         patch(f'{MODULE_PATH}.DatabaseUpdater') as mock_updater:
        mock_reader.return_value.get_value.return_value = DB_NAME
        mock_updater.return_value.is_update_available.return_value = True

        start_datagerry_setup(dbm)

    mock_reader.return_value.get_value.assert_called_once_with('database_name', 'Database')
    mock_validator.assert_called_once_with(DB_NAME, dbm, local_mode=True)
    mock_validator.return_value.validate_collections.assert_called_once_with()
    mock_updater.assert_called_once_with(dbm, DB_NAME)
    mock_updater.return_value.run_updates.assert_called_once_with()


def test_start_datagerry_setup_skips_updates_when_none_are_pending() -> None:
    """An up-to-date database is validated but not migrated"""
    with patch(f'{MODULE_PATH}.SystemConfigReader'), \
         patch(f'{MODULE_PATH}.CollectionValidator'), \
         patch(f'{MODULE_PATH}.DatabaseUpdater') as mock_updater:
        mock_updater.return_value.is_update_available.return_value = False

        start_datagerry_setup(MagicMock())

    mock_updater.return_value.run_updates.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                             bring_database_up_to_date                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_newly_created_database_is_stamped_and_not_migrated() -> None:
    """
    A database this call creates is already at the current schema, so it is stamped, not replayed

    `CollectionValidator` builds it from the current models, and every registered migration is a
    no-op against it. On-premise this used to replay the whole history: with no stored version,
    `get_current_update_version` seeds BASELINE_UPDATER_VERSION, which sits below the earliest
    migration.
    """
    dbm = MagicMock()
    dbm.check_database_exists.return_value = False

    with patch(f'{MODULE_PATH}.CollectionValidator'), \
         patch(f'{MODULE_PATH}.DatabaseUpdater') as mock_updater:
        mock_updater.return_value.get_highest_update_version.return_value = 20260916

        bring_database_up_to_date(dbm, DB_NAME)

    mock_updater.return_value.set_update_version.assert_called_once_with(20260916)
    mock_updater.return_value.run_updates.assert_not_called()
    mock_updater.return_value.is_update_available.assert_not_called()


def test_an_existing_database_is_migrated_and_not_stamped() -> None:
    """An upgrade must still run every migration it is behind - the stamp is only for a new one."""
    dbm = MagicMock()
    dbm.check_database_exists.return_value = True

    with patch(f'{MODULE_PATH}.CollectionValidator'), \
         patch(f'{MODULE_PATH}.DatabaseUpdater') as mock_updater:
        mock_updater.return_value.is_update_available.return_value = True

        bring_database_up_to_date(dbm, DB_NAME)

    mock_updater.return_value.run_updates.assert_called_once_with()
    mock_updater.return_value.set_update_version.assert_not_called()


def test_an_up_to_date_existing_database_is_left_alone() -> None:
    """Nothing pending, nothing stamped, nothing run."""
    dbm = MagicMock()
    dbm.check_database_exists.return_value = True

    with patch(f'{MODULE_PATH}.CollectionValidator'), \
         patch(f'{MODULE_PATH}.DatabaseUpdater') as mock_updater:
        mock_updater.return_value.is_update_available.return_value = False

        bring_database_up_to_date(dbm, DB_NAME)

    mock_updater.return_value.run_updates.assert_not_called()
    mock_updater.return_value.set_update_version.assert_not_called()


def test_existence_is_read_before_the_collections_are_validated() -> None:
    """
    The ordering IS the rule

    `validate_collections` creates the database when it is missing, so asking afterwards would always
    answer "it exists" and every fresh installation would replay the history again.
    """
    dbm = MagicMock()
    order: list[str] = []
    dbm.check_database_exists.side_effect = lambda *_: order.append('check') or True

    with patch(f'{MODULE_PATH}.CollectionValidator') as mock_validator, \
         patch(f'{MODULE_PATH}.DatabaseUpdater'):
        mock_validator.return_value.validate_collections.side_effect = lambda: order.append('validate')

        bring_database_up_to_date(dbm, DB_NAME)

    assert order == ['check', 'validate']


def test_the_local_mode_flag_reaches_the_validator() -> None:
    """It gates the key generation and the default admin user, so it must not be dropped."""
    dbm = MagicMock()

    with patch(f'{MODULE_PATH}.CollectionValidator') as mock_validator, \
         patch(f'{MODULE_PATH}.DatabaseUpdater'):
        bring_database_up_to_date(dbm, DB_NAME, local_mode=True)

    mock_validator.assert_called_once_with(DB_NAME, dbm, local_mode=True)


def test_both_boot_paths_share_one_rule() -> None:
    """
    The on-premise and tenant paths share the validate-then-migrate sequence

    Duplicated, they disagree about a newly created database. Sharing the helper is
    what keeps them from drifting apart again.
    """
    source: str = SOURCE_FILE.read_text(encoding='utf-8')
    body = source[source.index('def start_datagerry_setup'):]

    assert body.count('bring_database_up_to_date(') == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                                execute_update_checks                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_execute_update_checks_walks_every_tenant_database() -> None:
    """Each database from the service portal is validated and migrated in turn"""
    dbm = MagicMock()

    with patch(f'{MODULE_PATH}.get_db_names_from_service_portal', return_value=TENANT_DBS) as mock_names, \
         patch(f'{MODULE_PATH}.CollectionValidator') as mock_validator, \
         patch(f'{MODULE_PATH}.DatabaseUpdater') as mock_updater:
        mock_updater.return_value.is_update_available.return_value = True

        execute_update_checks(dbm)

    mock_names.assert_called_once_with(False)
    assert mock_validator.call_args_list == [call(name, dbm, local_mode=False) for name in TENANT_DBS]
    assert mock_updater.call_args_list == [call(dbm, name) for name in TENANT_DBS]
    assert mock_updater.return_value.run_updates.call_count == len(TENANT_DBS)


def test_execute_update_checks_forwards_the_local_mode_flag() -> None:
    """Local mode asks the portal for the local database list instead of the cloud one"""
    with patch(f'{MODULE_PATH}.get_db_names_from_service_portal', return_value=[]) as mock_names:
        execute_update_checks(MagicMock(), local_mode=True)

    mock_names.assert_called_once_with(True)


def test_execute_update_checks_skips_up_to_date_tenants() -> None:
    """A tenant already at the highest version is validated but not migrated"""
    with patch(f'{MODULE_PATH}.get_db_names_from_service_portal', return_value=TENANT_DBS), \
         patch(f'{MODULE_PATH}.CollectionValidator'), \
         patch(f'{MODULE_PATH}.DatabaseUpdater') as mock_updater:
        mock_updater.return_value.is_update_available.return_value = False

        execute_update_checks(MagicMock())

    mock_updater.return_value.run_updates.assert_not_called()


def test_execute_update_checks_sets_a_failing_tenant_aside_and_updates_the_rest() -> None:
    """One failing database is reported, and every other one is still validated and migrated"""
    dbm = MagicMock()

    def _validate(db_name: str, *_args: Any, **_kwargs: Any) -> MagicMock:
        validator = MagicMock()
        if db_name == BROKEN_TENANT:
            validator.validate_collections.side_effect = UpdaterException('broken schema')
        return validator

    with patch(f'{MODULE_PATH}.get_db_names_from_service_portal', return_value=TENANT_DBS), \
         patch(f'{MODULE_PATH}.CollectionValidator', side_effect=_validate), \
         patch(f'{MODULE_PATH}.DatabaseUpdater') as mock_updater:
        mock_updater.return_value.is_update_available.return_value = True

        failed = execute_update_checks(dbm)

    assert failed == frozenset({BROKEN_TENANT})
    assert mock_updater.call_args_list == [call(dbm, HEALTHY_TENANT)]
    mock_updater.return_value.run_updates.assert_called_once_with()


def test_execute_update_checks_reports_nothing_when_every_tenant_is_up_to_date() -> None:
    """A clean run returns an empty set"""
    with patch(f'{MODULE_PATH}.get_db_names_from_service_portal', return_value=TENANT_DBS), \
         patch(f'{MODULE_PATH}.update_tenant_database', return_value=True):
        assert execute_update_checks(MagicMock()) == frozenset()


def test_execute_update_checks_raises_when_every_tenant_failed() -> None:
    """Nothing could be served: the typed error names every failed tenant"""
    with patch(f'{MODULE_PATH}.get_db_names_from_service_portal', return_value=TENANT_DBS), \
         patch(f'{MODULE_PATH}.update_tenant_database', return_value=False):
        with pytest.raises(TenantUpdatesFailedError) as exc_info:
            execute_update_checks(MagicMock())

    assert all(name in str(exc_info.value) for name in TENANT_DBS)


def test_execute_update_checks_with_no_tenant_reports_nothing() -> None:
    """An empty portal list is not "every tenant failed" - there is simply nothing to update"""
    with patch(f'{MODULE_PATH}.get_db_names_from_service_portal', return_value=[]):
        assert execute_update_checks(MagicMock()) == frozenset()


def test_execute_update_checks_lets_a_portal_failure_through() -> None:
    """Without the tenant list nothing is known to be up to date: the lookup's error is not caught"""
    with patch(f'{MODULE_PATH}.get_db_names_from_service_portal', side_effect=RuntimeError('portal down')), \
         patch(f'{MODULE_PATH}.update_tenant_database') as mock_update:
        with pytest.raises(RuntimeError):
            execute_update_checks(MagicMock())

    mock_update.assert_not_called()


def test_execute_update_checks_stops_at_a_database_outage() -> None:
    """An unreachable server stops the loop at the tenant it struck - the rest are not attempted"""
    outage = DatabaseConnectionError('server unreachable')

    with patch(f'{MODULE_PATH}.get_db_names_from_service_portal', return_value=TENANT_DBS), \
         patch(f'{MODULE_PATH}.bring_database_up_to_date', side_effect=outage) as mock_bring:
        with pytest.raises(DatabaseConnectionError):
            execute_update_checks(MagicMock())

    assert mock_bring.call_count == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                               update_tenant_database                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_update_tenant_database_reports_success() -> None:
    """A tenant brought up to date answers True"""
    dbm = MagicMock()

    with patch(f'{MODULE_PATH}.bring_database_up_to_date') as mock_bring:
        assert update_tenant_database(dbm, HEALTHY_TENANT) is True

    mock_bring.assert_called_once_with(dbm, HEALTHY_TENANT)


def test_update_tenant_database_logs_a_tenant_failure_by_name(caplog: pytest.LogCaptureFixture) -> None:
    """A tenant's own failure is logged with its name and traceback and answered False"""
    with patch(f'{MODULE_PATH}.bring_database_up_to_date', side_effect=UpdaterException('broken schema')), \
         caplog.at_level(logging.ERROR, logger=MODULE_PATH):
        assert update_tenant_database(MagicMock(), BROKEN_TENANT) is False

    record = caplog.records[-1]
    assert BROKEN_TENANT in record.getMessage()
    assert record.exc_info is not None


def test_update_tenant_database_re_raises_an_outage_naming_the_tenant(caplog: pytest.LogCaptureFixture) -> None:
    """An outage is not the tenant's failure: it is logged with the tenant it struck and raised"""
    outage = ServerSelectionTimeoutError('no servers')

    with patch(f'{MODULE_PATH}.bring_database_up_to_date', side_effect=outage), \
         caplog.at_level(logging.ERROR, logger=MODULE_PATH):
        with pytest.raises(ServerSelectionTimeoutError):
            update_tenant_database(MagicMock(), BROKEN_TENANT)

    assert BROKEN_TENANT in caplog.records[-1].getMessage()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 is_database_outage                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def _wrapped(inner: Exception) -> Exception:
    """Wraps an error the way every layer does (raise ... from err) and returns the outer one."""
    outer = UpdaterException(inner)
    outer.__cause__ = inner

    return outer


@pytest.mark.parametrize('err', [
    ServerSelectionTimeoutError('no servers'),
    DatabaseConnectionError('lost'),
    DocumentNetworkError('timed out'),
], ids=['driver', 'connection', 'network'])
def test_is_database_outage_finds_an_outage_however_deeply_wrapped(err: Exception) -> None:
    """The error itself and a wrapped one both count"""
    assert is_database_outage(err) is True
    assert is_database_outage(_wrapped(err)) is True


@pytest.mark.parametrize('err', [
    UpdaterException('broken schema'),
    DocumentInsertError('duplicate'),
    DocumentLockTimeoutError('locked'),
], ids=['updater', 'insert', 'lock'])
def test_is_database_outage_leaves_a_tenant_failure_alone(err: Exception) -> None:
    """A failure of one database - even a transient lock - is the tenant's, not the server's"""
    assert is_database_outage(err) is False
    assert is_database_outage(_wrapped(err)) is False
