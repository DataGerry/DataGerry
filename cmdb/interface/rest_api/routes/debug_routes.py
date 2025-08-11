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
Implementation of all API debug routes
"""
from flask import current_app
from werkzeug.exceptions import abort

from cmdb.database import MongoDatabaseManager

from cmdb.interface.route_utils import verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.blueprints import RootBlueprint
# -------------------------------------------------------------------------------------------------------------------- #

debug_blueprint = RootBlueprint('debug_rest', __name__, url_prefix='/debug')

with current_app.app_context():
    dbm: MongoDatabaseManager = current_app.database_manager

# -------------------------------------------------------------------------------------------------------------------- #

@debug_blueprint.route('/indexes/<string:collection>', methods=['GET'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_index(collection: str):
    """
    Retrieves index information for the specified collection

    This route allows you to query the index information of a given collection in the database.
    It returns metadata about the indexes available for the specified collection

    Args:
        collection (str): The name of the collection for which index information is being requested

    Returns:
        DefaultResponse: A JSON response containing the index information for the specified collection
    """
    return DefaultResponse(dbm.get_index_info(collection)).make_response()


@debug_blueprint.route('/error/<int:status_code>', methods=['GET', 'POST'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def trigger_error_handler(status_code: int):
    """
    Triggers an error response with the specified status code.

    This route allows you to trigger a specific HTTP error by providing the status code in the URL. 
    It's useful for testing error handling in your application.

    Args:
        status_code (int): The HTTP status code to trigger, e.g., 400, 404, 500, etc

    Returns:
        Response: An error response with the provided status code
    """
    abort(status_code)


@debug_blueprint.route('/error/<int:status_code>/<string:description>', methods=['GET', 'POST'])
def trigger_error_handler_with_description(status_code: int, description: str):
    """
    Triggers an error response with the specified status code and description

    This route allows you to trigger a specific HTTP error along with a custom description.
    It's useful for testing error handling with more detailed error messages.

    Args:
        status_code (int): The HTTP status code to trigger, e.g., 400, 404, 500, etc
        description (str): A custom error message or description to accompany the status code

    Returns:
        Response: An error response with the provided status code and description
    """
    abort(status_code, description=description)
