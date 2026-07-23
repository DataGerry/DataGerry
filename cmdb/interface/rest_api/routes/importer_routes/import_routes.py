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
Root blueprint for the CmdbType import routes

Defines the `/import` root blueprint and mounts the nested `/import/type` route module: importing it
delegates every `@route(...)` back to `importer_blueprint` via its `NestedBlueprint`, so no explicit
sub-registration step is needed. The `/import/object` routes are their own `APIBlueprint`
(`importer_object_routes.importer_object_blueprint`) registered directly by `init_rest_api`.
"""
from flask import current_app

from cmdb.interface.blueprints import RootBlueprint
# -------------------------------------------------------------------------------------------------------------------- #
importer_blueprint = RootBlueprint('import_rest', __name__, url_prefix='/import')

# Side-effect import: loading this module registers its routes on importer_blueprint
with current_app.app_context():
    # pylint: disable=unused-import
    from cmdb.interface.rest_api.routes.importer_routes import importer_type_routes  # noqa: F401
