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
Implementation of the license activation-request REST routes

Exposes the offline activation-request endpoint: a GET that generates a fresh request bound to this
machine (fingerprint + HMAC, P9), persists it, and returns both the wire document and the
downloadable Base64+JSON blob. The license feature is on-premise only, so the route is hidden
(404) whenever the process runs in cloud or local mode
"""
from logging import Logger, getLogger

from flask import request, abort, current_app

from cmdb.manager import LicenseActivationRequestsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.security.license import (
    LicenseActivationRequest,
    activation_request_blob,
    get_machine_fingerprint,
)

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetSingleResponse
from cmdb.interface.rest_api.routes.cmdb_license.license_constants import (
    ACTIVATION_REQUEST_ROUTE,
    ACTIVATION_VIEW_RIGHT,
    LicenseActivationResponseKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

license_activation_blueprint = APIBlueprint('license_activation', __name__)


@license_activation_blueprint.route(ACTIVATION_REQUEST_ROUTE, methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@license_activation_blueprint.protect(auth=True, right=ACTIVATION_VIEW_RIGHT)
def get_license_activation_request(request_user: CmdbUser):
    """
    HTTP `GET`/`HEAD` route generating and returning an offline activation request

    Generates a fresh activation request bound to this machine, persists it, and returns the wire
    document together with the downloadable Base64+JSON blob. Available in the on-premise version
    only (404 in cloud/local mode)

    Args:
        request_user (CmdbUser): The user requesting the activation request

    Returns:
        GetSingleResponse: The activation request document and its downloadable blob
    """
    if current_app.cloud_mode or current_app.local_mode:
        abort(404, "The license feature is only available in the on-premise version!")

    try:
        activation_requests_manager: LicenseActivationRequestsManager = ManagerProvider.get_manager(
                                                                            ManagerType.LICENSE_ACTIVATION_REQUESTS,
                                                                            request_user
                                                                        )

        fingerprint = get_machine_fingerprint()
        activation_request = activation_requests_manager.create_activation_request(fingerprint)

        result = {
            LicenseActivationResponseKey.ACTIVATION_REQUEST: LicenseActivationRequest.to_json(activation_request),
            LicenseActivationResponseKey.BLOB: activation_request_blob(activation_request),
        }

        return GetSingleResponse(result, body=request.method == 'HEAD').make_response()
    except Exception as err:
        LOGGER.error("[get_license_activation_request] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while generating the license activation request!")
