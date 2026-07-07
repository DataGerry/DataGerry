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
The `requires_feature` route guard for license feature-gating (license feature part P15, Step 1)

A decorator that blocks a route when the active license does not unlock a given LicenseFeature.
Gating applies ON-PREMISE ONLY: in cloud or local mode the guard passes through untouched, leaving
the subscription/api-level gating those modes already enforce. On-premise it resolves the
LicenseService once per request (cached on `flask.g` so hot paths do not re-decrypt/re-verify per
call) and aborts with HTTP 403 - distinct from the codebase's usual 400 for invalid data - when the
feature is not unlocked. The guard belongs at the bottom of the decorator stack (the `@protect`
level): it runs after `@insert_request_user` has populated `request_user` in kwargs and reads the
mode flags off `current_app`
"""
import functools
from logging import Logger, getLogger
from typing import Any, Callable

from flask import Blueprint, abort, current_app, g, request

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.license_manager.license_service import LicenseService

from cmdb.models.user_model import CmdbUser

from cmdb.interface.rest_api.auth_method_enum import AuthMethod
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# `flask.g` attribute under which the per-request {LicenseFeature: bool} lookup cache is stored
LICENSE_FEATURE_CACHE_ATTR: str = 'license_feature_cache'

# Prefix of an `Authorization` header carrying HTTP Basic credentials (e.g. "Basic dXNlcjpwYXNz")
BASIC_AUTH_HEADER_PREFIX: str = f'{AuthMethod.BASIC.value} '

# 403 body when a feature is not unlocked; `{feature}` is filled with a human-readable feature label
FEATURE_NOT_LICENSED_MESSAGE: str = "The {feature} feature requires a valid license!"

# Human-readable labels for the 403 message, keyed by feature (values are display-only)
LICENSE_FEATURE_LABELS: dict[LicenseFeature, str] = {
    LicenseFeature.REST_API: 'REST API',
    LicenseFeature.IPAM: 'IPAM',
    LicenseFeature.ISMS: 'ISMS',
    LicenseFeature.DOCUMENT_GENERATOR: 'Document Generator',
    LicenseFeature.AUTOMATIONS: 'Automations',
}


def request_has_feature(feature: LicenseFeature, request_user: CmdbUser | None = None) -> bool:
    """
    Resolves whether the active license unlocks a feature, caching the result per request

    The first lookup of a feature in a request resolves the LicenseService (which re-verifies the
    stored license) and stores the boolean on `flask.g`; subsequent lookups in the same request -
    e.g. a bulk write hitting the guard repeatedly - read the cached value

    Args:
        feature (LicenseFeature): The feature whose availability is checked
        request_user (CmdbUser | None): The user making the request. Only consulted when resolving
            a tenant-scoped manager in cloud mode; on-premise (the only mode that gates) the license
            store is install-wide, so this may be None - e.g. when called from a blueprint-level gate
            that runs before the request user is resolved

    Returns:
        bool: True if the current entitlement unlocks the feature
    """
    cache: dict[LicenseFeature, bool] | None = getattr(g, LICENSE_FEATURE_CACHE_ATTR, None)

    if cache is None:
        cache = {}
        setattr(g, LICENSE_FEATURE_CACHE_ATTR, cache)

    if feature not in cache:
        license_service: LicenseService = ManagerProvider.get_manager(ManagerType.LICENSE_SERVICE, request_user)
        cache[feature] = license_service.has_feature(feature)

    return cache[feature]


def feature_locked(feature: LicenseFeature, request_user: CmdbUser | None = None) -> bool:
    """
    Whether a feature must be blocked right now: on-premise AND not licensed

    The single predicate behind every gate - the route decorator, the blueprint gate and the
    embedded write guards. In cloud or local mode it always returns False (those modes keep their
    own subscription gating); on-premise it returns True when the active license does not unlock the
    feature

    Args:
        feature (LicenseFeature): The feature to test
        request_user (CmdbUser | None): The requesting user; only needed to resolve a tenant-scoped
            manager in cloud mode, so on-premise (the only mode that gates) it may be None

    Returns:
        bool: True if the feature is currently blocked and the caller should refuse the action
    """
    if current_app.cloud_mode or current_app.local_mode:
        return False

    return not request_has_feature(feature, request_user)


def abort_if_feature_locked(feature: LicenseFeature, request_user: CmdbUser | None = None) -> None:
    """
    Aborts the request with HTTP 403 when the feature is blocked (on-premise and unlicensed)

    Shared by the route decorator, the blueprint gate and the embedded write guards so they all emit
    the same 403 contract and message. A no-op when the feature is available or in cloud/local mode

    Args:
        feature (LicenseFeature): The feature the action belongs to
        request_user (CmdbUser | None): The requesting user (see feature_locked)
    """
    if feature_locked(feature, request_user):
        label = LICENSE_FEATURE_LABELS.get(feature, feature.value)
        abort(403, FEATURE_NOT_LICENSED_MESSAGE.format(feature=label))


def requires_feature(feature: LicenseFeature) -> Callable[..., Any]:
    """
    Builds a route decorator that blocks the route when `feature` is not licensed (on-premise only)

    Requires `@insert_request_user` above it so `request_user` is present in kwargs. In cloud or
    local mode the guard is a no-op pass-through. On-premise it aborts with HTTP 403 when the active
    license does not unlock the feature

    Args:
        feature (LicenseFeature): The feature the route belongs to

    Returns:
        Callable[..., Any]: The decorator applying the gate to a route handler
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # On-premise only: cloud/local keep their own subscription + api-level gating
            if current_app.cloud_mode or current_app.local_mode:
                return func(*args, **kwargs)

            request_user: CmdbUser | None = kwargs.get('request_user')

            if request_user is None:
                abort(400, 'No request user was provided')

            abort_if_feature_locked(feature, request_user)

            return func(*args, **kwargs)

        return wrapper

    return decorator


