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
Resolves the user tokens of a scope's conditions to object ids, for one user and one request (phase 9 step 4, R13-R15)

* ``{user: person}``: the person the user sync links to the user (``system_ref {kind: user}``),
* ``{user: groups}``: the person groups the group sync links to the user's user groups (``kind: user_group``, R14) -

none when unresolvable, so the condition matches nothing (R15). ``{within: L}`` and ``{in_network: N}`` need nothing
resolved: they are answered by the objects' materialised scope block (``_scope``, phase 10)
"""
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from cmdb.manager import ObjectsManager
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectSystemRefKey
from cmdb.models.object_model.object_constants import SystemRefKind
from cmdb.models.user_model import CmdbUser
from cmdb.framework.scope_compiler.scope_compiler_constants import (
    ScopeBlockKey,
    UserToken,
    UserTokenKey,
)
from cmdb.framework.scope_compiler.scope_grammar import is_user_token

from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
from cmdb.errors.scope_compiler import ScopeResolutionError
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ScopeContext',
    'ScopeReferences',
    'scope_references',
    'ScopeResolver',
]

_SYSTEM_REF_KIND: str = f'{CmdbObjectKey.SYSTEM_REF.value}.{CmdbObjectSystemRefKey.KIND.value}'
_SYSTEM_REF_ID: str = f'{CmdbObjectKey.SYSTEM_REF.value}.{CmdbObjectSystemRefKey.ID.value}'
_ID_PROJECTION: dict[str, int] = {'_id': 0, CmdbObjectKey.PUBLIC_ID.value: 1}


@dataclass(frozen=True)
class ScopeContext:
    """
    What a scope's user tokens resolved to for one user

    Attributes:
        person_ids (tuple[int, ...]): ``{user: person}`` - the user's person, or none
        group_ids (tuple[int, ...]): ``{user: groups}`` - the person groups of the user's user groups
    """
    person_ids: tuple[int, ...] = ()
    group_ids: tuple[int, ...] = ()

    def token_ids(self, token: dict[str, Any]) -> list[int]:
        """
        The ids a user token stands for

        Args:
            token (dict[str, Any]): ``{user: person}`` or ``{user: groups}``

        Returns:
            list[int]: The ids; empty when unresolvable
        """
        if token[UserTokenKey.USER.value] == UserToken.PERSON.value:
            return list(self.person_ids)

        return list(self.group_ids)


@dataclass(frozen=True)
class ScopeReferences:
    """
    Which user tokens a set of scopes needs resolved

    Attributes:
        person (bool): Whether ``{user: person}`` occurs
        groups (bool): Whether ``{user: groups}`` occurs
    """
    person: bool = False
    groups: bool = False


def scope_references(scopes: Iterable[list[dict[str, Any]]]) -> ScopeReferences:
    """
    Collects the user tokens the given cast scopes name

    Args:
        scopes (Iterable[list[dict[str, Any]]]): Cast condition lists

    Returns:
        ScopeReferences: The tokens named
    """
    tokens: set[str] = {block[ScopeBlockKey.VALUE.value][UserTokenKey.USER.value]
                        for blocks in scopes for block in blocks
                        if is_user_token(block.get(ScopeBlockKey.VALUE.value))}

    return ScopeReferences(UserToken.PERSON.value in tokens, UserToken.GROUPS.value in tokens)


class ScopeResolver:
    """
    Reads what the user tokens stand for - one instance per request
    """
    def __init__(self, objects_manager: ObjectsManager) -> None:
        """
        Args:
            objects_manager (ObjectsManager): Reads the linked persons and person groups
        """
        self.objects_manager: ObjectsManager = objects_manager


    def resolve(self, user: CmdbUser, references: ScopeReferences) -> ScopeContext:
        """
        Resolves every named token for the user

        Args:
            user (CmdbUser): The user the scopes are evaluated for
            references (ScopeReferences): What to resolve

        Raises:
            ScopeResolutionError: When a read fails

        Returns:
            ScopeContext: The resolved ids
        """
        try:
            return ScopeContext(
                person_ids=self._linked_ids(SystemRefKind.USER, [user.public_id]) if references.person else (),
                group_ids=self._linked_ids(SystemRefKind.USER_GROUP, user.group_ids) if references.groups else (),
            )
        except (BaseManagerGetError, BaseManagerIterationError) as err:
            raise ScopeResolutionError(err) from err


    def _linked_ids(self, kind: SystemRefKind, record_ids: list[int]) -> tuple[int, ...]:
        """
        The objects the sync links to the given users / user groups

        Args:
            kind (SystemRefKind): ``user`` or ``user_group``
            record_ids (list[int]): The users' / user groups' ids

        Returns:
            tuple[int, ...]: The linked objects' ids, ascending
        """
        if not record_ids:
            return ()

        documents: list[dict[str, Any]] = self.objects_manager.find(
            criteria={_SYSTEM_REF_KIND: kind.value, _SYSTEM_REF_ID: {'$in': list(record_ids)}},
            projection=_ID_PROJECTION)

        return tuple(sorted(document[CmdbObjectKey.PUBLIC_ID.value] for document in documents))
