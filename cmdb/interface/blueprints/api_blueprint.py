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
from typing import Any, Callable
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
    def _user_matches_excepted(excepted: dict, user_dict: dict, route_kwargs: dict, right: str) -> bool:
        """
        Check whether a user qualifies for an `excepted` carve-out from a required right

        For each entry in `excepted` (mapping a user-attribute key to a route-parameter name), the user
        is granted access when the value of that user attribute equals the corresponding route parameter
        (e.g. `{'public_id': 'public_id'}` lets a user act on their own record without holding the right)

        Args:
            excepted (dict): Mapping of user-attribute key -> route-parameter name to compare against
            user_dict (dict): Serialized user (`CmdbUser.to_json`) to read the attribute values from
            route_kwargs (dict): Keyword arguments passed to the decorated route (holds the route parameters)
            right (str): The required right, used only for the abort message

        Returns:
            bool: True if the user matches any excepted rule, False if no rule matched

        Raises:
            403 Forbidden: If a referenced route parameter is missing, or the user lacks the compared attribute
        """
        for exe_key, exe_value in excepted.items():
            try:
                route_parameter = route_kwargs[exe_value]
            except KeyError:
                abort(403, f'User has not the required right {right}')

            if exe_key not in user_dict:
                abort(403, f'User has not the required right {right}')

            if user_dict[exe_key] == route_parameter:
                return True

        return False


    @staticmethod
    def protect(auth: bool = True, right: str | None = None, excepted: dict | None = None) -> Callable:
        """
        Decorator enforcing authentication and right-based authorization on a Flask route

        Enforcement only runs when both `auth` is True and a `right` is given. The user is resolved either
        from an injected `request_user` (cloud `x-api-key` requests) or from the request's Authorization
        token. If the user lacks `right`, an optional `excepted` carve-out is consulted (see
        `_user_matches_excepted`) before access is denied.

        Args:
            auth (bool): Whether to enforce protection (combined with `right`). Defaults to True
            right (str | None): The required right. If None, the decorator performs no enforcement
            excepted (dict | None): Optional mapping of user-attribute key -> route-parameter name that
                                    grants access even without `right` when the values match

        Returns:
            Callable: A decorator that wraps the route with the auth/right check

        Raises:
            401 Unauthorized: If the Authorization header is missing or the token is invalid
            403 Forbidden: If the user lacks the required right and matches no excepted rule
        """
        def _protect(f):
            @wraps(f)
            def _decorate(*args, **kwargs):
                # The cloud/non-cloud + excepted-carve-out branches are inherently nested here
                if auth and right:  # pylint: disable=too-many-nested-blocks
                    request_user = None

                    if current_app.cloud_mode and "x-api-key" in request.headers:
                        request_user = kwargs['request_user']

                    if not user_has_right(right, request_user):
                        if excepted:
                            if request_user:
                                user_dict = CmdbUser.to_json(request_user)

                                if APIBlueprint._user_matches_excepted(excepted, user_dict, kwargs, right):
                                    return f(*args, **kwargs)
                            else:
                                auth_header = request.headers.get('Authorization')

                                if not auth_header:
                                    abort(401, "No Authorization header provided!")

                                token = parse_authorization_header(auth_header)

                                try:
                                    decrypted_token = TokenValidator(current_app.database_manager).decode_token(token)
                                except TokenValidationError:
                                    abort(401, "Invalid Token")

                                try:
                                    user_id = decrypted_token['DATAGERRY']['value']['user']['public_id']

                                    if current_app.cloud_mode:
                                        database = decrypted_token['DATAGERRY']['value']['user']['database']
                                        users_manager = UsersManager(current_app.database_manager, database)
                                    else:
                                        users_manager = UsersManager(current_app.database_manager)

                                    user_dict: dict = CmdbUser.to_json(users_manager.get_user(user_id))

                                    if APIBlueprint._user_matches_excepted(excepted, user_dict, kwargs, right):
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
    def parse_request_parameters(cls, **optional):  # pylint: disable=unused-argument
        # '**optional' is an extensibility placeholder, matching the other parameter decorators
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
    def parse_request_body(cls, **optional):  # pylint: disable=unused-argument
        # '**optional' is an extensibility placeholder, matching the other parameter decorators
        """
        Decorator to extract the JSON request body and pass it to the decorated function

        Args:
            **optional: (Currently unused) Additional optional keyword arguments

        Returns:
            function: A decorator that injects the parsed JSON body as a dictionary into the decorated function

        Raises:
            400 Bad Request: If the request body is missing or is not a valid JSON object
        """
        def _parse(f):
            @wraps(f)
            def _decorate(*args, **kwargs):
                payload = request.get_json(silent=True)

                if not isinstance(payload, dict):
                    LOGGER.error("[parse_request_body] Request body is not a valid JSON object")
                    abort(400, "Failed to parse the request body!")

                return f(data=payload, *args, **kwargs)

            return _decorate

        return _parse


    @classmethod
    def parse_collection_parameters(cls, **optional):
        """
        Decorator to parse and validate HTTP request query parameters into a CollectionParameters instance

        Args:
            **optional: Additional optional keyword arguments (e.g. default sort/limit) merged into the
                        parsed collection parameters

        Returns:
            function: A decorator that injects the parsed CollectionParameters into the decorated function

        Raises:
            400 Bad Request: If parameter parsing or validation fails
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
