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
REST routes of the CI Explorer

  - ci_explorer_routes: the blueprint - the node/edge graph, the saved filter profiles and the two
      presentation fields the graph renders (a CmdbObject's tooltip, a CmdbType's label)
  - ci_explorer_helper: the request schemas of the two field routes, their shared
      fetch-guard-persist step, and the edit log the tooltip write records
  - ci_explorer_constants: the ACL rights guarding the routes and the query parameters they read

The graph itself is built in cmdb.framework.ci_explorer; these routes only parse, authorise and
delegate
"""
