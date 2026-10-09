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
Implementation of ReferenceReadScope

What the user a render is performed for may read among the objects it references. A referenced object
is read through that user's READ ACL, and one the user may not read renders exactly like an unset
reference. One scope serves a whole render - every hop of the prefetch - so the denied types are read once
and an id a load did not answer is not asked for again
"""
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                              ReferenceReadScope - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class ReferenceReadScope:
    """
    The READ ACL a render applies to the objects it references

    Attributes:
        user (CmdbUser | None): The user the render is performed for; None reads unscoped, as everywhere
            else in the object layer
        permission (AccessControlPermission): The permission a referenced object's type must grant
        unreturned_ids (set[int]): Ids a scoped load asked for and did not get - unreadable or missing.
            A later hop of the same render does not ask for them again
    """

    def __init__(self, user: CmdbUser | None) -> None:
        """
        Initialises the scope of one render

        Args:
            user (CmdbUser | None): The user the render is performed for
        """
        self.user: CmdbUser | None = user
        self.permission: AccessControlPermission = AccessControlPermission.READ
        self.unreturned_ids: set[int] = set()
        self._denied_type_ids: list[int] | None = None


    @property
    def denied_type_ids(self) -> list[int]:
        """
        The types whose objects the user may not read, read on first use and then kept

        Read lazily: a render that references nothing never pays the query

        Returns:
            list[int]: public_ids of the denied CmdbTypes; empty without a user or when nothing is denied
        """
        if self._denied_type_ids is None:
            self._denied_type_ids = [] if self.user is None else \
                resolve_denied_type_ids(self.user, self.permission)

        return self._denied_type_ids
