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

Names the query-string parameters the ``/ci_explorer`` routes read and the CmdbObject / CmdbType
field keys the update routes write, so the routes reference the literal strings from one place. The
node-direction values live in cmdb.models.ci_explorer_model.NodeType.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


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


class CiExplorerField(BaseStrEnum):
    """
    CmdbObject / CmdbType field keys the CI Explorer update routes read and write

    TOOLTIP is set on a CmdbObject by the ``/tooltip`` route; LABEL is set on a CmdbType by the
    ``/type_label`` route
    """
    TOOLTIP = 'ci_explorer_tooltip'
    LABEL = 'ci_explorer_label'
