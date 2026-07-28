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
Enumeration of top-level dict keys of a CmdbType / SpecialType schema
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class TypeSchemaKey(BaseStrEnum):
    """
    Enumeration of top-level dict keys of a CmdbType / SpecialType schema

    These keys appear at the outermost level of a type schema dict and reference the section list,
    the field list and the optional SpecialType marker. Use these members instead of bare string
    literals when constructing or reading a type schema so a typo becomes an ImportError or
    AttributeError instead of a silently ignored key

    RENDER_META is the persisted CmdbType document key the presentation data nests under;
    queries against stored type documents compose their dotted paths from RENDER_META +
    the nested member (SECTIONS, ICON, SUMMARY, EXTERNALS)

    The identity / audit / presentation members (PUBLIC_ID, NAME, LABEL, ACTIVE, AUTHOR_ID,
    EDITOR_ID, CREATION_TIME, LAST_EDIT_TIME, GLOBAL_TEMPLATE_IDS, SELECTABLE_AS_PARENT,
    VERSION, DESCRIPTION, CI_EXPLORER_LABEL, CI_EXPLORER_COLOR, ACL) are the remaining
    top-level keys a stored CmdbType document carries
    """
    SPECIAL_TYPE = 'special_type'
    SECTIONS = 'sections'
    FIELDS = 'fields'
    RENDER_META = 'render_meta'
    ICON = 'icon'
    SUMMARY = 'summary'
    EXTERNALS = 'externals'
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    LABEL = 'label'
    ACTIVE = 'active'
    AUTHOR_ID = 'author_id'
    EDITOR_ID = 'editor_id'
    CREATION_TIME = 'creation_time'
    LAST_EDIT_TIME = 'last_edit_time'
    GLOBAL_TEMPLATE_IDS = 'global_template_ids'
    SELECTABLE_AS_PARENT = 'selectable_as_parent'
    VERSION = 'version'
    DESCRIPTION = 'description'
    CI_EXPLORER_LABEL = 'ci_explorer_label'
    CI_EXPLORER_COLOR = 'ci_explorer_color'
    ACL = 'acl'
