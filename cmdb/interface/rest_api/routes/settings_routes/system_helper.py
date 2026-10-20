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
Helpers behind ``GET /settings/system/`` and ``GET /settings/system/deployment/``

``build_system_information`` assembles the answer and decides what a deployment may show: on premise the build,
the tenant's database schema version, the process uptime and the command line it was started with; in cloud mode
only the first two, because the uptime and the command line belong to the host process every tenant shares.
``read_db_version`` reads the schema version the database updater recorded, answering ``UNKNOWN_DB_VERSION`` when
it cannot be read and letting every other failure through

``build_deployment_information`` assembles the deployment answer - on premise or cloud, the build version, whether
the database answered, and the machine's name. ``read_host_name`` follows the same rule as the system information:
the machine's name is answered on premise only
"""
import sys
import time
from logging import Logger, getLogger
from typing import Any

from cmdb import __title__, __version__, __runtime__
from cmdb.manager import SettingsManager
from cmdb.security.license.license_constants import FINGERPRINT_FALLBACK
from cmdb.security.license.machine_fingerprint import get_computer_name
from cmdb.interface.rest_api.routes.settings_routes.system_constants import (
    UPDATER_SETTINGS_SECTION,
    UNKNOWN_DB_VERSION,
    DeploymentInfoKey,
    DeploymentKind,
    SystemInfoKey,
)

from cmdb.errors.database import DocumentGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


def read_db_version(settings_manager: SettingsManager) -> Any:
    """
    Reads the database schema version the updater recorded

    A database without an ``updater`` section, or a section without a version, has none recorded; a failed read
    is logged. Both answer ``UNKNOWN_DB_VERSION``, since the rest of the system information is still valid. Any
    other error is a defect and is raised

    Args:
        settings_manager (SettingsManager): The tenant's settings manager

    Returns:
        Any: The recorded version, or ``UNKNOWN_DB_VERSION``
    """
    try:
        updater_section: dict[str, Any] = settings_manager.get_all_values_from_section(
            UPDATER_SETTINGS_SECTION, default={},
        )
    except DocumentGetError as err:
        LOGGER.error("[read_db_version] Failed to read the '%s' settings: %s", UPDATER_SETTINGS_SECTION, err,
                     exc_info=True)
        return UNKNOWN_DB_VERSION

    db_version: Any = updater_section.get(SystemInfoKey.VERSION.value)

    return UNKNOWN_DB_VERSION if db_version is None else db_version


def build_system_information(db_version: Any, cloud_mode: bool) -> dict[str, Any]:
    """
    Assembles the answer of ``GET /settings/system/``

    Args:
        db_version (Any): The tenant's database schema version (``read_db_version``)
        cloud_mode (bool): Whether the process serves hosted cloud tenants

    Returns:
        dict[str, Any]: ``title``, ``version`` and ``db_version``; on premise also ``runtime`` (seconds since the
            process started) and ``starting_parameters`` (its ``sys.argv``)
    """
    information: dict[str, Any] = {
        SystemInfoKey.TITLE.value: __title__,
        SystemInfoKey.VERSION.value: __version__,
        SystemInfoKey.DB_VERSION.value: db_version,
    }

    if not cloud_mode:
        information[SystemInfoKey.RUNTIME.value] = time.time() - __runtime__
        information[SystemInfoKey.STARTING_PARAMETERS.value] = sys.argv

    return information


def read_host_name(cloud_mode: bool) -> str | None:
    """
    The name of the machine DataGerry runs on, as far as this deployment may show it

    Args:
        cloud_mode (bool): Whether the process serves hosted cloud tenants

    Returns:
        str | None: The machine's network name on premise; None in cloud mode (the machine is shared by every
            tenant) and when the name cannot be resolved
    """
    if cloud_mode:
        return None

    host_name: str = get_computer_name()

    return None if host_name == FINGERPRINT_FALLBACK else host_name


def build_deployment_information(
        cloud_mode: bool,
        database_reachable: bool,
        host_name: str | None) -> dict[str, Any]:
    """
    Assembles the answer of ``GET /settings/system/deployment/``

    Args:
        cloud_mode (bool): Whether the process serves hosted cloud tenants
        database_reachable (bool): Whether the database answered the connection probe
        host_name (str | None): The machine's name (``read_host_name``)

    Returns:
        dict[str, Any]: ``deployment`` (``on_premise`` / ``cloud``), ``version``, ``database_reachable`` and
            ``host_name``
    """
    return {
        DeploymentInfoKey.DEPLOYMENT.value: (DeploymentKind.CLOUD if cloud_mode else DeploymentKind.ON_PREMISE).value,
        DeploymentInfoKey.VERSION.value: __version__,
        DeploymentInfoKey.DATABASE_REACHABLE.value: database_reachable,
        DeploymentInfoKey.HOST_NAME.value: host_name,
    }
