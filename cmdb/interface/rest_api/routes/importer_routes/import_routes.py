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
Registering import routes for objects and types
"""
from flask import current_app

from cmdb.interface.blueprints import RootBlueprint
# -------------------------------------------------------------------------------------------------------------------- #
importer_blueprint = RootBlueprint('import_rest', __name__, url_prefix='/import')

with current_app.app_context():
    from cmdb.interface.rest_api.routes.importer_routes.importer_object_routes import importer_object_blueprint
    importer_blueprint.register_nested_blueprint(importer_object_blueprint)
    from cmdb.interface.rest_api.routes.importer_routes.importer_type_routes import importer_type_blueprint
    importer_blueprint.register_nested_blueprint(importer_type_blueprint)
