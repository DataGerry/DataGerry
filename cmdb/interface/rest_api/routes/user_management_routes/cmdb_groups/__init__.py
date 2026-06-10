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
REST API routes for the CmdbUserGroup domain

Gathers everything backing the ``/rest/groups`` endpoints in one place, mirroring the
``cmdb_objects`` / ``cmdb_types`` / ``cmdb_categories`` route packages:

    groups_routes.py   ``groups_blueprint`` - the CmdbUserGroup CRUD endpoints

The CRUD handlers delegate their domain logic to ``GroupsManager`` (right-tree hydration, the
protected-group guard) and ``UsersManager`` (member redistribution on delete), so there is no
route-level helper / constants module yet; one should be added here if such logic ever emerges.
"""
