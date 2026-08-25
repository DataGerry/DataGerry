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
Setup / teardown REST routes driven by the DataGerry Service Portal

  - setup_routes: the three destructive DELETE routes the portal calls to tear down a tenant - drop a
      subscription's database and evict cloud users from the local user cache
  - setup_constants: the query parameter and payload keys those routes read

The package is named after its blueprint (`setup`, mounted at `/setup`) rather than after the
system it belongs to, to keep it apart from `settings_routes/system_routes.py`
"""
