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
  (e.g. ``render_meta.sections``) which descend into nested dicts, and into every entry of
  a nested list - an entry that lacks the rest stays as an empty dict. Several includes under
  one parent combine (``render_meta.icon`` + ``render_meta.sections``).
- **excludes** (value ``0``): drop the listed keys - dotted paths too, resolved the same way.

A key the document holds as it is wins over reading it as a path, and a dotted key is split at the
longest prefix the document holds: a field name may contain a dot (``fields.ip.address`` selects the
field named ``ip.address``).

Note: this trims documents in application memory *after* they have been loaded from MongoDB;
it does not push the projection into the database query. See the module consumers
(`GetSingleResponse` / `GetListResponse` / `GetMultiResponse`) for where it is invoked.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.interface.rest_api.responses.helpers.api_projection import APIProjection

from cmdb.errors.api_projection import APIProjectionInclusionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# What separates the segments of a projection path (``render_meta.sections``)
PATH_SEPARATOR: str = '.'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 APIProjector - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class APIProjector:
    """
    Projects API response document(s) onto the fields selected by an `APIProjection`
    """

    def __init__(self, data: dict[str, Any] | list[dict[str, Any]], projection: APIProjection | None = None) -> None:
        """
        Stores the source data and the projection to apply

        Args:
            data (dict[str, Any] | list[dict[str, Any]]): The already-fetched result document, or a list of them
            projection (APIProjection | None): The projection to apply. When None, `project`
                returns the data unchanged
        """
        self.__output: dict[str, Any] | list[dict[str, Any]] | None = None
        self.__data: dict[str, Any] | list[dict[str, Any]] = data
        self.__projection: APIProjection | None = projection


    @property
    def project(self) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Returns the projected data, computing it once and caching the result

        Returns:
            dict[str, Any] | list[dict[str, Any]]: The projected document, or list of projected documents, matching
                the shape of the input data
        """
        if self.__output is None:
            self.__output = self.__project_output()

        return self.__output


    def __project_output(self) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Generates the output from the API result or results

        Returns:
            dict[str, Any] | list[dict[str, Any]]: The input data unchanged when no projection is set, otherwise the
                projected document(s) matching the shape of the input data
        """
        if not self.__projection:
            return self.__data

        if isinstance(self.__data, list):
            return [self.__parse_element(element) for element in self.__data]

        return self.__parse_element(self.__data)


    @staticmethod
    def split_key(key: str, element: dict[str, Any]) -> tuple[str, str] | None:
        """
        Splits a dotted projection key at the longest prefix the document holds as a key

        A key is read as a path, but a field name may itself hold a dot (``ip.address`` - the type builder derives
        names from labels). The longest prefix that exists wins, so ``fields.ip.address`` reaches the field named
        ``ip.address`` under ``fields``; a document that holds both that name and a nested ``ip`` -> ``address``
        answers with the named one. The whole key is not a prefix - the caller checks for an exact key first

        Args:
            key (str): The projection key, dotted or not
            element (dict[str, Any]): The (sub-)document the key is applied to

        Returns:
            tuple[str, str] | None: The existing prefix and the rest of the key; None when no prefix of the key exists
        """
        segments: list[str] = key.split(PATH_SEPARATOR)

        for cut in range(len(segments) - 1, 0, -1):
            prefix: str = PATH_SEPARATOR.join(segments[:cut])

            if prefix in element:
                return prefix, PATH_SEPARATOR.join(segments[cut:])

        return None


    @staticmethod
    def element_includes(include_key: str, element: dict[str, Any]) -> dict[str, Any]:
        """
        Extracts a single (possibly dotted) include key from a document

        A key the document holds as it is - dotted or not - is that key. Otherwise the key is split at the longest
        prefix the document holds (``split_key``) and the rest is applied to its value: into a nested dict, or into
        every entry of a nested list. A list entry that lacks the rest is kept as an empty dict, so the other entries
        keep their data and their positions; only a list in which no entry has it fails the include

        Args:
            include_key (str): The include key, either a plain key or a dotted path
            element (dict[str, Any]): The document (or nested sub-document) to read from

        Returns:
            dict[str, Any]: A dict holding only the resolved key and its (recursively projected) value

        Raises:
            APIProjectionInclusionError: If the key reaches nothing in the element - a missing key, a value that is
                no document, or a list none of whose entries has it
        """
        if not isinstance(element, dict):
            raise APIProjectionInclusionError(
                f'Projected element does not include the key: {include_key} | Not a document: {type(element).__name__}'
            )

        if include_key in element:
            return {include_key: element[include_key]}

        split: tuple[str, str] | None = APIProjector.split_key(include_key, element)

        if split is None:
            raise APIProjectionInclusionError(f'Projected element does not include the key: {include_key}')

        key, rest = split
        value: Any = element[key]

        if isinstance(value, list):
            return {key: APIProjector.__include_in_entries(rest, value)}

        return {key: APIProjector.element_includes(rest, value)}


    @staticmethod
    def __include_in_entries(include_key: str, entries: list[Any]) -> list[dict[str, Any]]:
        """
        Applies an include key to every entry of a list, entry by entry

        Args:
            include_key (str): The rest of the include key, applied to each entry
            entries (list[Any]): The list the key descended into

        Returns:
            list[dict[str, Any]]: One projected entry per entry, an empty dict where the entry lacks the key

        Raises:
            APIProjectionInclusionError: If the list has entries and none of them has the key
        """
        projected: list[dict[str, Any]] = []
        found: bool = False

        for entry in entries:
            try:
                projected.append(APIProjector.element_includes(include_key, entry))
                found = True
            except APIProjectionInclusionError:
                projected.append({})

        if entries and not found:
            raise APIProjectionInclusionError(f'No list entry includes the key: {include_key}')

        return projected


    @staticmethod
    def merge_included(target: dict[str, Any], included: dict[str, Any]) -> None:
        """
        Merges one include's result into the projected document, combining includes under a shared parent

        ``render_meta.icon`` and ``render_meta.sections`` both answer ``{'render_meta': {...}}``; a plain update let
        the second replace the first. Two dicts under one key are merged key by key, two lists of projected entries
        entry by entry (one include's entries are the same list positions as the other's); anything else is set

        Args:
            target (dict[str, Any]): The projected document so far, modified in place
            included (dict[str, Any]): One include's result (``element_includes``)
        """
        for key, value in included.items():
            current: Any = target.get(key)

            if isinstance(current, dict) and isinstance(value, dict):
                merged: dict[str, Any] = dict(current)
                APIProjector.merge_included(merged, value)
                target[key] = merged
            elif isinstance(current, list) and isinstance(value, list) and len(current) == len(value):
                target[key] = [
                    APIProjector.__merged_entry(current_entry, entry) for current_entry, entry in zip(current, value)
                ]
            else:
                target[key] = value


    @staticmethod
    def __merged_entry(current: Any, entry: Any) -> Any:
        """
        Merges two projected list entries at the same position

        Args:
            current (Any): The entry the projection holds so far
            entry (Any): The same position's entry from another include

        Returns:
            Any: The two dicts merged, or the new entry when either is no dict
        """
        if not isinstance(current, dict) or not isinstance(entry, dict):
            return entry

        merged: dict[str, Any] = dict(current)
        APIProjector.merge_included(merged, entry)

        return merged


    @staticmethod
    def element_excludes(exclude_key: str, element: Any) -> Any:
        """
        Removes a single (possibly dotted) exclude key from a document, without mutating it

        Resolved like an include: a key the document holds as it is is that key, otherwise the longest existing
        prefix (``split_key``) and the rest applied to its value - a nested dict, or every entry of a nested list.
        Only the containers on the path are copied, so neither the caller's document nor a sub-document the
        projection shares with it is changed. A key that reaches nothing removes nothing

        Args:
            exclude_key (str): The exclude key, either a plain key or a dotted path
            element (Any): The document (or nested value) to remove it from

        Returns:
            Any: The element without the key - a new container on the path, the element itself when nothing matched
        """
        if isinstance(element, list):
            return [APIProjector.element_excludes(exclude_key, entry) for entry in element]

        if not isinstance(element, dict):
            return element

        if exclude_key in element:
            return {key: value for key, value in element.items() if key != exclude_key}

        split: tuple[str, str] | None = APIProjector.split_key(exclude_key, element)

        if split is None:
            return element

        key, rest = split

        return {**element, key: APIProjector.element_excludes(rest, element[key])}


    def __parse_element(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Projects a single document according to the projection's includes/excludes

        Args:
            data (dict[str, Any]): The document to project

        Returns:
            dict[str, Any]: The projected document. The input `data` is never mutated

        Raises:
            TypeError: If `data` is not a dict
        """
        if not isinstance(data, dict):
            raise TypeError('Project elements must be a dict!')

        if self.__projection.has_includes:
            element: dict[str, Any] = {}
            for include in self.__projection.includes:
                try:
                    self.merge_included(element, self.element_includes(include, data))
                except APIProjectionInclusionError:
                    continue
        else:
            # Shallow copy so exclude-only projections never mutate the caller's document
            element = dict(data)

        for exclude in self.__projection.excludes:
            element = self.element_excludes(exclude, element)

        return element
