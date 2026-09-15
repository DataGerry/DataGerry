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
The static rights tree of DataGerry

A right is immutable configuration rather than persisted data: `all_rights.py` assembles every right
in the product into one nested tuple tree at import time, and it is served from memory. This package
holds that tree plus its building blocks - `BaseRight` (the node type, and the only place a level is
validated), `Levels` (the sensitivity scale), the `PREFIX`-specialising subclasses per domain
(`framework_rights`, `isms_rights`, `user_management_rights`, ...) and the shared constants.

What consumes it: `RightsManager` and `GroupsManager` flatten the tree, `CmdbUserGroup` stores the
qualified names of the rights a group holds, and `APIBlueprint.protect(right=...)` names one of those
qualified names per route.

Modules are imported by their full path (`cmdb.models.right_model.base_right`) rather than from this
package, so nothing is re-exported here.
"""
