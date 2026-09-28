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
Unit tests for cmdb.interface.rest_api.routes.cmdb_license.license_guard

Pure tests of the requires_feature decorator, the blueprint gate, the after-authentication enforcement
and the request_has_feature helper. A minimal Flask
app supplies the request/app context so current_app, flask.g and abort work without booting the REST
API, and ManagerProvider.get_manager is patched to hand back a stub LicenseService. Each branch is
exercised in isolation: cloud/local pass-through, feature present/absent, the missing-request_user
guard, the 403 message, and the per-request lookup cache (including that it does not leak across
requests)
"""
import base64
from http import HTTPStatus
from typing import Any, Callable

import pytest
from flask import Blueprint, Flask, g
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.cmdb_license import license_guard
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import (
    abort_if_feature_locked,
    GATED_FEATURE_ATTR,
    LICENSE_REQUIRED_FEATURES_ATTR,
    enforce_request_licenses,
    feature_locked,
    gate_blueprint,
    request_has_feature,
    require_feature_for_request,
    requires_feature,
)
from cmdb.interface.route_utils import AUTHORIZATION_HEADER, BASIC_AUTH_HEADER_PREFIX
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

GATED_FEATURE: LicenseFeature = LicenseFeature.DOCUMENT_GENERATOR
HANDLER_RESULT: str = 'handler-ran'
REQUEST_USER_SENTINEL: object = object()
GATED_ROUTE: str = '/gated'
VIEW_RESULT: str = 'view-ran'

# Fixtures for the REST-API (Basic-auth) lock tests
BASIC_AUTH_HEADER: str = BASIC_AUTH_HEADER_PREFIX + base64.b64encode(b'user:pass').decode('utf-8')
BEARER_AUTH_HEADER: str = 'Bearer some.jwt.token'


class _StubLicenseService:
    """Stand-in for LicenseService recording how often has_feature is asked"""

    def __init__(self, unlocked: set[str]) -> None:
        """
        Initialises the stub

        Args:
            unlocked (set[str]): The feature values the stub reports as licensed
        """
        self._unlocked = unlocked
        self.call_count = 0

    def has_feature(self, feature: LicenseFeature) -> bool:
        """
        Mirrors LicenseService.has_feature against a fixed set of unlocked feature values

        Args:
            feature (LicenseFeature): The feature being checked

        Returns:
            bool: True if the feature value is in the unlocked set
        """
        self.call_count += 1
        return feature.value in self._unlocked


@pytest.fixture(name='app')
def app_fixture() -> Flask:
    """Provides a minimal on-premise Flask app (cloud and local mode both off)"""
    application = Flask(__name__)
    application.cloud_mode = False
    application.local_mode = False

    return application


@pytest.fixture(name='install_service')
def install_service_fixture(monkeypatch: pytest.MonkeyPatch) -> Callable[[set[str]], _StubLicenseService]:
    """Returns a helper that patches the guard's ManagerProvider to yield a stub LicenseService"""
    def _install(unlocked: set[str]) -> _StubLicenseService:
        stub = _StubLicenseService(unlocked)
        monkeypatch.setattr(license_guard.ManagerProvider, 'get_manager', lambda *_args, **_kwargs: stub)

        return stub

    return _install


def _make_protected() -> Callable[..., str]:
    """Builds a handler guarded by requires_feature that returns a sentinel when it runs"""
    @requires_feature(GATED_FEATURE)
    def _protected(request_user: Any = None) -> str:
        return HANDLER_RESULT

    return _protected


# -------------------------------------------------------------------------------------------------------------------- #
#                                          mode pass-through                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_passes_through_in_cloud_mode(app: Flask, install_service: Callable[[set[str]], _StubLicenseService]) -> None:
    """In cloud mode the guard is a no-op and never consults the license"""
    app.cloud_mode = True
    stub = install_service(set())
    protected = _make_protected()

    with app.test_request_context():
        result = protected(request_user=REQUEST_USER_SENTINEL)

    assert result == HANDLER_RESULT
    assert stub.call_count == 0


