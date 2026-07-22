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
REST API routes for the on-premise license feature

Holds the license blueprints (routes, helpers and constants in one place, per the route-folder
convention). The blueprints are registered under the '/license' prefix in init_rest_api
"""
from cmdb.interface.rest_api.routes.cmdb_license.license_activation_routes import (
    license_activation_blueprint,
)
from cmdb.interface.rest_api.routes.cmdb_license.license_routes import license_blueprint
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'license_activation_blueprint',
    'license_blueprint',
]
