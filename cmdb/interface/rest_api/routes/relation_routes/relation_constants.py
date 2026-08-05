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
Shared constants for the CmdbRelation REST routes

Names the ACL rights guarding the CmdbRelation routes so the routes reference enum members
instead of repeating the literal right strings.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class RelationRight(BaseStrEnum):
    """
    ACL right identifiers guarding the CmdbRelation REST routes
    """
    ADD = 'base.framework.relation.add'
    VIEW = 'base.framework.relation.view'
    EDIT = 'base.framework.relation.edit'
    DELETE = 'base.framework.relation.delete'


class ObjectRelationRight(BaseStrEnum):
    """
    ACL right identifiers guarding the CmdbObjectRelation REST routes
    """
    ADD = 'base.framework.objectRelation.add'
    VIEW = 'base.framework.objectRelation.view'
    EDIT = 'base.framework.objectRelation.edit'
    DELETE = 'base.framework.objectRelation.delete'
