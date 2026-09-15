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
Shared constants for the CmdbRelation and CmdbObjectRelation REST routes

Names the ACL rights guarding the routes, plus the request / response keys that belong to a route
rather than to the document: the relation-tab pagination parameters and the keys of the relation-tab
instances body. The document's own keys live with the model (``ObjectRelationKey``,
``ObjectRelationRole``, ``RelationTabKey`` in ``cmdb.models.object_relation_model``) because the
managers read the very same keys.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'DEFAULT_TAB_PAGE_SIZE',
    'MAX_TAB_PAGE_SIZE',
    'SORT_DIRECTIONS',
    'RelationRight',
    'ObjectRelationRight',
    'ObjectRelationTabParam',
    'TabInstancesKey',
    'BulkDeleteKey',
]

# Page size used when the relation-tab instances route is called without an explicit 'limit'
DEFAULT_TAB_PAGE_SIZE: int = 10

# Upper bound for that route's 'limit'. A tab can hold thousands of instances and each row costs a
# rendered counterpart, so an unbounded page is refused instead of silently served
MAX_TAB_PAGE_SIZE: int = 1000

# Sort directions accepted by the relation-tab instances route, in MongoDB's own encoding
SORT_DIRECTIONS: tuple[int, ...] = (1, -1)


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


class ObjectRelationTabParam(BaseStrEnum):
    """Query parameters of the relation-tab instances route"""
    RELATION_ID = 'relation_id'
    ROLE = 'role'
    LIMIT = 'limit'
    PAGE = 'page'
    SORT = 'sort'
    ORDER = 'order'


class TabInstancesKey(BaseStrEnum):
    """Keys of the relation-tab instances response body and of a single row"""
    TOTAL = 'total'
    COUNT = 'count'
    RESULTS = 'results'
    COUNTERPART = 'counterpart'


class BulkDeleteKey(BaseStrEnum):
    """Keys of a bulk-delete request body"""
    TARGET_IDS = 'target_ids'
