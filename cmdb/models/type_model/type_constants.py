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
Shared constants for CmdbTypes

Names the ACL rights guarding the CmdbType REST routes so the routes and any other consumer
stay aligned on the literal strings instead of repeating them. Mirrors the SectionTemplateRight
convention in ``section_template_constants``.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class TypeRight(BaseStrEnum):
    """
    ACL right identifiers guarding the CmdbType REST routes
    """
    ADD = 'base.framework.type.add'
    VIEW = 'base.framework.type.view'
    EDIT = 'base.framework.type.edit'
    DELETE = 'base.framework.type.delete'
