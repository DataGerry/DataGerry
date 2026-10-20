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
Response-shape constants for the DataGerry system-information REST routes

Names the response keys of `GET /settings/system/` and `GET /settings/system/config/`, which are a
frontend contract (`app/src/app/settings/system/system.service.ts`), plus the right guarding both
routes, and the response keys and deployment values of `GET /settings/system/deployment/`
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'SYSTEM_VIEW_RIGHT',
    'UPDATER_SETTINGS_SECTION',
    'UNKNOWN_DB_VERSION',
    'SystemInfoKey',
    'SystemConfigKey',
    'DeploymentInfoKey',
    'DeploymentKind',
]

# Right required to read the system information and the system configuration
SYSTEM_VIEW_RIGHT: str = 'base.system.view'

# Settings section the database updater records its applied schema version in
UPDATER_SETTINGS_SECTION: str = 'updater'

# Reported as the db_version when the updater section cannot be read
UNKNOWN_DB_VERSION: int = 0


class SystemInfoKey(BaseStrEnum):
    """
    Keys of the `GET /settings/system/` response (frontend contract)

    ``RUNTIME`` and ``STARTING_PARAMETERS`` are answered on premise only (``system_helper.build_system_information``)
    """
    TITLE = 'title'
    VERSION = 'version'
    DB_VERSION = 'db_version'
    RUNTIME = 'runtime'
    STARTING_PARAMETERS = 'starting_parameters'


class SystemConfigKey(BaseStrEnum):
    """Keys of the `GET /settings/system/config/` response (frontend contract)"""
    PATH = 'path'
    PROPERTIES = 'properties'


class DeploymentInfoKey(BaseStrEnum):
    """
    Keys of the `GET /settings/system/deployment/` response (frontend contract)

    ``HOST_NAME`` is null in cloud mode, where the machine is shared by every tenant
    """
    DEPLOYMENT = 'deployment'
    VERSION = 'version'
    DATABASE_REACHABLE = 'database_reachable'
    HOST_NAME = 'host_name'


class DeploymentKind(BaseStrEnum):
    """
    How this DataGerry is deployed, the value of ``DeploymentInfoKey.DEPLOYMENT``

    ``CLOUD`` is the hosted cloud product, ``--local`` included (the cloud product on a developer machine)
    """
    ON_PREMISE = 'on_premise'
    CLOUD = 'cloud'
