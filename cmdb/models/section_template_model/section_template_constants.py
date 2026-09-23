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
Shared constants for CmdbSectionTemplates

Names the request-body / document keys a CmdbSectionTemplate carries, the keys of the usage payload
the count route answers, and the ACL rights guarding its REST routes, so the routes and any other
consumer stay aligned on the literal strings instead of repeating them
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class SectionTemplateKey(BaseStrEnum):
    """
    Keys of a CmdbSectionTemplate request body / document

    Use these members instead of bare string literals when reading the request payload or
    building a template document so a typo becomes an AttributeError instead of a silently
    missing key
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    LABEL = 'label'
    TYPE = 'type'
    FIELDS = 'fields'
    IS_GLOBAL = 'is_global'
    PREDEFINED = 'predefined'


# The keys a client may set on a section-template write. Everything else is dropped rather than
# stored: `CmdbSectionTemplate.__init__` takes **kwargs and the manager inserts the instance's
# __dict__, so an extra request parameter would become a document key the SCHEMA does not declare -
# invisible on read, because to_json drops it, and surviving every later edit
SECTION_TEMPLATE_WRITE_KEYS: frozenset[str] = frozenset({
    SectionTemplateKey.PUBLIC_ID,
    SectionTemplateKey.NAME,
    SectionTemplateKey.LABEL,
    SectionTemplateKey.TYPE,
    SectionTemplateKey.FIELDS,
    SectionTemplateKey.IS_GLOBAL,
    SectionTemplateKey.PREDEFINED,
})

# Cap on a template's `name` and `label`. Neither has a storage limit - the cap exists because both
# are rendered: the label heads the section on every consuming type's form, and the name is the
# propagation key shown wherever a template is listed. The value matches the frontend's own text cap
SECTION_TEMPLATE_TEXT_MAX_LENGTH: int = 255


class SectionTemplateUsageKey(BaseStrEnum):
    """
    Keys of the usage payload ``GET /section_templates/<public_id>/count`` answers

    TYPES and OBJECTS are the counts themselves. IS_GLOBAL is what makes a zero readable: only a
    global template stays linked to the types that adopt it, so ``{'types': 0, 'objects': 0}`` means
    "global and unused" when IS_GLOBAL is True and "the count does not apply here" when it is False
    """
    TYPES = 'types'
    OBJECTS = 'objects'
    IS_GLOBAL = 'is_global'


class SectionTemplateRight(BaseStrEnum):
    """
    ACL right identifiers guarding the CmdbSectionTemplate REST routes
    """
    ADD = 'base.framework.sectionTemplate.add'
    VIEW = 'base.framework.sectionTemplate.view'
    EDIT = 'base.framework.sectionTemplate.edit'
    DELETE = 'base.framework.sectionTemplate.delete'
