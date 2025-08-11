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
Implementation of NestedBlueprint
"""
import logging
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                NestedBlueprint - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class NestedBlueprint:
    """
    Blueprint wrapper that automatically prefixes all routes with a parent URL prefix.

    This is useful for grouping related routes under a common path without manually adding
    the prefix to each route.
    """
    def __init__(self, blueprint, url_prefix: str):
        """
        Initialize the NestedBlueprint

        Args:
            blueprint (Blueprint): The Flask Blueprint instance to wrap
            url_prefix (str): The URL prefix to add to all routes in the blueprint
        """
        self.blueprint = blueprint
        self.prefix = '/' + url_prefix
        super().__init__()


    def route(self, rule, **options):
        """
        Register a new route on the wrapped blueprint with the parent URL prefix applied

        Args:
            rule (str): The URL rule as a string (e.g., '/list', '/create')
            **options: Additional options to pass to the Flask Blueprint `route` method (e.g., methods, endpoint)

        Returns:
            function: The original route decorator from the underlying blueprint, now with the prefix applied
        """
        rule = self.prefix + rule
        return self.blueprint.route(rule, **options)
