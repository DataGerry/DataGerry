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
Enumeration of dict keys allowed inside a single section entry of a CmdbType section schema
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class SectionKey(BaseStrEnum):
    """
    Enumeration of dict keys allowed inside a single section entry

    A section entry lives inside the 'sections' list of a CmdbType (or SpecialType) schema and groups
    a set of field names together for display. Use these members instead of bare string literals when
    constructing or reading a section dict so a typo becomes an ImportError or AttributeError instead
    of a silently ignored key
    """
    TYPE = 'type'
    NAME = 'name'
    LABEL = 'label'
    FIELDS = 'fields'
    HIDDEN_FIELDS = 'hidden_fields'
