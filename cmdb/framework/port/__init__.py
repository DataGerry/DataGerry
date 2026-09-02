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
Port Connectivity logic that sits above the managers

Currently the delete cascade a CmdbObject's ports depend on. The write invariants a port has to
satisfy live in the route layer's helper, because they are request-shaped (they abort); anything a
later step needs from more than one caller belongs here
"""
from .cascade import delete_ports_of_object
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'delete_ports_of_object',
]
