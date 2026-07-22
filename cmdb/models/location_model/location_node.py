# DATAGERRY - OpenSource Enterprise CMDB
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
This module contains the implementation of LocationNode

A LocationNode is the in-memory tree representation of a single CmdbLocation. The
``/locations/tree`` route builds a forest of these nodes (see ``build_location_forest`` in the
CmdbLocation route helpers) and serializes it back to nested, JSON-compatible dicts.
"""
<<<<<<< HEAD
from logging import Logger, getLogger
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)
=======
from typing import Any

from cmdb.errors.models.cmdb_location import LocationNodeInitError
# -------------------------------------------------------------------------------------------------------------------- #
>>>>>>> origin/version-3.2

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 LocationNode - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class LocationNode:
    """
    Represents a node in the location tree
    """
    def __init__(self, params: dict[str, Any]):
        """
        Initialise a LocationNode from a CmdbLocation dict

        Args:
            params (dict[str, Any]): CmdbLocation data; must provide the keys ``public_id``,
                ``name``, ``parent``, ``type_icon`` and ``object_id``

        Raises:
            LocationNodeInitError: If any of the required keys is missing from ``params``
        """
        try:
            self.public_id: int = params['public_id']
            self.name: str = params['name']
            self.parent: int = params['parent']
            self.icon: str = params['type_icon']
            self.object_id: int = params['object_id']
            self.children: list[LocationNode] = []
        except KeyError as err:
            raise LocationNodeInitError(f"Missing required location key: {err}") from err


    def get_children(self, public_id: int, locations_list: list[dict]) -> list['LocationNode']:
        """
        Recursively retrieve all children for a given location

        Builds a ``parent -> [locations]`` index once so each recursion level is an O(1) lookup
        instead of a full re-scan of ``locations_list`` (O(n) total instead of O(n^2)). A
        ``visited`` set guards against parent cycles in the data so a malformed chain cannot
        cause infinite recursion

        Args:
            public_id (int): The public ID of the parent location
            locations_list (list[dict]): List of all location entries

        Returns:
            list[LocationNode]: A list of child LocationNode instances
        """
        children_by_parent: dict[int, list[dict]] = {}

        for location in locations_list:
            children_by_parent.setdefault(location['parent'], []).append(location)

        return self._build_children(public_id, children_by_parent, set())


    def _build_children(
            self,
            public_id: int,
            children_by_parent: dict[int, list[dict]],
            visited: set[int]) -> list['LocationNode']:
        """
        Recursively builds the child LocationNodes for a parent using a prebuilt parent index

        Args:
            public_id (int): The public ID of the parent location
            children_by_parent (dict[int, list[dict]]): Index mapping a parent public_id to its
                direct child location entries
            visited (set[int]): public_ids already expanded, used to break parent cycles

        Returns:
            list[LocationNode]: A list of child LocationNode instances
        """
        if public_id in visited:
            return []

        visited.add(public_id)

        sorted_children: list["LocationNode"] = [
            LocationNode(location)
            for location in children_by_parent.get(public_id, [])
            if location['public_id'] not in visited
        ]

        for child in sorted_children:
            child.children = self._build_children(child.get_public_id(), children_by_parent, visited)

        return sorted_children


    def get_public_id(self) -> int:
        """
        Retrieve the public ID of this LocationNode

        Returns:
            int: The public ID of the node
        """
        return self.public_id


    def __repr__(self) -> str:
        """
        Return a string representation of the LocationNode instance

        Returns:
            str: String representation of the node
        """
        return (
            f"[LocationNode => public_id: {self.public_id}, name: {self.name}, "
            f"parent: {self.parent}, icon: {self.icon}, object_id: {self.object_id}, "
            f"children: {len(self.children)}]"
        )


    @classmethod
    def to_json(cls, instance: "LocationNode") -> dict[str, Any]:
        """
        Convert a LocationNode instance into a JSON-serializable dictionary

        Child nodes are serialized recursively; the ``children`` key is only emitted when the
        node actually has children, keeping leaf nodes compact

        Args:
            instance (LocationNode): The LocationNode instance to convert

        Returns:
            dict[str, Any]: JSON-compatible dictionary representation of the node
        """
        json_data: dict[str, Any] = {
            'public_id': instance.public_id,
            'name': instance.name,
            'parent': instance.parent,
            'icon': instance.icon,
            'object_id': instance.object_id,
        }

        # Only emit the children key when the node has children
        if instance.children:
            json_data['children'] = [cls.to_json(child) for child in instance.children]

        return json_data
