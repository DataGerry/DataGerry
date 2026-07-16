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
String constants used by the CmdbLocation REST routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class LocationRight(BaseStrEnum):
    """The ``base.framework.location.*`` ACL rights enforced by the CmdbLocation routes."""
    VIEW = 'base.framework.location.view'
    ADD = 'base.framework.location.add'
    EDIT = 'base.framework.location.edit'
    DELETE = 'base.framework.location.delete'


# Fallback name template applied when a CmdbLocation has no explicit name and the linked
# CmdbObject yields no usable summary line. Format with the object's public_id.
OBJECT_ID_NAME_TEMPLATE: str = 'ObjectID: {object_id}'

# Response-only key added to each lazy location-tree node signalling whether it can be expanded
LOCATION_TREE_HAS_CHILDREN_KEY: str = 'has_children'
