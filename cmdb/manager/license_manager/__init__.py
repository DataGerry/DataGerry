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
Managers for the on-premise license feature

Holds the database-backed managers for the license feature (the activation-request store, and
later the license entitlement store). Each is registered in ManagerType and ManagerProvider
"""
from cmdb.manager.license_manager.license_activation_requests_manager import (
    LicenseActivationRequestsManager,
)
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'LicenseActivationRequestsManager',
    'ActiveLicenseManager',
    'LicenseService',
]
