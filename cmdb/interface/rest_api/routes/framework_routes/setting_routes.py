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
Implementation of all API routes for Settings
"""
from logging import Logger, getLogger
from flask import current_app

from cmdb.interface.blueprints import RootBlueprint
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

settings_blueprint = RootBlueprint('settings_rest', __name__, url_prefix='/settings')

with current_app.app_context():
    from cmdb.interface.rest_api.routes.settings_routes.system_routes import system_blueprint
    settings_blueprint.register_nested_blueprint(system_blueprint)
