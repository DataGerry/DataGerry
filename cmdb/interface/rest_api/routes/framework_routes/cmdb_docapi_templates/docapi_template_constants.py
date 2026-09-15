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
Shared constants for the DocapiTemplate REST routes

Names the ACL rights guarding the DocapiTemplate routes so the routes reference enum members
instead of repeating the literal right strings.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RENDER_OBJECT_RIGHT',
    'DocapiTemplateRight',
]

RENDER_OBJECT_RIGHT: str = 'base.framework.object.view'
"""
The right guarding the render route - a CmdbObject right, not a DocapiTemplate one

Rendering reads the target CmdbObject and puts its field values into the document, so the right that
decides it belongs to the object domain. The consequence is deliberate but worth knowing: holding all
four DocapiTemplate rights is not enough to render, and whether the route should demand a template
right AS WELL is a filed decision
"""


class DocapiTemplateRight(BaseStrEnum):
    """
    ACL right identifiers guarding the DocapiTemplate REST routes
    """
    ADD = 'base.docapi.template.add'
    VIEW = 'base.docapi.template.view'
    EDIT = 'base.docapi.template.edit'
    DELETE = 'base.docapi.template.delete'
