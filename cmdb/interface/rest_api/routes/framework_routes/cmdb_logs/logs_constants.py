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
Constants used by the CmdbLog REST routes

Centralises the ACL rights each endpoint guards on, the document keys the route queries read, and
the MongoDB operator literals used when assembling those queries - so the routes and helper carry
no bare string literals.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class LogRight(BaseStrEnum):
    """Per-endpoint ACL rights checked by the CmdbLog route ``protect`` decorators."""
    VIEW = 'base.framework.log.view'
    DELETE = 'base.framework.log.delete'


class LogKey(BaseStrEnum):
    """Document keys of a CmdbLog read or matched by the routes."""
    PUBLIC_ID = 'public_id'
    LOG_TYPE = 'log_type'
    OBJECT_ID = 'object_id'
    ACTION = 'action'
    USER_ID = 'user_id'
    TYPE_ID = 'type_id'


class LogResultKey(BaseStrEnum):
    """Keys nested inside the ``results`` payload when users are requested (``include_users=true``)."""
    LOGS = 'logs'
    USERS = 'users'


class LogQueryOperator(BaseStrEnum):
    """MongoDB operator literals used when assembling CmdbLog queries."""
    NOR = '$nor'
    NE = '$ne'
    EXISTS = '$exists'


# The existence split of the object-log lists joins each log to `framework.objects` under this field.
# The joined array holds at most one id-only document, so "the object exists" is "element 0 exists"
OBJECT_LOOKUP_FIELD: str = 'object'
OBJECT_LOOKUP_FIRST_MATCH: str = f'{OBJECT_LOOKUP_FIELD}.0'
OBJECT_LOOKUP_MAX_MATCHES: int = 1
MONGO_ID_KEY: str = '_id'


# Query-string flag: when truthy, the object-log list ``results`` becomes ``{logs, users}`` with the
# referenced users resolved server-side (default off, so the plain list is preserved for API clients)
INCLUDE_USERS_PARAM: str = 'include_users'


# Refusals (HTTP 403) of a log read or delete the caller's type ACL does not grant: a single log, and the logs of
# one object the caller may not read
LOG_ACCESS_DENIED_MSG: str = "The Log with ID:{public_id} belongs to an Object you may not read!"
OBJECT_LOGS_ACCESS_DENIED_MSG: str = "You may not read the logs of the Object with ID:{object_id}!"
