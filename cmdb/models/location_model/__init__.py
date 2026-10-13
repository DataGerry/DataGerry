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
Provides CmdbLocation related helpers: the canonical document read, the tree-level ordering, the
root-document check, the two coercions the model and that read share, and which nodes a reader may see
"""
from .location_utils import (
    coerce_type_icon,
    coerce_type_selectable,
    sort_locations_by_name,
    to_location_document,
    validate_root_location,
)
from .location_visibility import chain_is_hidden, node_is_hidden
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'chain_is_hidden',
    'coerce_type_icon',
    'coerce_type_selectable',
    'node_is_hidden',
    'sort_locations_by_name',
    'to_location_document',
    'validate_root_location',
]
