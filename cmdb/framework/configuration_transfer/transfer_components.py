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
The components of a configuration transfer and the order they are imported in

    section templates   the user's own - the predefined ones are DataGerry's, seeded from code on every system
    types               reference section templates (a type's copy of a global template names it)
    categories          name the types they hold (and their parent category)
    relations           name the types on either side

`TRANSFER_COMPONENTS` is the one registry: the export writes a section per entry, the envelope check expects
exactly these names, the import runs them in this order. A later part of DataGerry joins the transfer by one class
here
"""
from typing import Any

from cmdb.manager.manager_provider_model.manager_type_enum import ManagerType
from cmdb.models.type_model import CmdbType
from cmdb.models.category_model import CmdbCategory
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    NOT_PREDEFINED,
    TransferComponentName,
)
from cmdb.framework.configuration_transfer.transfer_component import TransferComponent
# -------------------------------------------------------------------------------------------------------------------- #

class SectionTemplateComponent(TransferComponent):
    """The user's section templates - every template not flagged predefined"""
    NAME = TransferComponentName.SECTION_TEMPLATES
    MANAGER_TYPE = ManagerType.SECTION_TEMPLATES
    COLLECTION = CmdbSectionTemplate.COLLECTION
    EXPORT_CRITERIA: dict[str, Any] = {SectionTemplateKey.PREDEFINED.value: NOT_PREDEFINED}


class TypeComponent(TransferComponent):
    """Every CmdbType - stored with the importing system's default ACL and the importing user as its author"""
    NAME = TransferComponentName.TYPES
    DEPENDS_ON = (TransferComponentName.SECTION_TEMPLATES,)
    MANAGER_TYPE = ManagerType.TYPES
    COLLECTION = CmdbType.COLLECTION


    def prepare_item(self, item: dict[str, Any], author_id: int) -> dict[str, Any]:
        """
        Replaces what the exporting system owned: the ACL (its groups are not this system's) and the authorship

        The ACL becomes the default - switched off, so the type is governed by the rights alone. The author becomes
        the importing user, and so does the editor of a type that had one

        Args:
            item (dict[str, Any]): The type entry
            author_id (int): public_id of the importing user

        Returns:
            dict[str, Any]: The type document to store
        """
        document: dict[str, Any] = dict(item)
        document[TypeSchemaKey.ACL.value] = AccessControlList.default_json()
        document[TypeSchemaKey.AUTHOR_ID.value] = author_id

        if document.get(TypeSchemaKey.EDITOR_ID.value) is not None:
            document[TypeSchemaKey.EDITOR_ID.value] = author_id

        return document


class CategoryComponent(TransferComponent):
    """Every CmdbCategory"""
    NAME = TransferComponentName.CATEGORIES
    DEPENDS_ON = (TransferComponentName.TYPES,)
    MANAGER_TYPE = ManagerType.CATEGORIES
    COLLECTION = CmdbCategory.COLLECTION


class RelationComponent(TransferComponent):
    """Every CmdbRelation"""
    NAME = TransferComponentName.RELATIONS
    DEPENDS_ON = (TransferComponentName.TYPES,)
    MANAGER_TYPE = ManagerType.RELATIONS
    COLLECTION = CmdbRelation.COLLECTION


# The import order: every component after the ones it depends on (pinned by `component_order_problems`)
TRANSFER_COMPONENTS: tuple[type[TransferComponent], ...] = (
    SectionTemplateComponent,
    TypeComponent,
    CategoryComponent,
    RelationComponent,
)

# The section names a transfer file carries, in import order
TRANSFER_COMPONENT_NAMES: tuple[str, ...] = tuple(component.NAME.value for component in TRANSFER_COMPONENTS)
