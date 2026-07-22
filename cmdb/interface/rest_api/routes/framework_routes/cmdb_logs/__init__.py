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
REST API routes for the CmdbLog domain

Gathers everything backing the ``/rest/logs`` endpoints in one place, mirroring the
``cmdb_objects`` and ``cmdb_locations`` route packages:

    logs_routes.py      ``logs_blueprint`` - the CmdbLog read/delete endpoints
    logs_helper.py      route-level helpers shared by the list handlers
    logs_constants.py   ACL rights, document keys and query operators used by those routes

The handlers delegate their domain logic to ``LogsManager``.
"""
from .logs_routes import logs_blueprint
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'logs_blueprint',
]
