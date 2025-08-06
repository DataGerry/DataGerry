# DATAGERRY - OpenSource Enterprise CMDB
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
Implementation of APIProjector
"""
from logging import getLogger

from cmdb.interface.rest_api.responses.helpers.api_projection import APIProjection

from cmdb.errors.api_projection import APIProjectionInclusionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 APIProjector - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class APIProjector:
    """
    Converts the API Responses based on the ApiProjection mapping.
    """

    def __init__(self, data: dict | list[dict], projection: APIProjection = None):
        self._output = None
        self.__data = data
        self.__projection = projection


    @property
    def project(self) -> dict:
        """
        Outputs the projected data
        """
        if not self._output:
            self._output = self.__project_output()
        return self._output


    def __project_output(self) -> dict | list[dict]:
        """
        Generate the output from the the api result or results
        W"""
        if not self.__projection:
            return self.__data

        if isinstance(self.__data, list):
            output = []
            for element in self.__data:
                output.append(self.__parse_element(element))
        else:
            output = self.__parse_element(self.__data)

        return output


    @staticmethod
    def element_includes(include_key: str, element: dict) -> dict:
        """Get the dict value if an elements has the include key"""
        if '.' not in include_key:
            try:
                return {include_key: element[include_key]}
            except (KeyError, ValueError, TypeError) as err:
                raise APIProjectionInclusionError(
                    f'Projected element does not include the key: {include_key} | Error: {err}'
                ) from err

        key, rest = include_key.split('.', 1)
        if isinstance(element[key], list):
            return {key: [APIProjector.element_includes(rest, e) for e in element[key]]}

        return {key: APIProjector.element_includes(rest, element[key])}


    def __parse_element(self, data: dict) -> dict:
        """Converts a single resource based on projection."""
        element = {}
        if not isinstance(data, dict):
            raise TypeError('Project elements must be a dict!')

        if self.__projection.has_includes():
            for include in self.__projection.includes:
                try:
                    element.update(self.element_includes(include, data))
                except APIProjectionInclusionError:
                    continue
        else:
            element = data

        if self.__projection.has_excludes():
            for key, _ in element.copy().items():
                if key in self.__projection.excludes:
                    del element[key]

        return element
