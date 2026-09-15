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
REST routes of the Rack View feature

  - rack_mount_routes: the CmdbRackMount CRUD - the only way a mount is written. Assigning an object
      to a rack, placing it, moving it, unplacing it and removing it from the rack all go through
      here, because each is a multi-step operation with its own conflict reporting that has no
      business being spread across the generic object-edit form
  - rack_mount_helper: the per-step orchestration those routes share
  - rack_assignable_routes: the picker listing the CmdbObjects still free to be mounted - a read-only
      projection of the objects collection, so it is its own blueprint rather than a further mount route
  - rack_route_constants: the ACL rights, request keys and query parameters of this route set

A Rack itself is an ordinary CmdbObject of the RACK SpecialType, so it is created, read, edited and
deleted through the /objects routes - there is deliberately no rack CRUD here
"""
