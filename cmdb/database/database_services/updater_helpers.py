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
Helpers for discovering which databases the updater must check

In cloud mode the set of tenant databases is owned by the Service Portal, so these helpers fetch
the database-name list from it over HTTP (authenticated with the x-access-token); in local mode a
fixed set of names is returned without any network call. The public entry point is
get_db_names_from_service_portal; the underscore-prefixed functions are its building blocks.
"""
from logging import Logger, getLogger
<<<<<<< HEAD
=======
from typing import Any
from http import HTTPStatus
>>>>>>> origin/version-3.2
import os
import requests

from cmdb.errors.security import (
    NoAccessTokenError,
    RequestTimeoutError,
    RequestError,
)
from cmdb.database.database_services.database_services_constants import ServicePortalEnv, ServicePortal
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def get_db_names_from_service_portal(local_mode: bool = False) -> list[str]:
    """
    Retrieves all database names which need to be checked for updates

    In local mode a fixed set of database names is returned without contacting the Service
    Portal; otherwise the names are fetched from the Service Portal over HTTP.

    Args:
        local_mode (bool): Set to True to not retrieve db_names from Service Portal

    Returns:
        list[str]: Names of all databases

    Raises:
        NoAccessTokenError: If the x-access-token is missing (non-local mode)
        RequestTimeoutError: If the Service Portal request times out
        RequestError: If the Service Portal request fails or returns a non-200 status
    """
    if local_mode:
        return _get_local_mode_db_names()

    headers: dict[str, str] = _build_service_portal_headers()

    return _fetch_db_names_from_portal(headers)


def _get_local_mode_db_names() -> list[str]:
    """
    Returns the fixed database names used when running outside the Service Portal (local mode)

    Returns:
        list[str]: The static local-mode database names
    """
    return list(ServicePortal.LOCAL_MODE_DB_NAMES)


def _build_service_portal_headers() -> dict[str, str]:
    """
    Builds the request headers for a Service Portal call, requiring the x-access-token

    Returns:
        dict[str, str]: Request headers carrying the x-access-token

    Raises:
        NoAccessTokenError: If the X-ACCESS-TOKEN environment variable is not set
    """
    x_access_token: str | None = os.getenv(ServicePortalEnv.ACCESS_TOKEN)

    if not x_access_token:
        raise NoAccessTokenError("No x-access-token provided!")

    return {
        ServicePortal.ACCESS_TOKEN_HEADER: x_access_token
    }


def _fetch_db_names_from_portal(headers: dict[str, str]) -> list[str]:
    """
    Requests the list of database names from the Service Portal

    Args:
        headers (dict[str, str]): Request headers carrying the x-access-token

    Returns:
        list[str]: Names of all databases reported by the Service Portal

    Raises:
        RequestError: If DG_SP_BASE_URL is not set, the request fails, or the Service Portal
            returns a non-200 status
        RequestTimeoutError: If the Service Portal request times out
    """
    base_url: str | None = os.getenv(ServicePortalEnv.BASE_URL)

    if not base_url:
        raise RequestError(f"No {ServicePortalEnv.BASE_URL} provided!")

    target: str = f"{base_url}{ServicePortal.DB_NAMES_ENDPOINT}"

    try:
        response: requests.Response = requests.get(
            target, headers=headers, timeout=ServicePortal.REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code == HTTPStatus.OK:
            return response.json()

        error_message: str = _extract_response_error_message(response)
        LOGGER.error("[get_db_names_from_service_portal] StatusCode: %s. Error: %s",
                     response.status_code,
                     error_message)

        raise RequestError(error_message)
    except requests.exceptions.Timeout as err:
        raise RequestTimeoutError(err) from err
    except requests.exceptions.RequestException as err:
        raise RequestError(err) from err
    except RequestError:
        # A missing-config / non-200 RequestError raised above is re-raised unchanged
        raise
    except Exception as err:
        LOGGER.error("[_fetch_db_names_from_portal] Exception: %s. Type: %s", err, type(err))
        raise RequestError(err) from err


def _extract_response_error_message(response: requests.Response) -> str:
    """
    Extracts a human-readable error message from a non-200 Service Portal response

    Falls back to the raw response body when the payload is not JSON or carries no 'message'
    field, so a malformed error body never raises while building the error message.

    Args:
        response (requests.Response): The non-200 response to read the error message from

    Returns:
        str: The payload's 'message' field when present, otherwise the raw response text
    """
    try:
        payload: Any = response.json()
    except ValueError:
        return response.text

    if isinstance(payload, dict):
        return payload.get(ServicePortal.RESPONSE_MESSAGE_KEY, response.text)

    return response.text
