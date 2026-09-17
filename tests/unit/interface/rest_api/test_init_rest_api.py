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

DB-free. `create_rest_api` is driven with a MagicMock database manager and the mode globals
(`cmdb.__MODE__`, `__CLOUD_MODE__`, `__LOCAL_MODE__`) monkeypatched, so each config profile and each
startup branch is exercised without a MongoDB. The two startup orchestrators are called directly with
`SystemConfigReader`, `CollectionValidator`, `DatabaseUpdater` and `get_db_names_from_service_portal`
patched at the module path.

The blueprint-registration test is the important one: it asserts that every blueprint imported by
`register_blueprints` is actually registered, and that none is registered twice. A blueprint that is
imported but never mounted fails silently - the feature is simply absent from the URL map with no
error anywhere - which has happened in this codebase before, so the parity is pinned rather than
trusted.
"""
import re
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, call, patch

import pytest
from werkzeug.exceptions import HTTPException, MethodNotAllowed, NotFound

import cmdb
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.custom_converters import RegexConverter
from cmdb.interface.rest_api.init_rest_api import (
    bring_database_up_to_date,
    create_rest_api,
    execute_update_checks,
    register_converters,
    register_error_pages,
    start_datagerry_setup,
)
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.rest_api.init_rest_api'
SOURCE_FILE: Path = Path(__file__).resolve().parents[4] / 'cmdb' / 'interface' / 'rest_api' / 'init_rest_api.py'

DB_NAME: str = 'cmdb-unit'
TENANT_DBS: list[str] = ['tenant-a', 'tenant-b']

# The statuses the route layer actually aborts (`grep -c "abort(<code>"` across cmdb/), so the
# envelope is proved for every one the API really emits
RAISED_STATUS_CODES: tuple[int, ...] = (400, 401, 403, 404, 405, 500, 503)

# Statuses NOTHING in cmdb/ aborts. Each used to answer Flask's HTML page; 415 is the one that was
# reachable in practice, because Werkzeug raises it while parsing a request - before any route runs,
# and therefore out of reach of any abort() census (tier 2 T135)
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
    Builds the app in the given mode with both startup routines patched out

    Blueprint registration is patched out too: the blueprints are module-level singletons and
    `gate_blueprint` attaches `before_request` hooks to them, which Flask refuses once a blueprint has
    been registered - so an app carrying the real blueprints can only be built ONCE per process (see
    discussion-backlog #159). The registration itself is covered separately by the fixture below.
    """
    monkeypatch.setattr(cmdb, '__MODE__', mode, raising=False)
    monkeypatch.setattr(cmdb, '__CLOUD_MODE__', cloud, raising=False)
    monkeypatch.setattr(cmdb, '__LOCAL_MODE__', local, raising=False)

    with patch(f'{MODULE_PATH}.register_blueprints'), \
         patch(f'{MODULE_PATH}.start_datagerry_setup') as mock_setup, \
         patch(f'{MODULE_PATH}.execute_update_checks') as mock_checks:
        app = create_rest_api(MagicMock())

    return app, mock_setup, mock_checks


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  create_rest_api                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_returns_a_configured_app_bound_to_the_database_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """The factory hands back a BaseCmdbApp carrying the given manager and strict slashes"""
    monkeypatch.setattr(cmdb, '__MODE__', 'TESTING', raising=False)

    with patch(f'{MODULE_PATH}.register_blueprints'):
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


