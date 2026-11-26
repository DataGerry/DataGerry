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
Evaluates a user's conditional assignments (phase 9 step 8, ruled R21, R22) - once per request

For the user's conditional grant entries: the Types their roles name are read (fields and sections only - every Type
for a role on every Type), each entry's comparison fields resolved across its role's Types (``resolve_scope_fields``),
its user tokens resolved for the user (``ScopeResolver``) and its scope compiled to one MongoDB filter. An entry whose
fields no longer resolve grants nothing (fail closed - the stale-scope guards keep that from happening). The result
answers the list filter's clauses (``filter_for``) and, through the in-memory matcher, which entries grant an
operation on one object state (``matching``). A location or network condition reads the object's scope block: a list
query the stored one, ``matching`` the block computed for the state it judges - a create's or an edit's new placement
counts, not the stored one (phase 10, B1 + B2)
"""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cmdb.utils import request_cache
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.object_scope_blocks import ObjectScopeBlocks
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import ScopeOperation
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectScopeKey
from cmdb.models.type_model import TypeSchemaKey
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine.access_grants import AccessGrants, GrantEntry
from cmdb.framework.access_engine.access_grants_reads import GRANTS_CACHE_KEY, grants_cache_key
from cmdb.framework.scope_compiler import (
    ScopeBlockKind,
    ScopeContext,
    ScopeField,
    ScopeResolver,
    block_kind,
    compile_scope,
    document_matches,
    field_views_of_document,
    resolve_scope_fields,
    scope_field_names,
    scope_references,
)

from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
from cmdb.errors.scope_compiler import ScopeResolutionError
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ConditionalGrant',
    'ScopeEvaluation',
    'build_scope_evaluation',
    'load_scope_evaluation',
]

# The second part of the key a user's evaluation is kept under: tokens make it the user's own, not the groups'
EVALUATION_KEY: str = 'scope-evaluation'
_TYPE_FIELDS_PROJECTION: dict[str, int] = {'_id': 0, TypeSchemaKey.PUBLIC_ID.value: 1, TypeSchemaKey.FIELDS.value: 1,
                                           TypeSchemaKey.RENDER_META.value: 1}


@dataclass(frozen=True)
class ConditionalGrant:
    """
    One conditional assignment of the user, compiled

    Attributes:
        entry (GrantEntry): The grant entry
        criteria (dict[str, Any]): Its scope as a MongoDB filter, resolved for the user
    """
    entry: GrantEntry
    criteria: dict[str, Any]


@dataclass(frozen=True)
class ScopeEvaluation:
    """
    A user's conditional assignments, compiled for one request

    Attributes:
        grants (tuple[ConditionalGrant, ...]): The evaluable conditional assignments, ascending by assignment id
        blocks (ObjectScopeBlocks | None): Computes a judged state's scope block - None when no condition reads one
    """
    grants: tuple[ConditionalGrant, ...] = ()
    blocks: ObjectScopeBlocks | None = None

    def granting(self, operation: ScopeOperation, type_id: int | None = None) -> tuple[ConditionalGrant, ...]:
        """
        The conditional assignments granting an operation - on one Type, or on any

        Args:
            operation (ScopeOperation): The operation
            type_id (int | None): The Type, or None

        Returns:
            tuple[ConditionalGrant, ...]: Those assignments
        """
        return tuple(grant for grant in self.grants if operation in grant.entry.operations
                     and (type_id is None or grant.entry.types.contains(type_id)))


    def matching(self, operation: ScopeOperation, state: Mapping[str, Any]) -> tuple[ConditionalGrant, ...]:
        """
        The conditional assignments granting an operation on one object state - its Type covered, its condition met

        Args:
            operation (ScopeOperation): The operation
            state (Mapping[str, Any]): An object state (stored or as it would be stored)

        Raises:
            ScopeResolutionError: When the state's scope block could not be computed

        Returns:
            tuple[ConditionalGrant, ...]: The matching assignments
        """
        type_id: Any = state.get(CmdbObjectKey.TYPE_ID.value)

        if not isinstance(type_id, int) or isinstance(type_id, bool):
            return ()

        granting: tuple[ConditionalGrant, ...] = self.granting(operation, type_id)

        if not granting:
            return ()

        document: dict[str, Any] = self.with_block(state)

        return tuple(grant for grant in granting if document_matches(document, grant.criteria))


    def with_block(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """
        A state with the scope block computed for it - a block it carries is never trusted

        Args:
            state (Mapping[str, Any]): An object state

        Raises:
            ScopeResolutionError: When the location tree or a subnet could not be read

        Returns:
            dict[str, Any]: The state, with its block when a condition reads one
        """
        document: dict[str, Any] = dict(state)
        document.pop(CmdbObjectScopeKey.BLOCK.value, None)

        if self.blocks is None:
            return document

        try:
            document[CmdbObjectScopeKey.BLOCK.value] = self.blocks.block_of(document)
        except BaseManagerIterationError as err:
            raise ScopeResolutionError(err) from err

        return document


def reads_scope_block(entries: tuple[GrantEntry, ...]) -> bool:
    """
    Whether a location, a network or a related-object condition occurs among the entries' scopes

    Args:
        entries (tuple[GrantEntry, ...]): The conditional entries

    Returns:
        bool: True when a judged state needs its scope block
    """
    return any(block_kind(block) in (ScopeBlockKind.WITHIN, ScopeBlockKind.IN_NETWORK, ScopeBlockKind.RELATED_TO)
               for entry in entries for block in entry.scope or ())


def build_scope_evaluation(entries: tuple[GrantEntry, ...], type_documents: list[dict[str, Any]],
                           context: ScopeContext, now: datetime,
                           blocks: ObjectScopeBlocks | None = None) -> ScopeEvaluation:
    """
    Compiles conditional grant entries - pure

    Args:
        entries (tuple[GrantEntry, ...]): The conditional entries
        type_documents (list[dict[str, Any]]): The Types their roles name (every Type for a role on every Type)
        context (ScopeContext): The user's resolved references
        now (datetime): The evaluation instant
        blocks (ObjectScopeBlocks | None): Computes a judged state's scope block. Defaults to None (none computed)

    Returns:
        ScopeEvaluation: The evaluable entries - one whose fields no longer resolve is left out (grants nothing)
    """
    views: dict[int, dict[str, ScopeField]] = {document[TypeSchemaKey.PUBLIC_ID.value]:
                                               field_views_of_document(document) for document in type_documents}
    grants: list[ConditionalGrant] = []

    for entry in entries:
        role_types: list[dict[str, ScopeField]] = [type_views for type_id, type_views in views.items()
                                                   if entry.types.contains(type_id)]
        conditions: list[dict[str, Any]] = list(entry.scope or ())
        fields, problems = resolve_scope_fields(scope_field_names({'scope': conditions}), role_types)

        if not problems:
            grants.append(ConditionalGrant(entry, compile_scope(conditions, fields, now, context)))

    return ScopeEvaluation(tuple(grants), blocks)


def load_scope_evaluation(user: CmdbUser, grants: AccessGrants) -> ScopeEvaluation:
    """
    The user's conditional assignments compiled, once per request - nothing read when there is none

    Args:
        user (CmdbUser): The user the request is made for
        grants (AccessGrants): The user's grants

    Raises:
        ScopeResolutionError: When the Types or the user tokens could not be read

    Returns:
        ScopeEvaluation: The evaluation
    """
    entries: tuple[GrantEntry, ...] = tuple(entry for entry in grants.entries if entry.conditional)

    if not entries:
        return ScopeEvaluation()

    cache: dict[Any, Any] | None = request_cache(GRANTS_CACHE_KEY)
    key: tuple[Any, ...] = (*grants_cache_key(user), EVALUATION_KEY, user.public_id)

    if cache is not None and key in cache:
        return cache[key]

    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, user)
    every_type: bool = any(entry.types.every_type for entry in entries)
    criteria: dict[str, Any] = {} if every_type else {TypeSchemaKey.PUBLIC_ID.value: {'$in': sorted(
        {type_id for entry in entries for type_id in entry.types.ids})}}

    try:
        type_documents: list[dict[str, Any]] = types_manager.find(criteria=criteria,
                                                                   projection=_TYPE_FIELDS_PROJECTION)
    except BaseManagerGetError as err:
        raise ScopeResolutionError(err) from err

    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)
    context: ScopeContext = ScopeResolver(objects_manager).resolve(
        user, scope_references(list(entry.scope or ()) for entry in entries))
    evaluation: ScopeEvaluation = build_scope_evaluation(
        entries, type_documents, context, datetime.now(timezone.utc),
        ObjectScopeBlocks(objects_manager) if reads_scope_block(entries) else None)

    if cache is not None:
        cache[key] = evaluation

    return evaluation
