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
This managers represents the core functionalities for the use of CMDB objects.
All communication with the objects is controlled by this managers.
The implementation of the managers used is always realized using the respective superclass.
"""
from logging import Logger, getLogger
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 LocationNode - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class LocationNode:
    """
    Represents a node in the location tree
    """
    #TODO: REFACTOR-FIX (Specific errors)
    def __init__(self, params: dict):
        """
        Initialize a LocationNode

        Args:
            params (dict): Dictionary containing location information
        """
        self.public_id: int = params['public_id']
        self.name: str = params['name']
        self.parent: int = params['parent']
        self.icon: str = params['type_icon']
        self.object_id: int = params['object_id']
        self.children: list[LocationNode] = []


    def get_children(self, public_id:int, locations_list: list[dict]) -> list['LocationNode']:
        """
        Recursively retrieve all children for a given location

        Args:
            public_id (int): The public ID of the parent location
            locations_list (list[dict]): List of all location entries

        Returns:
            list[LocationNode]: A list of child LocationNode instances
        """
        sorted_children: list["LocationNode"] = []
        filtered_list: list[dict] = []

        if len(locations_list) > 0:
            for location in locations_list:
                if location['parent'] == public_id:
                    sorted_children.append(LocationNode(location))
                else:
                    filtered_list.append(location)

            if len(filtered_list) > 0:
                for child in sorted_children:
                    child.children = self.get_children(child.get_public_id(), filtered_list)

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
        return f"[LocationNode => public_id: {self.public_id}, \
                                  name: {self.name}, \
                                  parent: {self.parent}, \
                                  icon: {self.icon}, \
                                  object_id: {self.object_id}, \
                                  children: {len(self.children)}]"


    @classmethod
    def to_json(cls, instance: "LocationNode") -> dict:
        """
        Convert a LocationNode instance into a JSON-serializable dictionary

        Args:
            instance (LocationNode): The LocationNode instance to convert

        Returns:
            dict: JSON-compatible dictionary representation of the node
        """
        json_data = {
            'public_id': instance.public_id,
            'name': instance.name,
            'parent': instance.parent,
            'icon': instance.icon,
            'object_id': instance.object_id,
        }

        # convert children to json
        children = []
        if len(instance.children) > 0:
            for child in instance.children:
                children.append(cls.to_json(child))

        # if there are any children then append the children-key
        if len(children) > 0:
            json_data['children'] = children

        return json_data
