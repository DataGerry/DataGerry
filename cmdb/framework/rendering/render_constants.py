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
All constants for rendering in DataGerry
"""
from cmdb.utils import BaseStrEnum

from cmdb.models.type_model.type_reference_key_enum import TypeReferenceKey
# -------------------------------------------------------------------------------------------------------------------- #

ANONYMOUS_NAME = 'unknown'


class RenderedFieldKey(BaseStrEnum):
    """
    Enumeration of the expansion keys a renderer ADDS to a field entry

    A rendered field starts out as the field definition of a CmdbType (whose keys are covered by
    `FieldKey`) and is then enriched by `CmdbMultiRender` with the resolved data behind a reference.
    Those extra keys live only on the render output — never on the stored type or object document —
    which is why they are not part of `FieldKey` / `CmdbObjectKey`. Use these members instead of bare
    string literals when reading a rendered field so a typo becomes an AttributeError instead of a
    silently missing expansion
    """
    #: Set on a `FieldType.REFERENCE` field; holds the referenced object's expansion
    REFERENCE = 'reference'
    #: List of the referenced object's summary fields, inside `REFERENCE`. Derived from the enum that
    #: owns that payload (`TypeReference.to_json` produces it) so the two cannot drift; it is
    #: repeated here because a caller reading a rendered FIELD reaches for this enum first
    SUMMARIES = TypeReferenceKey.SUMMARIES.value
    #: Set on a `FieldType.REF_SECTION` field; holds the pulled-in section's expansion
    REFERENCES = 'references'
    #: List of the pulled-in fields, inside `REFERENCES`
    FIELDS = 'fields'


class RenderObjectInfoKey(BaseStrEnum):
    """
    Enumeration of the keys inside a `RenderResult.object_information` block

    `CmdbMultiRender` copies these off the stored CmdbObject (plus the resolved author / editor
    names) into the render output. They mirror `CmdbObjectKey` members but live on the RENDER
    result, not on the stored document - `OBJECT_ID` in particular is the object's `public_id`
    under a different name - so reading them through this enum keeps a consumer from reaching for
    `CmdbObjectKey` and quietly getting the wrong key

    Attributes:
        OBJECT_ID: The rendered object's public_id
        CREATION_TIME: When the object was created
        LAST_EDIT_TIME: When the object was last edited, or None
        AUTHOR_ID: public_id of the creating user
        AUTHOR_NAME: Display name resolved for AUTHOR_ID
        EDITOR_ID: public_id of the last editing user, or None
        EDITOR_NAME: Display name resolved for EDITOR_ID
        ACTIVE: The object's active flag
        VERSION: The object's version string
        SPECIAL_TYPE: The SpecialType marker of the object's type, or an empty value
    """
    OBJECT_ID = 'object_id'
    CREATION_TIME = 'creation_time'
    LAST_EDIT_TIME = 'last_edit_time'
    AUTHOR_ID = 'author_id'
    AUTHOR_NAME = 'author_name'
    EDITOR_ID = 'editor_id'
    EDITOR_NAME = 'editor_name'
    ACTIVE = 'active'
    VERSION = 'version'
    SPECIAL_TYPE = 'special_type'


class RenderTypeInfoKey(BaseStrEnum):
    """
    Enumeration of the keys inside a `RenderResult.type_information` block

    `CmdbMultiRender` copies these off the rendered object's CmdbType (plus the resolved author
    name) into the render output. The block is a CURATED selection, not a dump of the type: a
    CmdbType carries far more than this, and only what a client rendering an object needs is
    forwarded - which is why a flag added to `CmdbType` does not appear here on its own and has to
    be added deliberately.

    They mirror `TypeSchemaKey` members but live on the RENDER result, not on the stored document -
    `TYPE_ID`, `TYPE_NAME` and `TYPE_LABEL` in particular are the type's `public_id` / `name` /
    `label` under different names - so reading them through this enum keeps a consumer from reaching
    for `TypeSchemaKey` and quietly getting the wrong key

    Attributes:
        TYPE_ID: public_id of the object's CmdbType
        TYPE_NAME: The type's unique name
        TYPE_LABEL: The type's display label
        CREATION_TIME: When the type was created
        AUTHOR_ID: public_id of the user who created the type
        AUTHOR_NAME: Display name resolved for AUTHOR_ID
        ICON: The type's render_meta icon, or an empty string when it has none
        ACTIVE: The type's active flag
        VERSION: The type's version string
        ACL: The type's serialised AccessControlList
        SELECTABLE_AS_PARENT: Whether objects of this type may be a CmdbLocation parent
        USES_PORTS: Whether objects of this type may carry physical ports (Port Connectivity)
    """
    TYPE_ID = 'type_id'
    TYPE_NAME = 'type_name'
    TYPE_LABEL = 'type_label'
    CREATION_TIME = 'creation_time'
    AUTHOR_ID = 'author_id'
    AUTHOR_NAME = 'author_name'
    ICON = 'icon'
    ACTIVE = 'active'
    VERSION = 'version'
    ACL = 'acl'
    SELECTABLE_AS_PARENT = 'selectable_as_parent'
    USES_PORTS = 'uses_ports'