def test_a_failing_startup_routine_exits_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """A startup failure is fatal: the process exits 1 rather than serving a half-built API"""
    monkeypatch.setattr(cmdb, '__MODE__', 'PRODUCTION', raising=False)
    monkeypatch.setattr(cmdb, '__CLOUD_MODE__', False, raising=False)

    with patch(f'{MODULE_PATH}.register_blueprints'), \
         patch(f'{MODULE_PATH}.start_datagerry_setup', side_effect=RuntimeError('boom')):
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
    parametrisation - the statuses nothing aborts today - is the point: each of them used to answer
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
    change that re-introduces per-code handlers fails here even if the responses still look right.
    """
    app = BaseCmdbApp(__name__, database_manager=MagicMock())
    register_error_pages(app)

    handlers = app.error_handler_spec[None][None]

    assert list(handlers) == [HTTPException]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                register_blueprints                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def _registration_source() -> str:
    """Returns the body of register_blueprints as text."""
    source: str = SOURCE_FILE.read_text(encoding='utf-8')

    return source[source.index('def register_blueprints'):source.index('def register_error_pages')]


def _imported_blueprint_names(body: str) -> set[str]:
    """Collects every blueprint name imported inside register_blueprints."""
    names: set[str] = set()

    for match in re.finditer(r'^\s+from [\w.]+ import \(([^)]*)\)', body, re.M):
        names |= {part.strip().rstrip(',') for part in match.group(1).split('\n') if part.strip().rstrip(',')}

    for match in re.finditer(r'^\s+from [\w.]+ import ([\w, ]+)$', body, re.M):
        names |= {part.strip() for part in match.group(1).split(',') if part.strip()}

    # 'gate_blueprint' is the licensing guard imported alongside them, not a blueprint itself
    return {
        name for name in names
        if name.endswith(('blueprint', 'blueprints', 'routes')) and name != 'gate_blueprint'
    }


def test_every_imported_blueprint_is_registered() -> None:
    """A blueprint imported but never mounted is invisible - no error, just a missing feature"""
    body = _registration_source()

    assert _imported_blueprint_names(body) - set(re.findall(r'register_blueprint\(\s*(\w+)', body)) == set()


def test_no_blueprint_is_registered_twice() -> None:
    """A duplicate registration would shadow routes depending on prefix order"""
    body = _registration_source()
    registered = re.findall(r'register_blueprint\(\s*(\w+)', body)

    assert len(registered) == len(set(registered))


def test_the_registration_list_covers_every_domain() -> None:
    """A rough floor on the blueprint count, so a whole domain cannot silently drop out"""
    body = _registration_source()

    assert len(re.findall(r'register_blueprint\(\s*(\w+)', body)) > 60


@pytest.mark.parametrize('blueprint, prefix', [
    ('objects_blueprint', '/objects'),
    ('types_blueprint', '/types'),
    ('search_blueprint', '/search'),
    ('docapi_blueprint', '/docapi'),
    ('media_file_blueprint', '/media_file'),
    ('special_blueprint', '/special'),
    ('ipam_subnet_blueprint', '/ipam/subnet'),
    ('risk_blueprint', '/isms/risks'),
])
def test_known_mount_points_are_declared_at_the_registration_site(blueprint: str, prefix: str) -> None:
    """
    Prefixes the frontend depends on are declared here, not only inside the route module

    Includes the four blueprints that ALSO set url_prefix on their own APIBlueprint(...) constructor
    (search / docapi / media_file / special) - the value passed here is identical and wins, so this
    list stays the single source of truth for the URL map
    """
    body = _registration_source()

    assert f"register_blueprint({blueprint}, url_prefix='{prefix}')" in body


def test_the_setup_blueprint_is_registered_only_in_cloud_mode() -> None:
    """
    The registration IS the guard for the Service-Portal teardown routes

    Those three routes carry no `insert_request_user` and no `.protect`; their only decorator is
    `verify_api_access`, which returns immediately outside cloud mode. Registering them on-premise
    therefore published an unauthenticated `DELETE /setup/subscriptions?database=<name>` that drops
    any database on the cluster. Moving the call back out of this guard would republish it, silently.
    """
    body = _registration_source()
    registration = "app.register_blueprint(setup_blueprint, url_prefix='/setup')"

    assert registration in body

    guard_position = body.index('if cmdb.__CLOUD_MODE__:')
    registration_position = body.index(registration)

    assert guard_position < registration_position
    # ...and nothing else slipped in between the guard and the call it guards
    assert body[guard_position:registration_position].strip() == 'if cmdb.__CLOUD_MODE__:'


def test_no_other_blueprint_registration_is_conditional() -> None:
    """
    The setup surface is the only one whose availability depends on the mode

    Everything else is mounted in every mode and gated per route, so a second conditional here would
    be a new rule that wants its own reason.
    """
    body = _registration_source()

    assert body.count('if cmdb.__CLOUD_MODE__:') == 1


def test_connection_routes_is_the_only_prefixless_registration() -> None:
    """Everything except the /rest root probe declares where it mounts"""
    body = _registration_source()

    assert re.findall(r'register_blueprint\(\s*(\w+)\s*\)', body) == ['connection_routes']


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
    The on-premise and tenant paths used to duplicate the validate-then-migrate sequence

    They disagreed about a newly created database, which is what G45 recorded. Sharing the helper is
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


def test_execute_update_checks_stops_at_the_first_failing_tenant() -> None:
    """No per-tenant isolation: one failing database aborts the whole loop (discussion-backlog #156)"""
    with patch(f'{MODULE_PATH}.get_db_names_from_service_portal', return_value=TENANT_DBS), \
         patch(f'{MODULE_PATH}.CollectionValidator') as mock_validator, \
         patch(f'{MODULE_PATH}.DatabaseUpdater'):
        mock_validator.return_value.validate_collections.side_effect = RuntimeError('tenant-a is broken')

        with pytest.raises(RuntimeError):
            execute_update_checks(MagicMock())

    assert mock_validator.call_count == 1
