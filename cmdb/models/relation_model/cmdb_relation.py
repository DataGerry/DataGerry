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
Represents a CmdbRelation in DataGerry
"""
from logging import Logger, getLogger

from cmdb.class_schema.cmdb_relation_schema import get_cmdb_relation_schema

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.type_model.type_field_section import TypeFieldSection

from cmdb.errors.models.cmdb_relation import (
    CmdbRelationInitError,
    CmdbRelationInitFromDataError,
    CmdbRelationToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CmdbRelation - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
#pylint: disable=too-many-instance-attributes
class CmdbRelation(CmdbDAO):
    """
    Implementation of a CmdbRelation in DataGerry

    Extends: CmdbDAO
    """
    COLLECTION = "framework.relations"
    MODEL = 'Relation'
    SCHEMA: dict = get_cmdb_relation_schema()

    #pylint: disable=R0913, R0917
    def __init__(self,
                 public_id: int,
                 relation_name: str,
                 parent_type_ids: list[int],
                 child_type_ids: list[int],
                 relation_name_parent: str,
                 relation_name_child: str,
                 description: str = None,
                 relation_icon_parent: str  = None,
                 relation_color_parent: str  = None,
                 relation_icon_child: str  = None,
                 relation_color_child: str  = None,
                 sections: list[TypeFieldSection] = None,
                 fields: list[dict] = None):
        """
        Initialises a CmdbRelation

        Args:
            public_id (int): public_id of the CmdbRelation
            relation_name (str): Name of the CmdbRelation
            parent_type_ids (list[int]): public_ids of allowed parent CmdbTypes
            child_type_ids (list[int]): public_ids of allowed child CmdbTypes
            relation_name_parent (str): Name of parent to child relation
            relation_name_child (str): Name of child to parent relation
            description (str, optional): General description of the Relation. Defaults to None
            relation_icon_parent (str, optional): Icon of the parent to child relation. Defaults to None
            relation_color_parent (str, optional): Color of the parent to child relation. Defaults to None
            relation_icon_child (str, optional): Icon of the child to parent relation. Defaults to None
            relation_color_child (str, optional): Color of the child to parent relation. Defaults to None
            sections (list[dict], optional): all sections of CmdbRelation. Defaults to None
            fields (list[dict], optional): fields of CmdbRelation. Defaults to None

        Raises:
            CmdbRelationInitError: When the CmdbRelation could not be initialised
        """
        try:
            self.relation_name = relation_name
            self.parent_type_ids = parent_type_ids
            self.child_type_ids = child_type_ids
            self.relation_name_parent = relation_name_parent
            self.relation_name_child = relation_name_child
            self.description = description
            self.relation_icon_parent = relation_icon_parent
            self.relation_color_parent = relation_color_parent
            self.relation_icon_child = relation_icon_child
            self.relation_color_child = relation_color_child
            self.sections = sections
            self.fields = fields

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbRelationInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbRelation":
        """
        Initialises a CmdbRelation from a dict

        Args:
            data (dict): Data with which the CmdbRelation should be initialised

        Raises:
            CmdbRelationInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbRelation: CmdbRelation with the given data
        """
        try:
            sections: list[TypeFieldSection] = []
            for section in data.get('sections', []):
                sections.append(TypeFieldSection.from_data(section))

            return cls(
                public_id = data.get('public_id'),
                relation_name = data.get('relation_name'),
                parent_type_ids = data.get('parent_type_ids'),
                child_type_ids = data.get('child_type_ids'),
                relation_name_parent = data.get('relation_name_parent'),
                relation_name_child = data.get('relation_name_child'),
                description = data.get('description', None),
                relation_icon_parent = data.get('relation_icon_parent', None),
                relation_color_parent = data.get('relation_color_parent', None),
                relation_icon_child = data.get('relation_icon_child', None),
                relation_color_child = data.get('relation_color_child', None),
                fields = data.get('fields', None) or [],
                sections = sections,
            )
        except Exception as err:
            raise CmdbRelationInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbRelation") -> dict:
        """
        Converts a CmdbRelation into a json compatible dict

        Args:
            instance (CmdbRelation): The CmdbRelation which should be converted

        Raises:
            CmdbRelationToJsonError: If the CmdbRelation could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the CmdbRelation values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'relation_name': instance.relation_name,
                'parent_type_ids': instance.parent_type_ids,
                'child_type_ids': instance.child_type_ids,
                'relation_name_parent': instance.relation_name_parent,
                'relation_name_child': instance.relation_name_child,
                'description': instance.description,
                'relation_icon_parent': instance.relation_icon_parent,
                'relation_color_parent': instance.relation_color_parent,
                'relation_icon_child': instance.relation_icon_child,
                'relation_color_child': instance.relation_color_child,
                'sections': [section.to_json(section) for section in instance.sections],
                'fields': instance.fields,
            }
        except Exception as err:
            raise CmdbRelationToJsonError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def remove_type_id_from_relation(self, target_type_id: int) -> None:
        """
        Removes the CmdbType public_id from the CmdbRelation

        Args:
            target_type_id (int): public_id of the CmdbType which should be removed from the CmdbRelation
        """
        if target_type_id in self.child_type_ids:
            self.child_type_ids.remove(target_type_id)

        if target_type_id in self.parent_type_ids:
            self.parent_type_ids.remove(target_type_id)
