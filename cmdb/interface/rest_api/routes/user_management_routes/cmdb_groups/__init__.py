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

    groups_routes.py     ``groups_blueprint`` - the CmdbUserGroup CRUD endpoints
    groups_helper.py     the route-level rules: unknown rights refused on both writes, the
                         administrator group keeps the master right, and the delete's refusals and
                         member redistribution
    groups_constants.py  the ``base.user-management.group.*`` rights, URL segments and refusal messages

The handlers delegate storage to ``GroupsManager`` (right-tree hydration, the protected-group guard)
and ``UsersManager`` (member redistribution on delete).
"""
