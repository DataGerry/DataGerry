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

Names the request-body / document keys a CmdbSectionTemplate carries and the ACL rights guarding
its REST routes, so the routes and any other consumer stay aligned on the literal strings instead
of repeating them
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


class SectionTemplateRight(BaseStrEnum):
    """
    ACL right identifiers guarding the CmdbSectionTemplate REST routes
    """
    ADD = 'base.framework.sectionTemplate.add'
    VIEW = 'base.framework.sectionTemplate.view'
    EDIT = 'base.framework.sectionTemplate.edit'
    DELETE = 'base.framework.sectionTemplate.delete'
