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
The hosted cloud's answer of ``GET /license/subscription``: the subscription license the Service Portal holds

The hosted cloud has no license blob: its license is the subscription's, read from the Service Portal
(``POST /datagerry/subscription/License``) for the requesting user's email and tenant database on every request.
The answer is forwarded as the portal sent it - nothing in it is checked or derived, because it is only displayed
(the start assistant) and feature gating in the cloud does not read it. The portal's error status or a body that is
no JSON object is a 502, an unreachable portal a 503
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort
from requests import RequestException

from cmdb.manager import DgServicePortalManager
from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.models.user_model import CmdbUser
from cmdb.errors.dg_service_portal import DgServicePortalGetError
from cmdb.interface.rest_api.routes.cmdb_license.license_constants import (
    SERVICE_PORTAL_UNREACHABLE_MESSAGE,
    SUBSCRIPTION_LICENSE_UNUSABLE_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


def subscription_license_payload(request_user: CmdbUser) -> dict[str, Any]:
    """
    Reads the requesting user's subscription license from the Service Portal, as the portal sent it

    Args:
        request_user (CmdbUser): The user requesting the license; its email and tenant database are sent

    Raises:
        HTTPException: 502 when the portal answered an error status or no JSON object, 503 when it could not be
            reached

    Returns:
        dict[str, Any]: The subscription license the portal answered, unchanged
    """
    database: str = ManagerProvider.tenant_database(request_user)

    try:
        return DgServicePortalManager().get_subscription_license(request_user.email, database)
    except DgServicePortalGetError as err:
        LOGGER.error("[subscription_license_payload] %s", err)
        abort(502, SUBSCRIPTION_LICENSE_UNUSABLE_MESSAGE)
    except RequestException as err:
        LOGGER.error("[subscription_license_payload] %s: %s", type(err).__name__, err)
        abort(503, SERVICE_PORTAL_UNREACHABLE_MESSAGE)
