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

Defines the `/settings` root blueprint and mounts the nested system routes on it. The side-effect
import at the bottom must stay below the blueprint definition - the imported module reads
`settings_blueprint` back out of this one to build its NestedBlueprint
"""
from logging import Logger, getLogger

from cmdb.interface.blueprints import RootBlueprint
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

settings_blueprint = RootBlueprint('settings_rest', __name__, url_prefix='/settings')

# Side-effect import: loading the system routes module registers its routes on settings_blueprint
# (its NestedBlueprint delegates every @route(...) back to this parent blueprint)
# pylint: disable=unused-import,wrong-import-position
from cmdb.interface.rest_api.routes.settings_routes import system_routes  # noqa: E402,F401
