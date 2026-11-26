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
Recording the access change history: every access write and every cascade changing an access document writes one entry
per changed document, under the same write ledger as the change - a change is never stored without its entry, nor an
entry without its change

The groups a change concerns are read before anything is written (a failed read refuses the write untouched); the
entries are written last, and the ledger undoes the change when they cannot be
"""
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from flask import abort, request

from cmdb.manager import (
    AccessAssignmentsManager,
    AccessHistoryManager,
    GroupsManager,
    ScopeRolesManager,
    TypesManager,
)
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import (
    ALL_TYPES,
    HISTORY_COMMENT_KEY,
    MAX_HISTORY_COMMENT_LENGTH,
    AccessHistoryKey,
    FieldClassKey,
    FieldRuleKey,
    HistoryAction,
    HistoryKind,
    HistorySource,
    ScopeRoleKey,
)
from cmdb.models.type_model import TypeSchemaKey
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.user_model import CmdbUser
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.access_engine import AccessGrants, build_grants
from cmdb.framework.access_engine.access_grants_reads import load_access_rules
from cmdb.framework.access_rules.access_history import (
    HistoryChange,
    assignment_groups,
    groups_writing_field,
    history_entry,
)
from cmdb.framework.field_rules import group_may_trigger
from cmdb.interface.rest_api.routes.routes_helper import undone_on_failure
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'COMMENT_TOO_LONG_MESSAGE',
    'ChangeContext',
    'take_comment',
    'query_comment',
    'concerned_groups',
    'field_concerned_groups',
    'record_change',
    'record_changes',
    'pull_types_with_history',
]

COMMENT_TOO_LONG_MESSAGE: str = "A comment holds at most {limit} characters!"
PULL_UNDO_INCOMPLETE_MESSAGE: str = (
    "Taking the Type ids out of the access rules failed and could not be undone: {residue}"
)
_TYPE_PROJECTION: dict[str, int] = {'_id': 0, TypeSchemaKey.PUBLIC_ID.value: 1, TypeSchemaKey.FIELDS.value: 1}
_GROUP_ID_PROJECTION: dict[str, int] = {'_id': 0, CmdbDAO.PUBLIC_ID_KEY: 1}


@dataclass(frozen=True)
class ChangeContext:
    """
    Who changes what kind of access document, why, and through what

    Attributes:
        request_user (CmdbUser): The writer
        kind (HistoryKind): The kind of document changed
        comment (str | None): The writer's comment
        source (HistorySource): A route, or the cascade making the change
    """
    request_user: CmdbUser
    kind: HistoryKind
    comment: str | None = None
    source: HistorySource = HistorySource.ROUTE


def take_comment(data: dict[str, Any]) -> str | None:
    """
    Takes a write body's comment off it - it belongs to the history, not to the document

    Args:
        data (dict[str, Any]): The validated body (the schema capped the comment)

    Returns:
        str | None: The comment, None when there is none
    """
    comment: Any = data.pop(HISTORY_COMMENT_KEY, None)

    return comment if isinstance(comment, str) and comment else None


def query_comment() -> str | None:
    """
    A delete's comment, from ``?comment=``

    Raises:
        HTTPException: 400 for a comment above the cap

    Returns:
        str | None: The comment, None when there is none
    """
    comment: str | None = request.args.get(HISTORY_COMMENT_KEY)

    if comment and len(comment) > MAX_HISTORY_COMMENT_LENGTH:
        abort(400, COMMENT_TOO_LONG_MESSAGE.format(limit=MAX_HISTORY_COMMENT_LENGTH))

    return comment or None


def _grants_by_group(request_user: CmdbUser) -> dict[int, AccessGrants]:
    """
    Every user group's own grants - one read of the assignments and roles, one of the group ids

    Args:
        request_user (CmdbUser): The caller - names the tenant

    Raises:
        BaseManagerGetError: When a read fails

    Returns:
        dict[int, AccessGrants]: By group id
    """
    every_assignment, roles = load_access_rules(request_user)
    groups: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)
    group_ids: list[int] = [document[CmdbDAO.PUBLIC_ID_KEY] for document in groups.find(
        criteria={}, projection=_GROUP_ID_PROJECTION)]

    return {group_id: build_grants(every_assignment, roles, [group_id]) for group_id in group_ids}


def _role_groups(request_user: CmdbUser, role_ids: Iterable[int]) -> set[int]:
    """
    The groups holding an assignment of the roles

    Args:
        request_user (CmdbUser): The caller
        role_ids (Iterable[int]): The roles

    Raises:
        AccessAssignmentsManagerGetError: When the read fails

    Returns:
        set[int]: The group ids
    """
    ids: list[int] = sorted(set(role_ids))

    if not ids:
        return set()

    assignments: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS, request_user)

    return assignment_groups(assignments.assignments_of_roles(ids))


def _rule_groups(request_user: CmdbUser, rules: Iterable[Mapping[str, Any] | None]) -> set[int]:
    """
    The groups that can trigger any of the rules

    Args:
        request_user (CmdbUser): The caller
        rules (Iterable[Mapping[str, Any] | None]): The rule's states (None skipped)

    Raises:
        BaseManagerGetError: When a read fails

    Returns:
        set[int]: The group ids
    """
    states: list[Mapping[str, Any]] = [rule for rule in rules if rule]
    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    every_type: bool = any(rule.get(FieldRuleKey.TYPES.value) == ALL_TYPES for rule in states)
    named: list[int] = sorted({type_id for rule in states if rule.get(FieldRuleKey.TYPES.value) != ALL_TYPES
                               for type_id in rule.get(FieldRuleKey.TYPES.value) or []})
    criteria: dict[str, Any] = {} if every_type else {TypeSchemaKey.PUBLIC_ID.value: {'$in': named}}
    documents: list[dict[str, Any]] = types.find(criteria=criteria, projection=_TYPE_PROJECTION) \
        if every_type or named else []

    def documents_of(rule: Mapping[str, Any]) -> list[dict[str, Any]]:
        listed: Any = rule.get(FieldRuleKey.TYPES.value)

        return documents if listed == ALL_TYPES else [document for document in documents
                                                      if document[TypeSchemaKey.PUBLIC_ID.value] in (listed or [])]

    return {group_id for group_id, grants in _grants_by_group(request_user).items()
            if any(group_may_trigger(grants, rule, documents_of(rule)) for rule in states)}


def field_concerned_groups(request_user: CmdbUser, name: str, field_classes: Iterable[str | None],
                           type_ids: Iterable[Any]) -> set[int]:
    """
    The groups a field's protection change concerns: those writing it under its class before or after

    Args:
        request_user (CmdbUser): The caller
        name (str): The field
        field_classes (Iterable[str | None]): Its class before and after
        type_ids (Iterable[Any]): The Types carrying it

    Raises:
        BaseManagerGetError: When a read fails

    Returns:
        set[int]: The group ids
    """
    return groups_writing_field(_grants_by_group(request_user), name, field_classes, type_ids)


def concerned_groups(context: ChangeContext, before: Mapping[str, Any] | None,
                     after: Mapping[str, Any] | None) -> set[int]:
    """
    The user groups a change of an access document concerns - read before the change is written

    Args:
        context (ChangeContext): The change
        before (Mapping[str, Any] | None): The document before; None for a create
        after (Mapping[str, Any] | None): The document after; None for a delete

    Raises:
        BaseManagerGetError: When a read fails

    Returns:
        set[int]: The group ids
    """
    states: list[Mapping[str, Any]] = [state for state in (before, after) if state]

    if context.kind is HistoryKind.ASSIGNMENT:
        return assignment_groups(states)

    if context.kind is HistoryKind.SCOPE_ROLE:
        return _role_groups(context.request_user, [state[ScopeRoleKey.PUBLIC_ID.value] for state in states
                                                   if isinstance(state.get(ScopeRoleKey.PUBLIC_ID.value), int)])

    if context.kind is HistoryKind.FIELD_CLASS:
        roles: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, context.request_user)
        names: set[str] = {state[FieldClassKey.NAME.value] for state in states}

        return _role_groups(context.request_user, [role[ScopeRoleKey.PUBLIC_ID.value] for name in sorted(names)
                                                   for role in roles.roles_granting_class(name)])

    if context.kind is HistoryKind.FIELD_RULE:
        return _rule_groups(context.request_user, states)

    return set()


def record_change(context: ChangeContext, action: HistoryAction, document_id: Any,
                  before: Mapping[str, Any] | None, after: Mapping[str, Any] | None, group_ids: Iterable[int],
                  ledger: WriteLedger) -> None:
    """
    Writes the entry of one change, in the change's ledger

    Args:
        context (ChangeContext): The change
        action (HistoryAction): How the document changed
        document_id (Any): Its id
        before (Mapping[str, Any] | None): The document before; None for a create
        after (Mapping[str, Any] | None): The document after; None for a delete
        group_ids (Iterable[int]): The groups it concerns (``concerned_groups``)
        ledger (WriteLedger): The change's ledger

    Raises:
        AccessHistoryManagerInsertError: When the entry could not be written - the ledger then undoes the change
    """
    record_changes(context, [(action, document_id, before, after, group_ids)], ledger)


def record_changes(context: ChangeContext,
                   changes: list[tuple[HistoryAction, Any, Mapping[str, Any] | None, Mapping[str, Any] | None,
                                       Iterable[int]]],
                   ledger: WriteLedger) -> None:
    """
    Writes the entries of several changes in one insert, in the changes' ledger

    Args:
        context (ChangeContext): The changes' writer, kind, comment and source
        changes (list[tuple[...]]): Per change its action, document id, before, after and concerned groups
        ledger (WriteLedger): The changes' ledger

    Raises:
        AccessHistoryManagerInsertError: When the entries could not be written
    """
    if not changes:
        return

    user: CmdbUser = context.request_user
    now: datetime = datetime.now(timezone.utc)
    entries: list[dict[str, Any]] = [
        history_entry(HistoryChange(action.value, context.kind.value, document_id, before, after, group_ids,
                                    context.source.value, context.comment), now, user.public_id,
                      user.get_display_name())
        for action, document_id, before, after, group_ids in changes]
    history: AccessHistoryManager = ManagerProvider.get_manager(ManagerType.ACCESS_HISTORY, user)
    public_ids: list[int] = history.insert_entries(entries)
    ledger.inserted_where(history, {AccessHistoryKey.PUBLIC_ID.value: {'$in': public_ids}})


def pull_types_with_history(request_user: CmdbUser, source: HistorySource, remaining: Callable[[list[int]], list[int]],
                            roles: list[dict[str, Any]], rules: list[dict[str, Any]], pull: Callable[[], Any]) -> None:
    """
    Takes Type ids out of scope roles and Field Rules - a cascade of a Type delete or a configuration reset - with an
    entry per changed document: the entries first, then the pull; a failed pull removes the entries again

    Args:
        request_user (CmdbUser): Who triggered the cascade
        source (HistorySource): The cascade
        remaining (Callable[[list[int]], list[int]]): The Type ids a listed set keeps
        roles (list[dict[str, Any]]): The scope roles the pull changes, as stored
        rules (list[dict[str, Any]]): The Field Rules the pull changes, as stored
        pull (Callable[[], Any]): The pull itself

    Raises:
        BaseManagerGetError: When the concerned groups could not be read
        AccessHistoryManagerInsertError: When the entries could not be written (nothing pulled)
        Exception: The pull's error (the entries are removed again)
    """
    def changes(kind: HistoryKind, documents: list[dict[str, Any]], key: str) -> list[tuple[Any, ...]]:
        context: ChangeContext = ChangeContext(request_user, kind, source=source)

        return [(HistoryAction.UPDATE, document[key], document,
                 {**document, ScopeRoleKey.TYPES.value: remaining(document.get(ScopeRoleKey.TYPES.value) or [])},
                 concerned_groups(context, document, None)) for document in documents]

    role_changes: list[tuple[Any, ...]] = changes(HistoryKind.SCOPE_ROLE, roles, ScopeRoleKey.PUBLIC_ID.value)
    rule_changes: list[tuple[Any, ...]] = changes(HistoryKind.FIELD_RULE, rules, FieldRuleKey.PUBLIC_ID.value)

    with undone_on_failure(PULL_UNDO_INCOMPLETE_MESSAGE) as ledger:
        record_changes(ChangeContext(request_user, HistoryKind.SCOPE_ROLE, source=source), role_changes, ledger)
        record_changes(ChangeContext(request_user, HistoryKind.FIELD_RULE, source=source), rule_changes, ledger)
        pull()
