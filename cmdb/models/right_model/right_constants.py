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

``ObjectRightName`` holds the qualified names of the CmdbObject rights, the ones the object routes and
every surface that reads objects the same way (the search, the media library, the DocAPI render) guard
with. The rights themselves are declared in ``all_rights.FRAMEWORK_RIGHTS``; the names are written down
once here so no route spells them - a misspelt name does not raise, it denies every caller.

The level catalogue `GET /rest/rights/levels` serves does NOT live here: it is
``Levels.as_name_map()``, built by the enum that owns the members, so it cannot fall out of step with
them.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

GLOBAL_RIGHT_IDENTIFIER = '*'


class ObjectRightName(BaseStrEnum):
    """
    Enumeration of the qualified names of the CmdbObject rights

    One member per right declared under ``ObjectRight`` in ``all_rights.FRAMEWORK_RIGHTS`` - the unit
    tests hold the two to each other - plus ``ALL``, the wildcard that grants every one of them

    Attributes:
        ALL: Every object right (the seeded ``user`` group holds it)
        VIEW: Read objects - every object read, and every surface that answers objects
        ADD: Create objects
        EDIT: Change objects
        DELETE: Delete objects
        ACTIVATION: Activate / deactivate objects
    """
    ALL = f'base.framework.object.{GLOBAL_RIGHT_IDENTIFIER}'
    VIEW = 'base.framework.object.view'
    ADD = 'base.framework.object.add'
    EDIT = 'base.framework.object.edit'
    DELETE = 'base.framework.object.delete'
    ACTIVATION = 'base.framework.object.activation'
