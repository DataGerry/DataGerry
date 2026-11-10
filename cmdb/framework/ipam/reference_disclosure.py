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
What an IPAM refusal may say about the objects that caused it

The IPAM invariants are judged over every stored object - a subnet still referenced by an interface row on an object of
a Type the caller may not READ still blocks its delete, an IP such an object uses is still taken. The **read** is
unscoped, deliberately. The **answer** is not: a refusal names an object only when the caller may READ its Type and
counts the rest ("…, plus 3 object(s) you cannot see"), the rule the reports, the reference listing and the cable views
follow (a hidden object is never named).

``hidden_types_of`` hands the refusals the caller's denied Types lazily: they are read once, and only when a refusal
actually has an object to describe - an allowed write or delete reads nothing more. ``no_hidden_types`` is the
answer for a caller nothing is hidden from (an internal check, a test), and every parameter's default
"""
from functools import cache
from typing import Callable

from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.ipam.references_constants import (
    HIDDEN_REFERENCES_JOIN,
    HIDDEN_REFERENCES_PART,
    MORE_REFERENCES_PART,
    REFERENCE_ID_SEPARATOR,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['HiddenTypeIds', 'describe_reference_ids', 'hidden_types_of', 'no_hidden_types']

# A call answering the public_ids of the CmdbTypes whose objects a refusal may not name
HiddenTypeIds = Callable[[], frozenset[int]]


def no_hidden_types() -> frozenset[int]:
    """
    The hidden Types of a caller nothing is hidden from

    Returns:
        frozenset[int]: Empty
    """
    return frozenset()



def hidden_types_of(request_user: CmdbUser) -> HiddenTypeIds:
    """
    The caller's denied Types as a lazy, read-once call

    The Types are read on the first call - when a refusal has an object to describe - and the answer is kept for the
    rest of the request, so a bulk delete naming references on several targets reads them once

    Args:
        request_user (CmdbUser): The caller, whose READ ACL decides what a refusal may name

    Returns:
        HiddenTypeIds: The call; it raises what ``resolve_denied_type_ids`` raises (BaseManagerGetError when the Types
            could not be read)
    """
    @cache
    def _hidden() -> frozenset[int]:
        return frozenset(resolve_denied_type_ids(request_user, AccessControlPermission.READ))

    return _hidden


def describe_reference_ids(listed: list[int], more: int, hidden: int) -> str:
    """
    The id description of a delete guard's 400: the listed readable ids, then the counts

    Args:
        listed (list[int]): The readable ids named, in their listing order
        more (int): How many more readable objects there are past the listed ones
        hidden (int): How many objects of Types the caller may not READ there are

    Returns:
        str: E.g. ``"1, 2"``, ``"1, 2 and 135 more"``, ``"1, 2 and 135 more, plus 3 object(s) you cannot see"``,
            ``"3 object(s) you cannot see"``; empty when there is nothing to describe
    """
    readable: str = REFERENCE_ID_SEPARATOR.join(str(public_id) for public_id in listed)

    if readable and more:
        readable = MORE_REFERENCES_PART.format(listed=readable, more=more)

    if not hidden:
        return readable

    hidden_part: str = HIDDEN_REFERENCES_PART.format(hidden=hidden)

    return f'{readable}{HIDDEN_REFERENCES_JOIN}{hidden_part}' if readable else hidden_part
