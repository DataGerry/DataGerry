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
Implementation of APIProjector

`APIProjector` applies an `APIProjection` (the client-supplied `projection` query parameter)
to already-fetched API result document(s), trimming them down to the requested fields before
serialization. It supports two mutually independent modes driven by the projection values:

- **includes** (value ``1``): keep only the listed keys. Keys may be dotted paths
  (e.g. ``render_meta.sections``) which descend into nested dicts, and into every element of
  a nested list.
- **excludes** (value ``0``): drop the listed top-level keys.

Note: this trims documents in application memory *after* they have been loaded from MongoDB;
it does not push the projection into the database query. See the module consumers
(`GetSingleResponse` / `GetListResponse` / `GetMultiResponse`) for where it is invoked.
"""
from logging import Logger, getLogger

from cmdb.interface.rest_api.responses.helpers.api_projection import APIProjection

from cmdb.errors.api_projection import APIProjectionInclusionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 APIProjector - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class APIProjector:
    """
    Projects API response document(s) onto the fields selected by an `APIProjection`
    """

    def __init__(self, data: dict | list[dict], projection: APIProjection | None = None) -> None:
        """
        Stores the source data and the projection to apply

        Args:
            data (dict | list[dict]): The already-fetched result document, or a list of them
            projection (APIProjection | None): The projection to apply. When None, `project`
                returns the data unchanged
        """
        self.__output: dict | list[dict] | None = None
        self.__data: dict | list[dict] = data
        self.__projection: APIProjection | None = projection


    @property
    def project(self) -> dict | list[dict]:
        """
        Returns the projected data, computing it once and caching the result

        Returns:
            dict | list[dict]: The projected document, or list of projected documents, matching
                the shape of the input data
        """
        if self.__output is None:
            self.__output = self.__project_output()

        return self.__output


    def __project_output(self) -> dict | list[dict]:
        """
        Generates the output from the API result or results

        Returns:
            dict | list[dict]: The input data unchanged when no projection is set, otherwise the
                projected document(s) matching the shape of the input data
        """
        if not self.__projection:
            return self.__data

        if isinstance(self.__data, list):
            return [self.__parse_element(element) for element in self.__data]

        return self.__parse_element(self.__data)


    @staticmethod
    def element_includes(include_key: str, element: dict) -> dict:
        """
        Extracts a single (possibly dotted) include key from a document

        For a plain key the matching ``{key: value}`` pair is returned. For a dotted key the
        first segment is resolved and the remainder is applied recursively, descending into a
        nested dict or into every element of a nested list.

        Args:
            include_key (str): The include key, either a plain key or a dotted path
            element (dict): The document (or nested sub-document) to read from

        Returns:
            dict: A dict holding only the resolved key and its (recursively projected) value

        Raises:
            APIProjectionInclusionError: If any segment of the key is missing from the element
                or the element is not subscriptable at that segment
        """
        if '.' not in include_key:
            try:
                return {include_key: element[include_key]}
            except (KeyError, ValueError, TypeError) as err:
                raise APIProjectionInclusionError(
                    f'Projected element does not include the key: {include_key} | Error: {err}'
                ) from err

        key, rest = include_key.split('.', 1)

        try:
            value = element[key]
        except (KeyError, ValueError, TypeError) as err:
            raise APIProjectionInclusionError(
                f'Projected element does not include the key: {key} | Error: {err}'
            ) from err

        if isinstance(value, list):
            return {key: [APIProjector.element_includes(rest, entry) for entry in value]}

        return {key: APIProjector.element_includes(rest, value)}


    def __parse_element(self, data: dict) -> dict:
        """
        Projects a single document according to the projection's includes/excludes

        Args:
            data (dict): The document to project

        Returns:
            dict: The projected document. The input `data` is never mutated

        Raises:
            TypeError: If `data` is not a dict
        """
        if not isinstance(data, dict):
            raise TypeError('Project elements must be a dict!')

        if self.__projection.has_includes:
            element = {}
            for include in self.__projection.includes:
                try:
                    element.update(self.element_includes(include, data))
                except APIProjectionInclusionError:
                    continue
        else:
            # Shallow copy so exclude-only projections never mutate the caller's document
            element = dict(data)

        if self.__projection.has_excludes:
            for key in self.__projection.excludes:
                element.pop(key, None)

        return element
