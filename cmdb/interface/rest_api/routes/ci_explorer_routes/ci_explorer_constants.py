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
Constants for the CI Explorer REST routes

Names the ACL rights guarding the ``/ci_explorer`` routes and the query-string parameters they read.

The CI Explorer FIELD keys are deliberately not repeated here: ``ci_explorer_tooltip`` belongs to the
CmdbObject document (``CmdbObjectKey.CI_EXPLORER_TOOLTIP``) and ``ci_explorer_label`` /
``ci_explorer_color`` to the CmdbType document (``TypeSchemaKey.CI_EXPLORER_*``), so the models own
them and every reader - these routes included - takes them from there. The node-direction values live
in cmdb.models.ci_explorer_model.NodeType
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CiExplorerRight',
    'CiExplorerParam',
]


class CiExplorerRight(BaseStrEnum):
    """
    ACL right identifiers guarding the CI Explorer REST routes

    The family has two members only - there is no add/delete right for the CI Explorer - so the reads
    take VIEW and every write takes EDIT, saved-profile creation and deletion included. The values are
    the flattened names of the ``CiExplorerRight`` entries in cmdb.models.right_model.all_rights; a
    value naming no existing right would silently deny every user
    """
    VIEW = 'base.framework.ciExplorer.view'
    EDIT = 'base.framework.ciExplorer.edit'


class CiExplorerParam(BaseStrEnum):
    """
    Query-string parameter names read by the CI Explorer ``/items`` route

    Use these members instead of bare string literals when reading ``request.args`` so a typo
    becomes an AttributeError instead of a silently missing parameter
    """
    TARGET_ID = 'target_id'
    TARGET_TYPE = 'target_type'
    WITH_ROOT = 'with_root'
    WITH_LOCATIONS = 'with_locations'
    WITH_IPAM_RELATIONS = 'with_ipam_relations'
    ITEM_LIMIT = 'item_limit'
    TYPES_FILTER = 'types_filter'
    RELATIONS_FILTER = 'relations_filter'
