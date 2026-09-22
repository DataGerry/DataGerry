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

The level catalogue `GET /rest/rights/levels` serves does NOT live here: it is
``Levels.as_name_map()``, built by the enum that owns the members. A hand-written copy used to sit
beside this constant, kept in step with the enum by nothing but a unit test.
"""
# -------------------------------------------------------------------------------------------------------------------- #

GLOBAL_RIGHT_IDENTIFIER = '*'
