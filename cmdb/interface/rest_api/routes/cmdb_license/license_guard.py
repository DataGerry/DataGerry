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
The license feature-gating guards: the `requires_feature` route decorator and the blueprint gate

Both block a route when the active license does not unlock a given LicenseFeature. Gating applies
ON-PREMISE ONLY: in cloud or local mode the guards pass through untouched, leaving the
subscription/api-level gating those modes already enforce. On-premise the LicenseService is resolved
once per request (cached on `flask.g` so hot paths do not re-decrypt/re-verify per call) and a locked
feature is refused with HTTP 403 - distinct from the codebase's usual 400 for invalid data.

The order is authenticate, then licence, then right: every licence check runs after the caller is
authenticated, so a caller without valid credentials gets the 401 and never learns which features
the installation is licensed for. `requires_feature` sits below `@insert_request_user`; the blueprint
gate and the REST API (HTTP Basic) lock are enforced by `insert_request_user` itself
"""
import functools
from logging import Logger, getLogger
from typing import Any, Callable

from flask import Blueprint, abort, current_app, g

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.license_manager.license_service import LicenseService

from cmdb.models.user_model import CmdbUser

from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# `flask.g` attribute under which the per-request {LicenseFeature: bool} lookup cache is stored
LICENSE_FEATURE_CACHE_ATTR: str = 'license_feature_cache'

# `flask.g` attribute listing the features the current request's gated blueprint requires
LICENSE_REQUIRED_FEATURES_ATTR: str = 'license_required_features'

# Attribute on a `gate_blueprint` hook naming the feature it records - lets a census find the gated blueprints
GATED_FEATURE_ATTR: str = 'gated_feature'


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
            store is install-wide, so this may be None

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

    Registers a `before_request` hook so all current and future routes on the blueprint require the
    feature. The hook only records the feature for the request - it never refuses anything itself:
    a `before_request` hook runs before any route decorator, so a refusal there would answer a caller
    who has not authenticated and tell a stranger which features the installation is licensed for.
    `insert_request_user` enforces the recorded features through `enforce_request_licenses` once the
    caller is authenticated, so every route on a gated blueprint must carry it. Because the hook never
    refuses, a CORS preflight `OPTIONS` - which carries no token and never reaches a route decorator -
    is never gated. Use `requires_feature` to gate individual routes. Must be called BEFORE the
    blueprint is registered on the app (Flask runs a blueprint's deferred setup at registration time)

    Args:
        blueprint (Blueprint): The blueprint whose routes are gated
        feature (LicenseFeature): The feature the blueprint belongs to
    """
    def record_required_feature() -> None:
        require_feature_for_request(feature)

    setattr(record_required_feature, GATED_FEATURE_ATTR, feature)
    blueprint.before_request(record_required_feature)


def require_feature_for_request(feature: LicenseFeature) -> None:
    """
    Records that the current request needs a feature, for `enforce_request_licenses` to check

    Args:
        feature (LicenseFeature): The feature the requested route belongs to
    """
    required: list[LicenseFeature] = getattr(g, LICENSE_REQUIRED_FEATURES_ATTR, [])

    if feature not in required:
        required.append(feature)

    setattr(g, LICENSE_REQUIRED_FEATURES_ATTR, required)


def enforce_request_licenses(request_user: CmdbUser, uses_basic_auth: bool) -> None:
    """
    Refuses an authenticated request whose route or channel needs a feature that is not licensed

    Called by `insert_request_user` right after the caller was authenticated, so a caller without
    valid credentials gets the 401 and never learns the licence state. Two features are checked:

    * REST_API, when the caller authenticated with HTTP Basic. On-premise the two auth channels are
      distinguishable: external automation sends `Authorization: Basic <user:pass>` on every call,
      whereas the Angular UI logs in once via `POST /auth/login` and then sends a Bearer JWT. Refusing
      Basic therefore locks the external REST API while the UI keeps working. The determined caller
      can still script the login+Bearer flow; this is a deliberate, accepted gap
    * every feature a gated blueprint recorded for the request (see `gate_blueprint`)

    A no-op in cloud or local mode (`abort_if_feature_locked` returns without effect there)

    Args:
        request_user (CmdbUser): The authenticated user
        uses_basic_auth (bool): Whether the caller authenticated with HTTP Basic credentials
            (`route_utils.request_uses_basic_auth`)

    Raises:
        HTTPException: 403 naming the first required feature that is not licensed
    """
    required: list[LicenseFeature] = list(getattr(g, LICENSE_REQUIRED_FEATURES_ATTR, []))

    if uses_basic_auth:
        required.insert(0, LicenseFeature.REST_API)

    for feature in required:
        abort_if_feature_locked(feature, request_user)
