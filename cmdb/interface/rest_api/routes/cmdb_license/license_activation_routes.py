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
machine (fingerprint + HMAC, P9), persists it (superseding any prior pending request), and returns
its Base64 blob - by default as a downloadable `text/plain` `.txt` file the admin hands to the
license portal, or, when called with `?as_string=true`, as a string payload wrapped in a
`DefaultResponse` so the frontend can read the content directly. The license feature is on-premise
only, so the route is hidden (404) whenever the process runs in cloud or local mode
"""
from logging import Logger, getLogger

from flask import abort, current_app, request, Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import LicenseActivationRequestsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.security.license import (
    activation_request_blob,
    get_machine_fingerprint,
)

from cmdb.utils.helpers import str_to_bool

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.cmdb_license.license_constants import (
    ACTIVATION_REQUEST_ROUTE,
    ACTIVATION_REQUEST_FILENAME,
    ACTIVATION_REQUEST_AS_STRING_PARAM,
    ACTIVATION_REQUEST_RESPONSE_KEY,
    ACTIVATION_VIEW_RIGHT,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

license_activation_blueprint = APIBlueprint('license_activation', __name__)

# MIME type of the downloadable activation-request file
ACTIVATION_REQUEST_MIME_TYPE: str = 'text/plain'


@license_activation_blueprint.route(ACTIVATION_REQUEST_ROUTE, methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@license_activation_blueprint.protect(auth=True, right=ACTIVATION_VIEW_RIGHT)
def get_license_activation_request(request_user: CmdbUser):
    """
    HTTP `GET` route generating an offline activation request

    Generates a fresh activation request bound to this machine, persists it (superseding any prior
    pending request), and returns its Base64 blob. By default the blob is a downloadable
    `text/plain` `.txt` attachment; when called with `?as_string=true` the same blob is returned as
    a string payload in a `DefaultResponse`. Available in the on-premise version only (404 in
    cloud/local mode)

    Args:
        request_user (CmdbUser): The user requesting the activation request

    Returns:
        Response: The activation-request blob - a `.txt` attachment, or a `DefaultResponse` string
            payload when `?as_string=true`
    """
    if current_app.cloud_mode or current_app.local_mode:
        abort(404, "The license feature is only available in the on-premise version!")

    try:
        as_string: bool = str_to_bool(request.args.get(ACTIVATION_REQUEST_AS_STRING_PARAM, default='false'))
    except ValueError:
        abort(400, f"Query parameter '{ACTIVATION_REQUEST_AS_STRING_PARAM}' must be 'true' or 'false'!")

    try:
        activation_requests_manager: LicenseActivationRequestsManager = ManagerProvider.get_manager(
                                                                            ManagerType.LICENSE_ACTIVATION_REQUESTS,
                                                                            request_user
                                                                        )

        activation_request = activation_requests_manager.create_activation_request(get_machine_fingerprint())
        blob = activation_request_blob(activation_request)

        if as_string:
            return DefaultResponse({ACTIVATION_REQUEST_RESPONSE_KEY: blob}).make_response()

        response = Response(blob, mimetype=ACTIVATION_REQUEST_MIME_TYPE)
        response.headers['Content-Disposition'] = f'attachment; filename="{ACTIVATION_REQUEST_FILENAME}"'

        return response
    except HTTPException:
        raise
    except Exception as err:
        LOGGER.error("[get_license_activation_request] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while generating the license activation request!")
