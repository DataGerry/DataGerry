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
All API routes for OpenCelium Licenses

**OpenCelium's licence, not DataGerry's.** DataGerry has its own licensing feature under
`/rest/license` (`routes/cmdb_license/`, including its own activation-request route); these two routes
report on the licence of the OpenCelium installation the tenant is connected to. Nothing here is
stored by DataGerry - both routes are read-only proxies.

**Deliberately NOT gated behind the AUTOMATIONS licence.** Every other OpenCelium blueprint is
(`init_rest_api`), because the whole integration is that licensed feature - but OpenCelium's own
licence has to stay readable, which is exactly the state an operator needs to see when something is
wrong with it. The routes are still authenticated and `ApiLevel.LOCKED`; they carry no per-route ACL
right, which is discussion-backlog #115 (this file is the fifth unprotected OpenCelium blueprint).

**Frontend usage: `/licenses/info` only** (`license.service.ts`, which always sends `page` and
`size`). The activation route has no caller at all - neither in the frontend nor in the backend - and
its documented answer disagrees with what it actually returns: discussion-backlog #224.
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort
from werkzeug import Response

from cmdb.manager import OcLicenseManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.open_celium_routes.oc_license_helper import (
    build_license_manager,
    read_usage_paging,
)

from cmdb.errors.open_celium.license import OcLicenseGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_licenses_blueprint = APIBlueprint('oc_licenses', __name__)

# The two halves of the /licenses/info body. A frontend contract: the Angular LicenseInfoResponse
# reads both keys off one answer
LICENSE_RESPONSE_KEY: str = 'license'
USAGE_RESPONSE_KEY: str = 'usage'

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_licenses_blueprint.route('/licenses/activation/generate', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium License activation request!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_oc_license_activation(request_user: CmdbUser) -> Response:
    """
    **GET**/**HEAD** route to retrieve an OpenCelium licence activation request

    The activation request is what an operator sends to becon to have their OpenCelium licence
    issued. **Answered as whatever OpenCelium's body parses to**: the manager reads it through
    `parse_response`, i.e. as JSON. This docstring used to promise "a text file", which the code
    cannot produce - which of the two is right needs the OpenCelium endpoint's actual answer and is
    discussion-backlog #224. No caller exists today, in either layer

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        Response: The activation request as OpenCelium answered it
    """
    try:
        oc_license_manager: OcLicenseManager = build_license_manager(request_user)

        oc_license: Any = oc_license_manager.get_license_activation()

        return DefaultResponse(oc_license).make_response()
    except OcLicenseGetError as err:
        LOGGER.error("[get_oc_license_activation] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium License activation!")


@oc_licenses_blueprint.route('/licenses/info', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium License info!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_oc_license_info(request_user: CmdbUser) -> Response:
    """
    **GET**/**HEAD** route to retrieve the OpenCelium licence and its usage of the current month

    Answers **both halves in one body** - `{'license': ..., 'usage': ...}`, the shape the Angular
    `LicenseInfoResponse` reads - which costs two sequential OpenCelium calls per request
    (discussion-backlog #227). `?page=` / `?size=` page the usage report; see `read_usage_paging` for
    what an unreadable value does, and note that the usage WINDOW is the host's local month
    (discussion-backlog #225)

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        Response: `{'license': <the active licence>, 'usage': <the paged usage report>}`
    """
    try:
        page, size = read_usage_paging()

        oc_license_manager: OcLicenseManager = build_license_manager(request_user)

        license_data: dict[str, Any] = {
            LICENSE_RESPONSE_KEY: oc_license_manager.get_active_license(),
            USAGE_RESPONSE_KEY: oc_license_manager.get_license_usage(page, size),
        }

        return DefaultResponse(license_data).make_response()
    except OcLicenseGetError as err:
        LOGGER.error("[get_oc_license_info] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium License info!")
