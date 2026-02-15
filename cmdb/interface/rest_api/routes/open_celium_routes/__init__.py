# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
All OpenCelium API blueprints
"""
from .oc_connector_routes import oc_connectors_blueprint
from .oc_invoker_routes import oc_invokers_blueprint
from .oc_template_routes import oc_templates_blueprint
from .oc_connection_routes import oc_connections_blueprint
from .oc_scheduler_routes import oc_schedulers_blueprint
from .oc_license_routes import oc_licenses_blueprint
from .oc_connection_log_routes import oc_connection_log_blueprint
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'oc_connectors_blueprint',
    'oc_invokers_blueprint',
    'oc_templates_blueprint',
    'oc_connections_blueprint',
    'oc_schedulers_blueprint',
    'oc_licenses_blueprint',
    'oc_connection_log_blueprint',
]
