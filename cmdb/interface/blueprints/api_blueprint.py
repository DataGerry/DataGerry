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
Implementation of APIBlueprint
"""
from functools import wraps
from logging import Logger, getLogger
from typing import Any
from cerberus import Validator #type: ignore
from flask import Blueprint, abort, request, current_app
from werkzeug.exceptions import HTTPException

from cmdb.manager import UsersManager

from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.route_utils import user_has_right, parse_authorization_header
from cmdb.models.user_model import CmdbUser
from cmdb.security.token.validator import TokenValidator

from cmdb.errors.security import TokenValidationError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 APIBlueprint - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class APIBlueprint(Blueprint):
    """
    Wrapper class for Blueprints with nested elements
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    @staticmethod
    def protect(auth: bool = True, right: str = None, excepted: dict = None):
        """
        Active auth and right protection for flask routes
        """
        def _protect(f):
            @wraps(f)
            def _decorate(*args, **kwargs):
                if auth and right:
                    request_user = None

                    if current_app.cloud_mode and "x-api-key" in request.headers:
                        request_user = kwargs['request_user']

                    if not user_has_right(right, request_user):
                        if excepted:
                            if request_user:
                                user_dict = CmdbUser.to_json(request_user)

                                for exe_key, exe_value in excepted.items():
                                    try:
                                        route_parameter = kwargs[exe_value]
                                    except KeyError:
                                        abort(403, f'User has not the required right {right}')

                                    if exe_key not in user_dict:
                                        abort(403, f'User has not the required right {right}')

                                    if user_dict[exe_key] == route_parameter:
                                        return f(*args, **kwargs)

                            else:
                                with current_app.app_context():
                                    users_manager = UsersManager(current_app.database_manager)

                                token = parse_authorization_header(request.headers['Authorization'])

                                try:
                                    decrypted_token = TokenValidator(current_app.database_manager).decode_token(token)
                                except TokenValidationError:
                                    abort(401, "Invalid Token")

                                try:
                                    user_id = decrypted_token['DATAGERRY']['value']['user']['public_id']

                                    if current_app.cloud_mode:
                                        database = decrypted_token['DATAGERRY']['value']['user']['database']
                                        users_manager = UsersManager(current_app.database_manager, database)

                                    user_dict: dict = CmdbUser.to_json(users_manager.get_user(user_id))

                                    for exe_key, exe_value in excepted.items():
                                        try:
                                            route_parameter = kwargs[exe_value]
                                        except KeyError:
                                            abort(403, f'User has not the required right {right}')

                                        if exe_key not in user_dict:
                                            abort(403, f'User has not the required right {right}')

                                        if user_dict[exe_key] == route_parameter:
                                            return f(*args, **kwargs)
                                except HTTPException as http_err:
                                    raise http_err
                                except Exception:
                                    abort(403, "Could not retrieve user!")

                        abort(403, f'User has not the required right {right}')

                return f(*args, **kwargs)

            return _decorate

        return _protect


    @classmethod
    def validate(cls, schema: dict[str, Any]):
        """
        Decorator to validate incoming JSON request data against a provided schema

        Args:
            schema (dict, optional): A validation schema used by the Cerberus Validator
                                    Defines the required structure and rules for the incoming data

        Returns:
            function: A decorator that injects validated and normalized data into the decorated function

        Raises:
            400 Bad Request:
                - If the incoming request body is not valid JSON
                - If the data does not conform to the provided schema
        """
        validator = Validator(schema, purge_unknown=True)

        def _validate(f):
            @wraps(f)
            def _decorate(*args, **kwargs):
                data = request.get_json()
                # LOGGER.debug("validation data: %s", data)
                try:
                    validation_result = validator.validate(data)
                except Exception as err:
                    LOGGER.error("[validate] Exception %s. Type: %s", err, type(err), exc_info=True)
                    abort(400, f"Schema '{schema}' validation failed")

                if not validation_result:
                    LOGGER.error("[VALIDATION] Error: %s", validator.errors or "No validation errors found!")
                    abort(400, "Invalid data provided!")

                return f(data=validator.document, *args, **kwargs)

            return _decorate

        return _validate


    @classmethod
    def parse_parameters(cls, parameters_class, **optional):
        """
        Decorator to parse and validate HTTP request query parameters using a specified parameters class

        Args:
            parameters_class (Type): A class that defines the structure and validation of the request parameters
            **optional: Additional optional keyword arguments to pass to the parameters class

        Returns:
            function: A decorator that injects parsed parameters into the decorated function

        Raises:
            400 Bad Request: If parameter parsing or validation fails
        """
        def _parse(f):
            @wraps(f)
            def _decorate(*args, **kwargs):
                try:
                    params = parameters_class.from_data(
                        str(request.query_string, 'utf-8'), **{**optional, **request.args.to_dict()}
                    )
                except Exception as err:
                    LOGGER.error("[parse_parameters] Exception %s. Type: %s", err, type(err))
                    abort(400, "Failed to parse the request parameters!")

                return f(params=params, *args, **kwargs)

            return _decorate

        return _parse


    @classmethod
    def parse_request_parameters(cls, **optional):
        """
        Decorator to extract raw HTTP request query parameters and pass them to the decorated function

        Args:
            **optional: (Currently unused) Additional optional keyword arguments

        Returns:
            function: A decorator that injects request query parameters as a dictionary into the decorated function

        Raises:
            400 Bad Request: If request argument extraction fails
        """
        def _parse(f):
            @wraps(f)
            def _decorate(*args, **kwargs):
                try:
                    request_args = request.args.to_dict()
                except Exception as err:
                    LOGGER.error("[parse_request_parameters] Exception %s. Type: %s", err, type(err))
                    abort(400, "Failed to parse the request parameters!")

                return f(params=request_args, *args, **kwargs)

            return _decorate

        return _parse


    @classmethod
    def parse_collection_parameters(cls, **optional):
        """
        Wrapper function for the flask routes.
        Auto parses the collection based parameters to the route.

        TODO:
            Move to global method like up.

        Args:
            **optional: dict of optional collection parameters for given route function.
        """
        def _parse(f):
            @wraps(f)
            def _decorate(*args, **kwargs):
                try:
                    params = CollectionParameters.from_data(
                        str(request.query_string, 'utf-8'), **{**optional, **request.args.to_dict()}
                    )
                except Exception as err:
                    LOGGER.error("[parse_collection_parameters] Exception %s. Type: %s", err, type(err))
                    abort(400, "Failed to parse the request parameters!")

                return f(params=params, *args, **kwargs)

            return _decorate

        return _parse
