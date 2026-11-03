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
The hosted cloud's answer of ``GET /license/current``: the subscription license the Service Portal holds

On premise the route answers the verified, machine-bound license. The hosted cloud has no license blob: its license
is the subscription's, read from the Service Portal (``POST /datagerry/subscription/License``) for the requesting
user's email and tenant database on every request. The answer keeps the on-premise shape, so the frontend reads one
document in both editions:

- the entitlement keys as the portal answered them (``startDate``, ``endDate``, ``subId``, ``licenseId``, ``type``,
  ``features``), ``hmac`` null - nothing is bound to a machine in the cloud;
- ``is_active`` and ``status`` judged from the validity window exactly as on premise
  (``entitlement_window_status``: ``valid`` / ``not_yet_valid`` / ``expired``, ``endDate`` 0 = no expiry).

The portal's answer is checked before it is shown (``SUBSCRIPTION_LICENSE_SCHEMA``, and it must name the requested
database when it names one); an error answer or an unusable license is a 502, an unreachable portal a 503. The
answer only displays the license - feature gating in the cloud does not read it
"""
import time
from logging import Logger, getLogger
from typing import Any

from cerberus import Validator
from flask import abort
from requests import RequestException

from cmdb.manager import DgServicePortalManager
from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.manager.system_manager.dg_service_portal_constants import SubscriptionLicenseResponseKey
from cmdb.models.user_model import CmdbUser
from cmdb.security.license import LicenseEntitlement, LicenseEntitlementKey, entitlement_window_status
from cmdb.security.license.license_constants import LicenseVerificationStatus
from cmdb.security.license.verification import MILLIS_PER_SECOND
from cmdb.errors.dg_service_portal import DgServicePortalGetError
from cmdb.interface.rest_api.routes.cmdb_license.license_constants import (
    SERVICE_PORTAL_UNREACHABLE_MESSAGE,
    SUBSCRIPTION_LICENSE_DATABASE_REASON,
    SUBSCRIPTION_LICENSE_SCHEMA,
    SUBSCRIPTION_LICENSE_SCHEMA_REASON,
    SUBSCRIPTION_LICENSE_UNUSABLE_MESSAGE,
    CurrentLicenseResponseKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


def check_subscription_license(portal_license: dict[str, Any], database: str) -> None:
    """
    Refuses a subscription license the route cannot show

    Args:
        portal_license (dict[str, Any]): The license the Service Portal answered
        database (str): The tenant database the license was asked for

    Raises:
        DgServicePortalGetError: If the license does not fit ``SUBSCRIPTION_LICENSE_SCHEMA``, or names another database
    """
    validator: Validator = Validator(SUBSCRIPTION_LICENSE_SCHEMA, allow_unknown=True)

    if not validator.validate(portal_license):
        raise DgServicePortalGetError(SUBSCRIPTION_LICENSE_SCHEMA_REASON.format(errors=validator.errors))

    answered: Any = portal_license.get(SubscriptionLicenseResponseKey.DATABASE_NAME.value)

    if answered is not None and answered != database:
        raise DgServicePortalGetError(
            SUBSCRIPTION_LICENSE_DATABASE_REASON.format(answered=answered, requested=database),
        )


def build_subscription_license_payload(portal_license: dict[str, Any], now_ms: int) -> dict[str, Any]:
    """
    Builds the current-license answer from a checked subscription license, in the on-premise shape

    Args:
        portal_license (dict[str, Any]): The license the Service Portal answered, already checked
        now_ms (int): The moment the validity window is judged at, epoch milliseconds

    Returns:
        dict[str, Any]: The entitlement keys (``hmac`` null) plus ``is_active`` and ``status``
    """
    entitlement: LicenseEntitlement = LicenseEntitlement.from_data({
        LicenseEntitlementKey.START_DATE: portal_license[SubscriptionLicenseResponseKey.START_DATE.value],
        LicenseEntitlementKey.END_DATE: portal_license[SubscriptionLicenseResponseKey.END_DATE.value],
        LicenseEntitlementKey.SUB_ID: portal_license[SubscriptionLicenseResponseKey.SUB_ID.value],
        LicenseEntitlementKey.LICENSE_ID: portal_license[SubscriptionLicenseResponseKey.LICENSE_ID.value],
        LicenseEntitlementKey.TYPE: portal_license[SubscriptionLicenseResponseKey.TYPE.value],
        LicenseEntitlementKey.FEATURES: portal_license[SubscriptionLicenseResponseKey.FEATURES.value],
    })
    status: LicenseVerificationStatus = entitlement_window_status(
        entitlement.start_date, entitlement.end_date, now_ms,
    )

    payload: dict[str, Any] = LicenseEntitlement.to_json(entitlement)
    payload[CurrentLicenseResponseKey.IS_ACTIVE] = status is LicenseVerificationStatus.VALID
    payload[CurrentLicenseResponseKey.STATUS] = status.value

    return payload


def subscription_license_payload(request_user: CmdbUser, now_ms: int | None = None) -> dict[str, Any]:
    """
    Reads the requesting user's subscription license from the Service Portal and builds the route's answer

    Args:
        request_user (CmdbUser): The user requesting the license; its email and tenant database are sent
        now_ms (int | None): The moment the validity window is judged at, epoch milliseconds. Defaults to now

    Raises:
        HTTPException: 502 when the portal answered an error or an unusable license, 503 when it could not be reached

    Returns:
        dict[str, Any]: The current-license answer (see ``build_subscription_license_payload``)
    """
    database: str = ManagerProvider.tenant_database(request_user)

    try:
        portal_license: dict[str, Any] = DgServicePortalManager().get_subscription_license(
            request_user.email, database,
        )
        check_subscription_license(portal_license, database)
    except DgServicePortalGetError as err:
        LOGGER.error("[subscription_license_payload] %s", err)
        abort(502, SUBSCRIPTION_LICENSE_UNUSABLE_MESSAGE)
    except RequestException as err:
        LOGGER.error("[subscription_license_payload] %s: %s", type(err).__name__, err)
        abort(503, SERVICE_PORTAL_UNREACHABLE_MESSAGE)

    current_ms: int = int(time.time() * MILLIS_PER_SECOND) if now_ms is None else now_ms

    return build_subscription_license_payload(portal_license, current_ms)
