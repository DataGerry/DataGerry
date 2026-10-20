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
Shared constants of the rights domain

``GLOBAL_RIGHT_IDENTIFIER`` is the wildcard segment ('*') that turns a right into a group-wide one:
`BaseRight` marks such a right `is_master`, and `CmdbUserGroup.has_extended_right` walks a qualified
name segment by segment asking whether the group holds the '*' right of each parent.

``NAME_TO_LEVEL`` is the level mapping the API serves (`GET /rest/rights/levels`), keyed by name
because that is the direction the frontend needs: it renders a level selector from names and sends
back the numeric value.
"""
from cmdb.models.right_model.levels_enum import Levels
# -------------------------------------------------------------------------------------------------------------------- #

GLOBAL_RIGHT_IDENTIFIER = '*'

NAME_TO_LEVEL = {
    'CRITICAL': Levels.CRITICAL,
    'DANGER': Levels.DANGER,
    'SECURE': Levels.SECURE,
    'PROTECTED': Levels.PROTECTED,
    'PERMISSION': Levels.PERMISSION,
    'NOTSET': Levels.NOTSET,
}
