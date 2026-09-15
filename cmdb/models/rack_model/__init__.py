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
Domain entities of the Rack View feature

A Rack itself is an ordinary CmdbObject of the RACK SpecialType (see
cmdb.models.special_type_model.rack_constants for its field names). This package holds what is NOT an
object: CmdbRackMount, the join document binding one CmdbObject to one Rack, plus the area and
document-key enums that describe it
"""
from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey
from cmdb.models.rack_model.cmdb_rack_mount import CmdbRackMount
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RackArea',
    'RackMountKey',
    'CmdbRackMount',
]
