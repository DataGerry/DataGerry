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
Constants consumed by the CmdbUser routes

The rights the routes demand, and which fields of a user an update may change - and by whom. The
update route lets a user edit their OWN record without the edit right (the ``excepted`` carve-out),
so the fields are split by what they decide: a profile field describes the user, an administrative
field decides what the user may do, and a server-owned field is never set through the route at all
"""
from cmdb.utils import BaseStrEnum
from cmdb.models.user_model.cmdb_user_key_enum import CmdbUserKey
# -------------------------------------------------------------------------------------------------------------------- #


class UserAccessRight(BaseStrEnum):
    """The ``base.user-management.user.*`` rights enforced by the CmdbUser routes"""
    VIEW = 'base.user-management.user.view'
    ADD = 'base.user-management.user.add'
    EDIT = 'base.user-management.user.edit'
    DELETE = 'base.user-management.user.delete'


# Fields a user may change on their own record without holding UserAccessRight.EDIT
PROFILE_FIELDS: frozenset[CmdbUserKey] = frozenset({
    CmdbUserKey.FIRST_NAME,
    CmdbUserKey.LAST_NAME,
    CmdbUserKey.EMAIL,
    CmdbUserKey.IMAGE,
})

# Fields that decide what a user may do: only a holder of UserAccessRight.EDIT may change them. On a
# self-edit without that right each one must equal the stored value
ADMINISTRATIVE_FIELDS: frozenset[CmdbUserKey] = frozenset({
    CmdbUserKey.GROUP_ID,
    CmdbUserKey.ACTIVE,
    CmdbUserKey.AUTHENTICATOR,
    CmdbUserKey.API_LEVEL,
    CmdbUserKey.USER_NAME,
})

# Fields the update route never sets, whoever asks. The tenant database binds every manager in cloud
# mode, the ConfigItem limit comes from the subscription, and a password changes only through
# `PATCH /users/<id>/password`, which hashes it and refuses a directory-managed account
SERVER_OWNED_FIELDS: frozenset[CmdbUserKey] = frozenset({
    CmdbUserKey.DATABASE,
    CmdbUserKey.CONFIG_ITEMS_LIMIT,
    CmdbUserKey.PASSWORD,
})

# Fields the update route handles on its own: the public_id is pinned from the URL and the
# registration_time is normalised from its wire shape. Together with the three sets above they name
# every CmdbUserKey, so a new user field has to be placed in one of them
ROUTE_HANDLED_FIELDS: frozenset[CmdbUserKey] = frozenset({
    CmdbUserKey.PUBLIC_ID,
    CmdbUserKey.REGISTRATION_TIME,
})

# The refusals of `guard_user_update`, formatted with the offending field's name
ADMINISTRATIVE_FIELD_REFUSED: str = (
    "The field '{field}' can only be changed by a user holding the right " + UserAccessRight.EDIT.value + "!"
)
SERVER_OWNED_FIELD_REFUSED: str = "The field '{field}' cannot be changed through this route!"
PASSWORD_FIELD_REFUSED: str = (
    "A password cannot be set through this route - use PATCH /users/<public_id>/password instead!"
)
