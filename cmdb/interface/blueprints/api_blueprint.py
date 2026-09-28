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
from flask import Blueprint, abort, request

from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.route_utils import user_has_right
from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints.api_blueprint_constants import (
    PROTECT_WITHOUT_REQUEST_USER_MESSAGE,
    REQUEST_USER_KWARG,
    RIGHT_CHECK_FAILED_MESSAGE,
    VALIDATION_FAILED_MESSAGE,
)
from cmdb.interface.blueprints.schema_error_format import describe_schema_errors

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
            user_dict (dict): Serialized user (`CmdbUser.to_public_json`) to read the attribute values from
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
    def _user_is_excepted(excepted: dict | None, request_user: CmdbUser, route_kwargs: dict, right: str) -> bool:
        """
        Whether a user without the right still passes through the route's `excepted` carve-out

        Args:
            excepted (dict | None): The route's carve-out, or None when it has none
            request_user (CmdbUser): The authenticated user of the request
            route_kwargs (dict): Keyword arguments passed to the decorated route (holds the route parameters)
            right (str): The required right, used only for the abort message

        Returns:
            bool: True if the route has a carve-out and the user matches it
        """
        if not excepted:
            return False

        user_dict: dict[str, Any] = CmdbUser.to_public_json(request_user)

        return APIBlueprint._user_matches_excepted(excepted, user_dict, route_kwargs, right)


    @staticmethod
    def protect(auth: bool = True, right: str | None = None, excepted: dict | None = None) -> Callable:
        """
        Decorator refusing a route to a caller who lacks the route's right

        **A right gate, not an authentication step.** Authentication is `insert_request_user`'s job:
        it sits above this decorator on every route that carries it (a census test fails otherwise),
        resolves the user once and hands it in as ``request_user``, which is the user checked here -
        the token and the user are not read a second time. If the user lacks `right`, an optional
        `excepted` carve-out is consulted (see `_user_matches_excepted`) before access is denied.

        Enforcement runs when `right` is given. `auth` is vestigial: every route passes `auth=True`,
        and without a right the decorator checks nothing - a route without a right is authenticated
        by `insert_request_user` alone

        Args:
            auth (bool): Kept for the call sites; the check runs only when it is True. Defaults to True
            right (str | None): The required right. If None, the decorator performs no enforcement
            excepted (dict | None): Optional mapping of user-attribute key -> route-parameter name that
                                    grants access even without `right` when the values match

        Returns:
            Callable: A decorator that wraps the route with the right check

        Raises:
            403 Forbidden: If the user lacks the required right and matches no excepted rule
            500 Internal Server Error: If the route has no `insert_request_user` above this decorator,
                or the user's group could not be read - a failed check is not a missing right
        """
        def _protect(f):
            @wraps(f)
            def _decorate(*args, **kwargs):
                if auth and right:
                    request_user: CmdbUser | None = kwargs.get(REQUEST_USER_KWARG)

                    if request_user is None:
                        LOGGER.error("[protect] %s carries no insert_request_user above protect", f.__name__)
                        abort(500, PROTECT_WITHOUT_REQUEST_USER_MESSAGE)

                    try:
                        has_right: bool = user_has_right(right, request_user)
                    except Exception as err:
                        LOGGER.error("[protect] Right check for '%s' failed: %s", right, err, exc_info=True)
                        abort(500, RIGHT_CHECK_FAILED_MESSAGE)

                    if not has_right and not APIBlueprint._user_is_excepted(excepted, request_user, kwargs, right):
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
                - If the data does not conform to the provided schema: the message names each failing
                  field and why (see ``schema_error_format.describe_schema_errors``)
                - If the validator itself fails: a fixed message, the schema is never echoed
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
                    # The schema is internal, so the answer names nothing; the traceback is logged above
                    abort(400, f"{VALIDATION_FAILED_MESSAGE}!")

                if not validation_result:
                    LOGGER.error("[VALIDATION] Error: %s", validator.errors or "No validation errors found!")
                    # The reason goes back to the caller: a 400 that names nothing cannot be fixed
                    abort(400, describe_schema_errors(validator.errors))

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
                    abort(400, f"Failed to parse the request parameters: {err}")

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
                    abort(400, f"Failed to parse the request parameters: {err}")

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
            400 Bad Request: If parameter parsing or validation fails. The raised message is carried
                into the response: every rejection from this package states which parameter was wrong
                and why, and a filter refused by ``pipeline_guard`` names the stage or operator. A
                fixed message here reported a refused pipeline stage the same way it reported a
                mistyped page number
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
                    abort(400, f"Failed to parse the request parameters: {err}")

                return f(params=params, *args, **kwargs)

            return _decorate

        return _parse
