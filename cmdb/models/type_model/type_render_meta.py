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
This class represents type render meta
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.type_model.type_section import TypeSection
from cmdb.models.type_model.type_external_link import TypeExternalLink
from cmdb.models.type_model.type_summary import TypeSummary
from cmdb.models.type_model.type_field_section import TypeFieldSection
from cmdb.models.type_model.type_reference_section import TypeReferenceSection
from cmdb.models.type_model.type_multi_data_section import TypeMultiDataSection
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    TypeRenderMeta                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TypeRenderMeta:
    """
    Class of the type models `render_meta` field
    """

    def __init__(
        self,
        icon: str | None = None,
        sections: list[TypeSection] | None = None,
        externals: list[TypeExternalLink] | None = None,
        summary: TypeSummary | None = None
    ) -> None:
        """TODO: document"""
        self.icon: str | None = icon
        self.sections: list[TypeSection] = sections or []
        self.externals: list[TypeExternalLink] = externals or []
        self.summary: TypeSummary = summary or TypeSummary()

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "TypeRenderMeta":
        """
        Generates a TypeRenderMeta object from a dict

        Args:
            data (dict): Data with which the TypeRenderMeta should be instantiated

        Returns:
            TypeRenderMeta: TypeRenderMeta class with given data
        """
        sections: list[TypeSection] = []

        for section in data.get('sections', []):
            section_type = section.get('type', 'section')
            if section_type == 'section':
                sections.append(TypeFieldSection.from_data(section))
            elif section_type == 'multi-data-section':
                sections.append(TypeMultiDataSection.from_data(section))
            elif section_type == 'ref-section':
                sections.append(TypeReferenceSection.from_data(section))
            else:
                sections.append(TypeFieldSection.from_data(section))

        return cls(
            icon=data.get('icon'),
            sections=sections,
            externals=[TypeExternalLink.from_data(external) for external in
                       data.get('externals') or data.get('external', [])],
            summary=TypeSummary.from_data(data.get('summary', {}))
        )


    @classmethod
    def to_json(cls, instance: "TypeRenderMeta") -> dict[str, Any]:
        """
        Returns a TypeRenderMeta as JSON representation

        Args:
            instance (TypeRenderMeta): TypeRenderMeta which should be transformed
        Returns:
            dict: JSON representation of the given TypeRenderMeta
        """
        return {
            'icon': instance.icon,
            'sections': [section.to_json(section) for section in instance.sections],
            'externals': [TypeExternalLink.to_json(external) for external in instance.externals],
            'summary': TypeSummary.to_json(instance.summary)
        }