def test_passes_through_in_local_mode(app: Flask, install_service: Callable[[set[str]], _StubLicenseService]) -> None:
    """In local mode the guard is a no-op and never consults the license"""
    app.local_mode = True
    stub = install_service(set())
    protected = _make_protected()

    with app.test_request_context():
        result = protected(request_user=REQUEST_USER_SENTINEL)

    assert result == HANDLER_RESULT
    assert stub.call_count == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                          on-premise gating                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_runs_handler_when_feature_licensed(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """On-premise, a licensed feature lets the handler run"""
    install_service({GATED_FEATURE.value})
    protected = _make_protected()

    with app.test_request_context():
        result = protected(request_user=REQUEST_USER_SENTINEL)

    assert result == HANDLER_RESULT


def test_aborts_403_when_feature_not_licensed(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """On-premise, an unlicensed feature is blocked with HTTP 403"""
    install_service(set())
    protected = _make_protected()

    with app.test_request_context():
        with pytest.raises(HTTPException) as exc_info:
            protected(request_user=REQUEST_USER_SENTINEL)

    assert exc_info.value.code == HTTPStatus.FORBIDDEN


def test_aborts_400_when_request_user_missing(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """A guarded route invoked without a request_user is rejected with HTTP 400"""
    install_service({GATED_FEATURE.value})
    protected = _make_protected()

    with app.test_request_context():
        with pytest.raises(HTTPException) as exc_info:
            protected()

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST


def test_403_message_uses_feature_label(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """The 403 body names the feature with its human-readable label"""
    install_service(set())
    protected = _make_protected()

    with app.test_request_context():
        with pytest.raises(HTTPException) as exc_info:
            protected(request_user=REQUEST_USER_SENTINEL)

    expected = license_guard.FEATURE_NOT_LICENSED_MESSAGE.format(
        feature=license_guard.LICENSE_FEATURE_LABELS[GATED_FEATURE],
    )
    assert exc_info.value.description == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                          per-request cache                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_request_has_feature_caches_within_a_request(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """Repeated lookups in one request resolve the license only once"""
    stub = install_service({GATED_FEATURE.value})

    with app.test_request_context():
        first = request_has_feature(GATED_FEATURE, REQUEST_USER_SENTINEL)
        second = request_has_feature(GATED_FEATURE, REQUEST_USER_SENTINEL)

    assert first is True
    assert second is True
    assert stub.call_count == 1


def test_cache_does_not_leak_across_requests(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """A fresh request re-resolves the license (the cache lives on flask.g)"""
    stub = install_service({GATED_FEATURE.value})

    with app.test_request_context():
        request_has_feature(GATED_FEATURE, REQUEST_USER_SENTINEL)

    with app.test_request_context():
        request_has_feature(GATED_FEATURE, REQUEST_USER_SENTINEL)

    assert stub.call_count == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                          gate_blueprint (whole-blueprint lock)                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _build_gated_client(cloud_mode: bool = False, local_mode: bool = False, authenticate: bool = True):
    """
    Builds a test client for an app whose single-route blueprint is gated by gate_blueprint

    With `authenticate` the view stands in for a route under `insert_request_user`: it runs
    `enforce_request_licenses` first, as that decorator does once the caller is known. Without it the
    view never enforces - what a route missing the decorator would do
    """
    application = Flask(__name__)
    application.cloud_mode = cloud_mode
    application.local_mode = local_mode

    blueprint = Blueprint('gated_bp', __name__)

    @blueprint.route(GATED_ROUTE)
    def _view() -> str:
        if authenticate:
            enforce_request_licenses(REQUEST_USER_SENTINEL, False)

        return VIEW_RESULT

    # Must gate BEFORE registering (Flask runs the blueprint's deferred setup at registration time)
    gate_blueprint(blueprint, GATED_FEATURE)
    application.register_blueprint(blueprint)

    return application.test_client()


def test_gate_blueprint_blocks_every_route_when_unlicensed(
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """A gated blueprint blocks its routes with 403 when the feature is not licensed"""
    install_service(set())
    client = _build_gated_client()

    assert client.get(GATED_ROUTE).status_code == HTTPStatus.FORBIDDEN


def test_gate_blueprint_allows_route_when_licensed(
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """A gated blueprint lets its routes run when the feature is licensed"""
    install_service({GATED_FEATURE.value})
    client = _build_gated_client()

    response = client.get(GATED_ROUTE)

    assert response.status_code == HTTPStatus.OK
    assert response.get_data(as_text=True) == VIEW_RESULT


def test_the_gate_hook_itself_never_refuses(
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """
    The hook only records the feature - it runs before any route decorator, so it must not answer

    The view here never enforces, so an unlicensed request reaching it proves the hook let it through
    and never consulted the licence: a refusal is left to the route, after authentication
    """
    stub = install_service(set())
    client = _build_gated_client(authenticate=False)

    assert client.get(GATED_ROUTE).status_code == HTTPStatus.OK
    assert stub.call_count == 0


def test_the_gate_hook_names_its_feature() -> None:
    """The hook carries its feature, which is how a census finds the gated blueprints"""
    blueprint = Blueprint('named_bp', __name__)
    gate_blueprint(blueprint, GATED_FEATURE)

    (hook,) = blueprint.before_request_funcs[None]

    assert getattr(hook, GATED_FEATURE_ATTR) == GATED_FEATURE


def test_gate_blueprint_passes_through_in_local_mode(
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """In local mode a gated blueprint never consults the license and lets routes run"""
    stub = install_service(set())
    client = _build_gated_client(local_mode=True)

    assert client.get(GATED_ROUTE).status_code == HTTPStatus.OK
    assert stub.call_count == 0


def test_gate_blueprint_passes_through_in_cloud_mode(
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """In cloud mode a gated blueprint never consults the license and lets routes run"""
    stub = install_service(set())
    client = _build_gated_client(cloud_mode=True)

    assert client.get(GATED_ROUTE).status_code == HTTPStatus.OK
    assert stub.call_count == 0


def test_gate_blueprint_does_not_block_options_preflight(
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """
    The gate never blocks an OPTIONS preflight, even when unlicensed and never consulting the license

    The browser sends an unauthenticated OPTIONS before a real cross-origin request and requires a
    2xx on it. Gating the preflight (403) would fail the browser check before the real request is
    sent. Flask answers the preflight itself without running the view, so the enforcement - which
    lives in the route - never runs; this pins that directly on gate_blueprint, independently of the
    REST API's flask-cors setup.
    """
    stub = install_service(set())
    client = _build_gated_client()

    response = client.options(GATED_ROUTE)

    assert response.status_code == HTTPStatus.OK
    assert stub.call_count == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                          require_feature_for_request                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_required_feature_is_recorded_once(app: Flask) -> None:
    """Recording the same feature twice keeps one entry, so it is checked once"""
    with app.test_request_context():
        require_feature_for_request(GATED_FEATURE)
        require_feature_for_request(GATED_FEATURE)
        require_feature_for_request(LicenseFeature.ISMS)

        assert getattr(g, LICENSE_REQUIRED_FEATURES_ATTR) == [GATED_FEATURE, LicenseFeature.ISMS]


def test_required_features_do_not_leak_across_requests(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """A feature one request recorded is not required of the next"""
    stub = install_service(set())

    with app.test_request_context():
        require_feature_for_request(GATED_FEATURE)

    with app.test_request_context():
        enforce_request_licenses(REQUEST_USER_SENTINEL, False)  # must not raise

    assert stub.call_count == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                          feature_locked / abort_if_feature_locked                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_feature_locked_false_in_cloud_mode(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """feature_locked is always False in cloud mode and never consults the license"""
    app.cloud_mode = True
    stub = install_service(set())

    with app.test_request_context():
        assert feature_locked(GATED_FEATURE, REQUEST_USER_SENTINEL) is False

    assert stub.call_count == 0


def test_feature_locked_false_in_local_mode(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """feature_locked is always False in local mode and never consults the license"""
    app.local_mode = True
    stub = install_service(set())

    with app.test_request_context():
        assert feature_locked(GATED_FEATURE) is False

    assert stub.call_count == 0


def test_feature_locked_false_when_feature_licensed(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """On-premise, a licensed feature is not locked"""
    install_service({GATED_FEATURE.value})

    with app.test_request_context():
        assert feature_locked(GATED_FEATURE, REQUEST_USER_SENTINEL) is False


def test_feature_locked_true_when_feature_unlicensed(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """On-premise, an unlicensed feature is locked"""
    install_service(set())

    with app.test_request_context():
        assert feature_locked(GATED_FEATURE, REQUEST_USER_SENTINEL) is True


def test_abort_if_feature_locked_raises_403_when_unlicensed(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """abort_if_feature_locked aborts 403 when the feature is locked"""
    install_service(set())

    with app.test_request_context():
        with pytest.raises(HTTPException) as exc_info:
            abort_if_feature_locked(GATED_FEATURE, REQUEST_USER_SENTINEL)

    assert exc_info.value.code == HTTPStatus.FORBIDDEN


def test_abort_if_feature_locked_is_noop_when_licensed(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """abort_if_feature_locked does nothing when the feature is available"""
    install_service({GATED_FEATURE.value})

    with app.test_request_context():
        abort_if_feature_locked(GATED_FEATURE, REQUEST_USER_SENTINEL)  # must not raise


# -------------------------------------------------------------------------------------------------------------------- #
#                                          enforce_request_licenses                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_nothing_required_means_nothing_checked(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """An ungated route with a Bearer caller never consults the licence"""
    stub = install_service(set())

    with app.test_request_context(headers={AUTHORIZATION_HEADER: BEARER_AUTH_HEADER}):
        enforce_request_licenses(REQUEST_USER_SENTINEL, False)  # must not raise

    assert stub.call_count == 0


def test_a_recorded_feature_is_enforced(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """The feature a gated blueprint recorded is refused with 403 naming it"""
    install_service(set())

    with app.test_request_context():
        require_feature_for_request(LicenseFeature.ISMS)

        with pytest.raises(HTTPException) as exc_info:
            enforce_request_licenses(REQUEST_USER_SENTINEL, False)

    assert exc_info.value.code == HTTPStatus.FORBIDDEN
    assert exc_info.value.description == 'The ISMS feature requires a valid license!'


def test_a_licensed_recorded_feature_passes(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """A licensed feature is let through"""
    install_service({LicenseFeature.ISMS.value})

    with app.test_request_context():
        require_feature_for_request(LicenseFeature.ISMS)
        enforce_request_licenses(REQUEST_USER_SENTINEL, False)  # must not raise


def test_the_request_user_reaches_the_licence_lookup(
    app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The authenticated user is what the LicenseService is resolved for"""
    seen: list[Any] = []

    def _get_manager(_manager_type: Any, request_user: Any) -> _StubLicenseService:
        seen.append(request_user)
        return _StubLicenseService({LicenseFeature.ISMS.value})

    monkeypatch.setattr(license_guard.ManagerProvider, 'get_manager', _get_manager)

    with app.test_request_context():
        require_feature_for_request(LicenseFeature.ISMS)
        enforce_request_licenses(REQUEST_USER_SENTINEL, False)

    assert seen == [REQUEST_USER_SENTINEL]


def test_rest_lock_blocks_basic_auth_when_unlicensed(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """On-premise, a Basic-auth caller is refused with 403 when REST_API is not licensed"""
    install_service(set())

    with app.test_request_context(headers={AUTHORIZATION_HEADER: BASIC_AUTH_HEADER}):
        with pytest.raises(HTTPException) as exc_info:
            enforce_request_licenses(REQUEST_USER_SENTINEL, True)

    assert exc_info.value.code == HTTPStatus.FORBIDDEN
    assert exc_info.value.description == 'The REST API feature requires a valid license!'


def test_rest_lock_allows_basic_auth_when_licensed(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """On-premise, a Basic-auth caller passes when REST_API is licensed"""
    install_service({LicenseFeature.REST_API.value})

    with app.test_request_context(headers={AUTHORIZATION_HEADER: BASIC_AUTH_HEADER}):
        enforce_request_licenses(REQUEST_USER_SENTINEL, True)  # must not raise


def test_the_rest_api_is_checked_before_the_blueprint_feature(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """A Basic caller on an unlicensed gated route is told about the channel first"""
    install_service(set())

    with app.test_request_context(headers={AUTHORIZATION_HEADER: BASIC_AUTH_HEADER}):
        require_feature_for_request(LicenseFeature.ISMS)

        with pytest.raises(HTTPException) as exc_info:
            enforce_request_licenses(REQUEST_USER_SENTINEL, True)

    assert exc_info.value.description == 'The REST API feature requires a valid license!'


def test_a_basic_caller_still_needs_the_blueprint_feature(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """REST_API licensed does not unlock the gated blueprint's own feature"""
    install_service({LicenseFeature.REST_API.value})

    with app.test_request_context(headers={AUTHORIZATION_HEADER: BASIC_AUTH_HEADER}):
        require_feature_for_request(LicenseFeature.ISMS)

        with pytest.raises(HTTPException) as exc_info:
            enforce_request_licenses(REQUEST_USER_SENTINEL, True)

    assert exc_info.value.description == 'The ISMS feature requires a valid license!'


def test_rest_lock_passes_through_in_cloud_mode(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """In cloud mode nothing is refused and the license is never consulted"""
    app.cloud_mode = True
    stub = install_service(set())

    with app.test_request_context(headers={AUTHORIZATION_HEADER: BASIC_AUTH_HEADER}):
        require_feature_for_request(LicenseFeature.ISMS)
        enforce_request_licenses(REQUEST_USER_SENTINEL, True)  # must not raise

    assert stub.call_count == 0


def test_rest_lock_passes_through_in_local_mode(
    app: Flask,
    install_service: Callable[[set[str]], _StubLicenseService],
) -> None:
    """In local mode nothing is refused and the license is never consulted"""
    app.local_mode = True
    stub = install_service(set())

    with app.test_request_context(headers={AUTHORIZATION_HEADER: BASIC_AUTH_HEADER}):
        require_feature_for_request(LicenseFeature.ISMS)
        enforce_request_licenses(REQUEST_USER_SENTINEL, True)  # must not raise

    assert stub.call_count == 0