def gate_blueprint(blueprint: Blueprint, feature: LicenseFeature) -> None:
    """
    Gates EVERY route on a blueprint behind a license feature (on-premise only)

    Registers a `before_request` hook so all current and future routes on the blueprint are blocked
    with HTTP 403 when the feature is not licensed. Use this to lock a whole feature surface in one
    place; use `requires_feature` to gate individual routes. CORS preflight `OPTIONS` requests are
    never gated - aborting them would fail the browser preflight and surface as a CORS error rather
    than the intended 403. In cloud or local mode the hook is a no-op pass-through. Must be called
    BEFORE the blueprint is registered on the app (Flask runs a blueprint's deferred setup at
    registration time)

    Args:
        blueprint (Blueprint): The blueprint whose routes are gated
        feature (LicenseFeature): The feature the blueprint belongs to
    """
    def enforce_feature() -> None:
        # Never gate the CORS preflight: the browser sends an unauthenticated OPTIONS before the
        # real cross-origin request and requires a 2xx on it. Aborting here (403) fails the preflight
        # so the browser never sends the real request, surfacing as a CORS error in the frontend.
        # flask-cors answers the preflight itself; the gate belongs on the actual method only.
        if request.method == 'OPTIONS':
            return

        # On-premise only: cloud/local keep their own subscription + api-level gating (handled
        # inside abort_if_feature_locked, which is a no-op in those modes)
        abort_if_feature_locked(feature)

    blueprint.before_request(enforce_feature)


def enforce_rest_api_license() -> None:
    """
    Blocks HTTP Basic-auth REST calls when the REST_API feature is not licensed (on-premise only)

    Registered as an app-level `before_request` on the REST API. On-premise the two auth channels are
    distinguishable: external automation authenticates per request with `Authorization: Basic
    <user:pass>` (`parse_authorization_header` mints a token from those credentials on every call),
    whereas the Angular UI logs in once via `POST /auth/login` (a JSON body, no `Authorization`
    header) and then sends `Authorization: Bearer <jwt>`. Refusing Basic-auth requests therefore
    locks the external REST API while leaving the UI - login and every Bearer call - fully
    functional. The determined caller can still script the login+Bearer flow; this is a deliberate,
    accepted gap (the mint route stays open so users can always log in).

    CORS preflight `OPTIONS` is never gated. In cloud or local mode the check is a no-op
    (`abort_if_feature_locked` returns without effect there), leaving the cloud `x-api-key` +
    api-level gating untouched.
    """
    # Never gate the CORS preflight (see gate_blueprint for the rationale)
    if request.method == 'OPTIONS':
        return

    auth_header: str | None = request.headers.get('Authorization')

    # Case-insensitive match: parse_authorization_header lowercases the scheme before accepting it,
    # so a lowercase "basic " header still authenticates and must be gated the same way
    if auth_header and auth_header.lower().startswith(BASIC_AUTH_HEADER_PREFIX.lower()):
        abort_if_feature_locked(LicenseFeature.REST_API)
