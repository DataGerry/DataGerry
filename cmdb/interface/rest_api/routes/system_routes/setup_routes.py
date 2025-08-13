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
These routes are used to setup databases and the correspondig user in DataGerry
"""
import logging
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    delete_database,
    verify_api_access,
)

from cmdb.errors.database import DatabaseNotFoundError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

setup_blueprint = APIBlueprint('setup', __name__)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

#TODO: REFACTOR-FIX (create specific errors)
@setup_blueprint.route('/subscriptions', methods=['DELETE'])
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
def delete_subscription() -> Response:
    """
    Deletes a subscription

    Hint:
    Expects a dict with the following keys:
    {
        "database"(str): Name of database
    }
    """
    try:
        if not request.args:
            abort(400, "No request arguments provided!")

        delete_data: dict = request.args.to_dict()

        try:
            subscrption_database = delete_data['database']
        except KeyError:
            abort(400, "Database name was not provided!")

        try:
            delete_database(subscrption_database)
        except DatabaseNotFoundError:
            abort(400, f"The database with the name {subscrption_database} does not exist!")
        except Exception as err:
            LOGGER.error("[delete_subscription] Error: %s, Type: %s", err, type(err))
            abort(400, "An issue occured while deleting the subscription!")

        return DefaultResponse(True).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[delete_subscription] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while deleting the subscription!")
