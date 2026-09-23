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
Implementation of the license (entitlement) REST routes

Exposes the active license to the frontend: GET the current license (always answers - the verified
license, or the free/Community default when none is active or it is invalid), POST a license blob to
activate it (verify then store), and DELETE it to revert to free. The license feature is on-premise
only, so every route is hidden (404) in cloud or local mode

`GET /entitlements` is the exception to the rights on this surface: managing a license is an admin
task, but every user's screen depends on what the license unlocks, so that route is authenticated
and nothing more. It answers what a client needs to gate its UI and nothing that identifies the
license
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, current_app

from cmdb.manager import LicenseService
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.security.license import LicenseEntitlement

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetSingleResponse
from cmdb.interface.rest_api.routes.cmdb_license.license_constants import (
    ACTIVATE_LICENSE_ROUTE,
    CURRENT_LICENSE_ROUTE,
    LICENSE_ENTITLEMENTS_ROUTE,
    LICENSE_DELETE_RIGHT,
    LICENSE_EDIT_RIGHT,
    LICENSE_VIEW_RIGHT,
    LICENSE_UPLOAD_SCHEMA,
    CurrentLicenseResponseKey,
    LicenseEntitlementsResponseKey,
    LicenseUploadKey,
)
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

license_blueprint = APIBlueprint('license', __name__)

# Message returned when the feature is accessed outside the on-premise version
ON_PREMISE_ONLY_MESSAGE: str = "The license feature is only available in the on-premise version!"


def _abort_if_not_on_premise() -> None:
    """Aborts with 404 when the process runs in cloud or local mode (license is on-premise only)"""
    if current_app.cloud_mode or current_app.local_mode:
        abort(404, ON_PREMISE_ONLY_MESSAGE)


def _current_license_payload(license_service: LicenseService) -> dict[str, Any]:
    """
    Builds the current-license response payload from a single license-state resolution

    The effective entitlement fields (type, features, licenseId, hmac, startDate, endDate, subId)
    are emitted flat at the top level, alongside the is_active flag and verification status

    Args:
        license_service (LicenseService): The license service to read state from

    Returns:
        dict[str, Any]: The flattened entitlement document plus the is_active / status fields
    """
    state = license_service.current_state()

    payload: dict[str, Any] = LicenseEntitlement.to_json(state.entitlement)
    payload[CurrentLicenseResponseKey.IS_ACTIVE] = state.active
    payload[CurrentLicenseResponseKey.STATUS] = state.status.value if state.status is not None else None

    return payload


@license_blueprint.route(CURRENT_LICENSE_ROUTE, methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@license_blueprint.protect(auth=True, right=LICENSE_VIEW_RIGHT)
def get_current_license(request_user: CmdbUser):
    """
    HTTP `GET`/`HEAD` route returning the currently effective license

    Always returns a license: the verified entitlement when one is active, otherwise the free
    (Community) entitlement. Available in the on-premise version only (404 in cloud/local mode)

    Args:
        request_user (CmdbUser): The user requesting the current license

    Returns:
        GetSingleResponse: The is_active flag, verification status and effective entitlement
    """
    _abort_if_not_on_premise()

    try:
        license_service: LicenseService = ManagerProvider.get_manager(ManagerType.LICENSE_SERVICE, request_user)

        return GetSingleResponse(_current_license_payload(license_service),
                                 body=request_wants_body()).make_response()
    except Exception as err:
        LOGGER.error("[get_current_license] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the current license!")


@license_blueprint.route(LICENSE_ENTITLEMENTS_ROUTE, methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@handle_route_errors("while retrieving the license entitlements")
def get_license_entitlements(request_user: CmdbUser):
    """
    HTTP `GET`/`HEAD` route returning what the current license unlocks

    **Authenticated, and carries no ACL right.** Its sibling routes demand `base.license.*` because
    they read or change the license itself; this one answers only what every user's own screens need
    in order to decide what to show, so gating it behind an admin right would leave a normal user's
    UI unable to tell a locked feature from a broken one

    Three fields, chosen so nothing identifies the license: `is_active`, `type` and `features`. The
    license id, subscription id, binding HMAC and validity dates are NOT part of this payload - they
    are on the right-gated `/current` route.

    `type` is the effective tier and is always answered: an install running on no valid license runs
    on the free entitlement, so the key reads `free` rather than being absent. It is what a screen
    NAMES the plan by - a badge reads "Business" - while saying nothing about which license granted
    it

    `is_active` is the same flag `/current` reports, so the two cannot disagree: True only when a
    stored license verifies as VALID, which already requires that it decrypts, matches an activation
    request bound to this machine, has started, and has not expired. `features` is the list the
    license gating itself reads, so a feature listed here is exactly a feature `@requires_feature`
    will let through

    Args:
        request_user (CmdbUser): The user requesting the entitlements

    Returns:
        GetSingleResponse: `is_active`, `type` and `features` (see `LicenseEntitlementsResponseKey`)
    """
    _abort_if_not_on_premise()

    license_service: LicenseService = ManagerProvider.get_manager(ManagerType.LICENSE_SERVICE, request_user)
    state = license_service.current_state()

    payload: dict[str, Any] = {
        LicenseEntitlementsResponseKey.IS_ACTIVE.value: state.active,
        LicenseEntitlementsResponseKey.TYPE.value: state.entitlement.license_type,
        LicenseEntitlementsResponseKey.FEATURES.value: list(state.entitlement.features),
    }

    return GetSingleResponse(payload, body=request_wants_body()).make_response()


@license_blueprint.route(ACTIVATE_LICENSE_ROUTE, methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@license_blueprint.protect(auth=True, right=LICENSE_EDIT_RIGHT)
@license_blueprint.validate(LICENSE_UPLOAD_SCHEMA)
@handle_route_errors("while activating the license")
def activate_license(data: dict, request_user: CmdbUser):
    """
    HTTP `POST` route activating an uploaded license blob

    Verifies the uploaded blob and, when valid, stores it as the active license. An invalid license
    is rejected with HTTP 400 carrying the verification status. On-premise only (404 in cloud/local)

    Args:
        data (LICENSE_UPLOAD_SCHEMA): The request body carrying the Base64 license blob
        request_user (CmdbUser): The user activating the license

    Returns:
        GetSingleResponse: The current license after activation
    """
    _abort_if_not_on_premise()

    license_service: LicenseService = ManagerProvider.get_manager(ManagerType.LICENSE_SERVICE, request_user)

    result = license_service.activate(data[LicenseUploadKey.BLOB])

    if not result.is_valid:
        abort(400, f"The license could not be activated (status: {result.status.value})!")

    return GetSingleResponse(_current_license_payload(license_service)).make_response()


@license_blueprint.route(CURRENT_LICENSE_ROUTE, methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@license_blueprint.protect(auth=True, right=LICENSE_DELETE_RIGHT)
def delete_current_license(request_user: CmdbUser):
    """
    HTTP `DELETE` route removing the active license, reverting the install to the free tier

    On-premise only (404 in cloud/local mode)

    Args:
        request_user (CmdbUser): The user removing the license

    Returns:
        GetSingleResponse: The current license after removal (the free entitlement)
    """
    _abort_if_not_on_premise()

    try:
        license_service: LicenseService = ManagerProvider.get_manager(ManagerType.LICENSE_SERVICE, request_user)

        license_service.deactivate()

        return GetSingleResponse(_current_license_payload(license_service)).make_response()
    except Exception as err:
        LOGGER.error("[delete_current_license] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while removing the license!")
