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
Implementation of ApiLevel - which routes the cloud API key may reach

An API level belongs to ONE channel: the hosted cloud's API, a request carrying HTTP Basic credentials and an
`x-api-key`, checked against the Service Portal account (`route_utils.verify_api_access`). It is not an
authorisation check: what a caller may do is decided by the rights (`APIBlueprint.protect`) and the type ACLs.
On-premise no level is checked at all - the licensed REST API (HTTP Basic, the `REST_API` feature) reaches every
route the user's rights allow, `LOCKED` ones included - and a cloud request with a Bearer token, which is how the
DataGerry frontend calls, skips the check as well
"""
from enum import IntEnum
# -------------------------------------------------------------------------------------------------------------------- #

class ApiLevel(IntEnum):
    """
    The level a route asks of the cloud API key

    The values are compared with the `api_level` the Service Portal stores for an account, so they must not change

    Attributes:
        NO_API: Requires nothing - the default of a check that names no level
        ADMIN: The account's subscription level must reach ADMIN - the core CMDB entities and the schema
        SUPER_ADMIN: The account's own level must reach SUPER_ADMIN - the tenant setup and the user writes
        LOCKED: Not offered to the cloud API key at all, whatever its level: refused outright, never compared.
            The feature and presentation surfaces - for the frontend's token and, on-premise, the REST API
    """
    NO_API = 0
    ADMIN = 1
    SUPER_ADMIN = 2
    LOCKED = 3
