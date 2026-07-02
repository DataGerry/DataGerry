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
Implementation of RootBlueprint
"""
from functools import wraps
from logging import Logger, getLogger
from flask import Blueprint, abort, request
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 RootBlueprint - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class RootBlueprint(Blueprint):
    """Wrapper class for Blueprints with nested elements"""
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.nested_blueprints = []


    def register_nested_blueprint(self, nested_blueprint) -> None:
        """Add a 'sub' blueprint to root element
        Args:
            nested_blueprint (NestedBlueprint): Blueprint for sub routes
        """
        self.nested_blueprints.append(nested_blueprint)


    @classmethod
    def parse_assistant_parameters(cls, **optional):
        """
        Decorator to parse and extract parameters from an HTTP request

        This class method returns a decorator that:
        - Extracts query parameters from the current request (via `request.args.to_dict()`)
        - Passes the extracted parameters as a dictionary to the decorated function
        - Aborts with a 400 Bad Request if the parameters cannot be parsed

        Args:
            **optional: 
                Placeholder for optional keyword arguments (currently unused)

        Raises:
            400 Bad Request: 
                If there is an error while accessing or parsing the request arguments

        Returns:
            Callable: 
                A decorator that injects parsed request parameters into the decorated function
        """
        def _parse(f):
            @wraps(f)
            def _decorate(*args, **kwargs):
                try:
                    location_args = request.args.to_dict()
                except Exception as err:
                    LOGGER.error("[parse_arguments] Exception: %s. Type: %s", err, type(err), exc_info=True)
                    abort(400, "Failed to parse the request arguments!")

                return f(location_args)

            return _decorate

        return _parse
