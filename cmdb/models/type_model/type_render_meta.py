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
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: Which section class builds a stored section, chosen by its `type` key. A `type` this version does
#: not know - or a document written before the key existed - falls back to TypeFieldSection rather
#: than being refused or dropped: refusing would make a type saved by a newer version unreadable, and
#: dropping would silently lose the section's fields
SECTION_CLASSES: dict[str, type[TypeSection]] = {
    SectionType.SECTION.value: TypeFieldSection,
    SectionType.MDS_SECTION.value: TypeMultiDataSection,
    SectionType.REF_SECTION.value: TypeReferenceSection,
}

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
        sections: list[TypeSection] = [
            SECTION_CLASSES.get(section.get(SectionKey.TYPE.value), TypeFieldSection).from_data(section)
            for section in data.get(TypeSchemaKey.SECTIONS.value, [])
        ]

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
