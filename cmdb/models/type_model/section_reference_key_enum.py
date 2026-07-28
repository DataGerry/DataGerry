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
Enumeration of dict keys allowed inside the 'reference' entry of a ref-section
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class SectionReferenceKey(BaseStrEnum):
    """
    Enumeration of dict keys allowed inside a ref-section's 'reference' entry

    A ref-section (SectionKey.REFERENCE) points at a section of ANOTHER CmdbType: TYPE_ID is that
    type's public_id, SECTION_NAME the section of it that is rendered, and SELECTED_FIELDS the subset
    of its fields to show. Use these members instead of bare string literals when constructing or
    reading the reference dict so a typo becomes an ImportError or AttributeError instead of a
    silently ignored key
    """
    TYPE_ID = 'type_id'
    SECTION_NAME = 'section_name'
    SELECTED_FIELDS = 'selected_fields'
