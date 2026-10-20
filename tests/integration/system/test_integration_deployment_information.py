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
Integration tests for the values behind ``GET /settings/system/deployment/``, unmocked

The machine's name is the one the operating system reports for this host (``platform.node()``, else
``socket.gethostname()``), and the database probe answers ``True`` for the running test MongoDB
"""
import platform
import socket

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.settings_routes.system_constants import DeploymentInfoKey, DeploymentKind
from cmdb.interface.rest_api.routes.settings_routes.system_helper import build_deployment_information, read_host_name
# -------------------------------------------------------------------------------------------------------------------- #


def test_the_host_name_is_this_machines() -> None:
    """What the operating system calls this host"""
    assert read_host_name(cloud_mode=False) == (platform.node().strip() or socket.gethostname().strip())


def test_the_probe_reaches_the_running_database(database_manager: MongoDatabaseManager) -> None:
    """The live probe the route answers as database_reachable"""
    information = build_deployment_information(False, database_manager.status(), read_host_name(cloud_mode=False))

    assert information[DeploymentInfoKey.DATABASE_REACHABLE.value] is True
    assert information[DeploymentInfoKey.DEPLOYMENT.value] == DeploymentKind.ON_PREMISE.value
