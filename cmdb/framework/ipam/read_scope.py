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
What an IPAM reader may see

The IPAM views read CmdbObjects that belong to other people: a subnet's IP table is built from the
``dg-ipam-interface`` rows of servers, clients and anything else carrying one. An ACL lives on the
CmdbType, so "may this caller see that row" is "may their group read that carrier's type".

`resolve_read_scope` turns the requesting user into the list of denied CmdbType ids **once per
request**. Every read below then narrows its criteria with that list rather than resolving it again -
the lookup is a query against `framework.types`, and an overview performs several reads.

**Presentation reads scope; invariant reads must not.** The validators check a candidate against every
existing object, not only the visible ones, because the rule they enforce is global: an ACL-filtered
check would report an overlapping CIDR as valid and the write would then accept it. Those callers pass
no user and get an empty scope.
"""
from logging import Logger, getLogger

from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

__all__: list[str] = [
    'resolve_read_scope',
]


def resolve_read_scope(request_user: CmdbUser | None) -> list[int]:
    """
    Resolves the CmdbTypes the requesting user may not read

    Args:
        request_user (CmdbUser | None): The user the read is performed for, or None for an unscoped
            read - which is what an invariant check passes

    Returns:
        list[int]: public_ids of the denied CmdbTypes; empty when nothing is denied or no user was
            given
    """
    if request_user is None:
        return []

    return resolve_denied_type_ids(request_user, AccessControlPermission.READ)
