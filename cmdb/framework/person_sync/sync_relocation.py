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
Moving synced persons to their new target Type - or leaving a deactivated copy behind

**The plan** (``plan_relocations``) finds every linked person of an existing user that lives in another Type than the
new settings choose for it, and judges each (``sync_relocation_rules``). One read each: the linked persons' links, the
moving persons, the user ids, the Types, the objects referencing them, their object relations and definitions, their
location nodes.

**A move keeps the person** - its ``public_id`` and every reference to it. The object takes its new Type and the
values the Type keeps (``sync_documents.relocated_person``); what is stamped with the Type follows: the object's
change logs, its object relations' side and their logs. Its fingerprint goes, so the next sync rewrites the synced
values under the new Type's rules. A move is the sync's own operation - no object route changes a Type.

**A copy** (a blocked person, when the caller chose it) leaves the old person as a former user's - unlinked, unlocked,
deactivated, every reference kept on it - and creates a new person in the new Type; the mapped person groups' members
move to the new one.

Everything is written into the caller's ledger, so a relocation stands or falls whole
"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from cmdb.manager import (
    LocationsManager,
    LogsManager,
    ObjectRelationLogsManager,
    ObjectRelationsManager,
    RelationsManager,
)
from cmdb.manager.object_scope_blocks import ObjectScopeBlocks
from cmdb.models.location_model.location_constants import LocationKey
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE, ObjectLogKey
from cmdb.models.log_model.object_relation_log_constants import ObjectRelationLogKey
from cmdb.database.database_constants import PUBLIC_ID_FIELD
from cmdb.models.object_model import (
    OBJECT_SYNC_KEYS,
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    CmdbObjectSyncKey,
    SystemRefKind,
    extract_field_value,
)
from cmdb.models.object_relation_model.object_relation_constants import ObjectRelationKey
from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.special_type_model.person_type_constants import PersonGroupField
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser

from cmdb.framework.object_field_value_rules import build_field_value_rules
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_types.person_memberships import group_members, holding_members_criteria
from cmdb.framework.person_sync.person_sync_constants import KIND_PATH, RELOCATION_REFERENCE_KINDS
from cmdb.framework.person_sync.sync_documents import (
    build_person_document,
    former_person,
    group_after_sync,
    linked_record_id,
    relocated_person,
)
from cmdb.framework.person_sync.sync_engine import (
    SyncContext,
    SyncResult,
    insert_linked_object,
    plan_edit_write,
    write_edit,
)
from cmdb.framework.person_sync.sync_mapping import SyncedPerson, synced_person_from_user
from cmdb.framework.person_sync.sync_relocation_rules import (
    PersonRelocation,
    location_blockers,
    lost_value_blockers,
    reference_blockers,
    relation_blockers,
)
from cmdb.framework.person_sync.sync_settings import UserSyncSettings
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RelocationStores',
    'plan_relocations',
    'relocate_persons',
]

# The collections a restamp names in an undo residue
OBJECT_LOGS_LABEL: str = 'object logs'
OBJECT_RELATIONS_LABEL: str = 'object relations'
OBJECT_RELATION_LOGS_LABEL: str = 'object relation logs'


@dataclass(frozen=True)
class RelocationStores:
    """
    The managers of what is stamped with an object's Type, beside the sync's own

    Attributes:
        logs_manager (LogsManager): The object change logs
        relations_manager (RelationsManager): The relation definitions
        object_relations_manager (ObjectRelationsManager): The object relations
        relation_logs_manager (ObjectRelationLogsManager): The object relation logs
        locations_manager (LocationsManager): The location tree
    """
    logs_manager: LogsManager
    relations_manager: RelationsManager
    object_relations_manager: ObjectRelationsManager
    relation_logs_manager: ObjectRelationLogsManager
    locations_manager: LocationsManager

# ------------------------------------------------------- plan ------------------------------------------------------- #

def _misplaced(context: SyncContext, users: UserSyncSettings) -> list[PersonRelocation]:
    """
    Reads the linked persons of existing users that live outside their new target - unjudged

    Args:
        context (SyncContext): The managers
        users (UserSyncSettings): The new user sync settings

    Returns:
        list[PersonRelocation]: One per person to relocate, in user id order
    """
    linked: list[dict[str, Any]] = context.objects_manager.find(
        criteria={KIND_PATH: SystemRefKind.USER.value},
        projection={CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.SYSTEM_REF.value: 1,
                    CmdbObjectKey.TYPE_ID.value: 1},
    )
    candidates: list[PersonRelocation] = []

    for person in linked:
        user_id: int = linked_record_id(person)
        target_id: int | None = users.type_overrides.get(user_id, users.default_type_id)

        if target_id is not None and target_id != person[CmdbObjectKey.TYPE_ID.value]:
            candidates.append(PersonRelocation(user_id, person[CmdbObjectKey.PUBLIC_ID.value],
                                               person[CmdbObjectKey.TYPE_ID.value], target_id))

    if not candidates:
        return []

    existing: set[int] = set(context.users_manager.get_user_lookup(sorted({c.user_id for c in candidates})))

    return sorted((c for c in candidates if c.user_id in existing), key=lambda c: c.user_id)


def _holders(context: SyncContext, person_ids: list[int]) -> list[dict[str, Any]]:
    """
    Reads the objects holding any of the persons in a reference field or a reference row

    Args:
        context (SyncContext): The managers
        person_ids (list[int]): The persons

    Returns:
        list[dict[str, Any]]: The holders - their id, Type, fields and multi-data sections
    """
    entry_match: dict[str, Any] = {'$elemMatch': {
        CmdbObjectFieldKey.TYPE.value: {'$in': list(RELOCATION_REFERENCE_KINDS)},
        CmdbObjectFieldKey.VALUE.value: {'$in': person_ids},
    }}
    row_path: str = (
        f'{CmdbObjectKey.MULTI_DATA_SECTIONS.value}.{CmdbObjectMdsKey.VALUES.value}.{CmdbObjectMdsRowKey.DATA.value}'
    )

    return context.objects_manager.find(
        criteria={'$or': [{CmdbObjectKey.FIELDS.value: entry_match}, {row_path: entry_match}]},
        projection={CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.TYPE_ID.value: 1, CmdbObjectKey.FIELDS.value: 1,
                    CmdbObjectKey.MULTI_DATA_SECTIONS.value: 1},
    )


def plan_relocations(context: SyncContext, stores: RelocationStores,
                     users: UserSyncSettings) -> list[PersonRelocation]:
    """
    Finds every synced person the new settings place in another Type, and why each cannot move

    Args:
        context (SyncContext): The managers
        stores (RelocationStores): The relations, logs and locations
        users (UserSyncSettings): The new user sync settings, judged already

    Returns:
        list[PersonRelocation]: The relocations in user id order, each with its blockers
    """
    candidates: list[PersonRelocation] = _misplaced(context, users)

    if not candidates:
        return []

    person_ids: list[int] = sorted(c.person_id for c in candidates)
    persons: dict[int, dict[str, Any]] = {
        person[CmdbObjectKey.PUBLIC_ID.value]: person
        for person in context.objects_manager.find(criteria={CmdbObjectKey.PUBLIC_ID.value: {'$in': person_ids}})
    }
    holders: list[dict[str, Any]] = _holders(context, person_ids)
    types: dict[int, CmdbType] = context.types_manager.get_types_lookup(sorted(
        {c.to_type_id for c in candidates} | {holder[CmdbObjectKey.TYPE_ID.value] for holder in holders}))
    relations: list[dict[str, Any]] = stores.object_relations_manager.find(
        criteria=stores.object_relations_manager.get_relations_of_objects_query(person_ids))
    definitions: dict[int, dict[str, Any]] = {
        definition[RelationKey.PUBLIC_ID.value]: definition
        for definition in stores.relations_manager.find(criteria={RelationKey.PUBLIC_ID.value: {'$in': sorted(
            {relation[ObjectRelationKey.RELATION_ID.value] for relation in relations})}})
    } if relations else {}
    placed: set[int] = {
        node[LocationKey.OBJECT_ID.value] for node in stores.locations_manager.find(
            criteria={LocationKey.OBJECT_ID.value: {'$in': person_ids}},
            projection={LocationKey.OBJECT_ID.value: 1})
    }

    return [
        replace(candidate, blockers=tuple(
            lost_value_blockers(persons[candidate.person_id], types[candidate.to_type_id])
            + reference_blockers(candidate.person_id, candidate.to_type_id, holders, types)
            + relation_blockers(candidate.person_id, candidate.to_type_id, relations, definitions)
            + location_blockers(candidate.person_id, placed)
        ))
        for candidate in candidates
    ]

# ------------------------------------------------------ writes ------------------------------------------------------ #

def _restamp_group(manager: Any, ledger: WriteLedger, label: str, key: str, ids: list[int], old_value: Any,
                   new_value: int) -> None:
    """
    Sets one Type key on the given documents, recording first how to set it back

    Args:
        manager (Any): The manager of the collection
        ledger (WriteLedger): Records the inverse
        label (str): The collection, as a residue names it
        key (str): The Type key
        ids (list[int]): The documents, all holding ``old_value``
        old_value (Any): What they hold
        new_value (int): The new Type id
    """
    selection: dict[str, Any] = {PUBLIC_ID_FIELD: {'$in': ids}}

    def _undo() -> None:
        manager.update_many_raw(selection, {'$set': {key: old_value}})

    def _verify() -> bool:
        return manager.count_documents({**selection, key: old_value}) == len(ids)

    ledger.compensated(label, f"{key} {old_value} -> {new_value} of {ids}", _undo, _verify)
    manager.update_many_raw(selection, {'$set': {key: new_value}})


def _restamp(manager: Any, ledger: WriteLedger, label: str, criteria: dict[str, Any], key: str,
             new_value: int) -> None:
    """
    Sets one Type key on every matching document - grouped by the value each had, so the undo puts each back

    Args:
        manager (Any): The manager of the collection
        ledger (WriteLedger): Records each inverse
        label (str): The collection, as a residue names it
        criteria (dict[str, Any]): The documents to restamp
        key (str): The Type key
        new_value (int): The new Type id
    """
    stamped: list[dict[str, Any]] = manager.find(criteria={**criteria, key: {'$ne': new_value}},
                                                 projection={PUBLIC_ID_FIELD: 1, key: 1})
    by_value: dict[Any, list[int]] = {}

    for document in stamped:
        by_value.setdefault(document.get(key), []).append(document[PUBLIC_ID_FIELD])

    for old_value, ids in by_value.items():
        _restamp_group(manager, ledger, label, key, ids, old_value, new_value)


def _move(context: SyncContext, stores: RelocationStores, ledger: WriteLedger, stored: dict[str, Any],
          to_type: CmdbType, result: SyncResult) -> None:
    """
    Moves a person to its new Type in place, and what is stamped with its Type

    Args:
        context (SyncContext): The managers and the acting user
        stores (RelocationStores): The relations, logs and locations
        ledger (WriteLedger): Records every write
        stored (dict[str, Any]): The person as stored
        to_type (CmdbType): Its new Type
        result (SyncResult): Receives the edit
    """
    person_id: int = stored[CmdbObjectKey.PUBLIC_ID.value]
    after: dict[str, Any] = relocated_person(stored, to_type)
    plan, operations = plan_edit_write(context.acting_user, stored, after, (CmdbObjectSyncKey.SYNC_HASH.value,))
    operations['$set'][CmdbObjectKey.TYPE_ID.value] = to_type.public_id
    operations['$set'][CmdbObjectKey.MULTI_DATA_SECTIONS.value] = after[CmdbObjectKey.MULTI_DATA_SECTIONS.value]

    ledger.updated(context.objects_manager, person_id, stored)
    context.objects_manager.update({CmdbObjectKey.PUBLIC_ID.value: person_id}, operations)
    # The new Type may not declare the interface rows the person had - the ledger's undo restores the stored block
    ObjectScopeBlocks(context.objects_manager).refresh([person_id])
    result.edits[person_id] = plan

    _restamp(stores.logs_manager, ledger, OBJECT_LOGS_LABEL,
             {ObjectLogKey.LOG_TYPE.value: OBJECT_LOG_TYPE, ObjectLogKey.OBJECT_ID.value: person_id},
             ObjectLogKey.TYPE_ID.value, to_type.public_id)
    _restamp(stores.object_relations_manager, ledger, OBJECT_RELATIONS_LABEL,
             {ObjectRelationKey.RELATION_PARENT_ID.value: person_id},
             ObjectRelationKey.RELATION_PARENT_TYPE_ID.value, to_type.public_id)
    _restamp(stores.object_relations_manager, ledger, OBJECT_RELATIONS_LABEL,
             {ObjectRelationKey.RELATION_CHILD_ID.value: person_id},
             ObjectRelationKey.RELATION_CHILD_TYPE_ID.value, to_type.public_id)
    _restamp(stores.relation_logs_manager, ledger, OBJECT_RELATION_LOGS_LABEL,
             {ObjectRelationLogKey.OBJECT_RELATION_PARENT_ID.value: person_id},
             ObjectRelationLogKey.RELATION_PARENT_TYPE_ID.value, to_type.public_id)
    _restamp(stores.relation_logs_manager, ledger, OBJECT_RELATION_LOGS_LABEL,
             {ObjectRelationLogKey.OBJECT_RELATION_CHILD_ID.value: person_id},
             ObjectRelationLogKey.RELATION_CHILD_TYPE_ID.value, to_type.public_id)


def _copy(context: SyncContext, ledger: WriteLedger, stored: dict[str, Any], user: CmdbUser, to_type: CmdbType,
          result: SyncResult) -> None:
    """
    Leaves the old person deactivated and unlinked, creates a new one in the new Type and moves the mapped groups'
    membership to it

    The new person is active and fingerprinted only while the user sync is on - off, it is created as the switch-off
    leaves every person

    Args:
        context (SyncContext): The managers, the settings the relocation runs on and the acting user
        ledger (WriteLedger): Records every write
        stored (dict[str, Any]): The old person as stored
        user (CmdbUser): Its user
        to_type (CmdbType): The new Type
        result (SyncResult): Receives the edits and the create
    """
    old_id: int = stored[CmdbObjectKey.PUBLIC_ID.value]
    result.edits[old_id] = write_edit(context, ledger, stored, former_person(stored), OBJECT_SYNC_KEYS)
    result.config_items_changed = True

    synced: SyncedPerson = synced_person_from_user(user, build_field_value_rules(to_type.get_fields()))

    def _new_person(public_id: int) -> dict[str, Any]:
        document: dict[str, Any] = build_person_document(
            public_id, to_type, user.public_id, synced, context.acting_user.public_id, datetime.now(timezone.utc),
        )

        if not context.settings.users.active:
            document[CmdbObjectKey.ACTIVE.value] = False
            document.pop(CmdbObjectSyncKey.SYNC_HASH.value, None)

        return document

    new_id: int = insert_linked_object(context, ledger, _new_person)
    result.created.append(new_id)
    groups: list[dict[str, Any]] = context.objects_manager.find(
        criteria={KIND_PATH: SystemRefKind.USER_GROUP.value, **holding_members_criteria([old_id])})
    types: dict[int, CmdbType] = context.types_manager.get_types_lookup(
        sorted({group[CmdbObjectKey.TYPE_ID.value] for group in groups})) if groups else {}

    for group in groups:
        if (group_type := types.get(group[CmdbObjectKey.TYPE_ID.value])) is not None:
            result.edits[group[CmdbObjectKey.PUBLIC_ID.value]] = write_edit(context, ledger, group, group_after_sync(
                group, group_type, extract_field_value(group, PersonGroupField.NAME.value),
                [new_id if member == old_id else member for member in group_members(group)]))


def relocate_persons(context: SyncContext, stores: RelocationStores, ledger: WriteLedger,
                     relocations: list[PersonRelocation], copy_blocked: bool) -> SyncResult:
    """
    Moves every person that can move and copies every blocked one - the caller refused the change when blocked
    persons were not to be copied

    Args:
        context (SyncContext): The managers, the new settings and the acting user
        stores (RelocationStores): The relations, logs and locations
        ledger (WriteLedger): Records every write
        relocations (list[PersonRelocation]): The planned relocations (``plan_relocations``)
        copy_blocked (bool): Whether a blocked person is copied; refused otherwise

    Raises:
        ValueError: When a blocked person is not to be copied

    Returns:
        SyncResult: The persons and groups edited, the persons created
    """
    result = SyncResult()

    if not relocations:
        return result

    if not copy_blocked and any(relocation.blocked for relocation in relocations):
        raise ValueError("Blocked persons are only relocated as copies")

    ids: list[int] = sorted(relocation.person_id for relocation in relocations)
    persons: dict[int, dict[str, Any]] = {
        person[CmdbObjectKey.PUBLIC_ID.value]: person
        for person in context.objects_manager.find(criteria={CmdbObjectKey.PUBLIC_ID.value: {'$in': ids}})
    }
    types: dict[int, CmdbType] = context.types_manager.get_types_lookup(
        sorted({relocation.to_type_id for relocation in relocations}))
    users: dict[int, CmdbUser] = context.users_manager.get_user_lookup(
        sorted({relocation.user_id for relocation in relocations}))

    for relocation in relocations:
        stored: dict[str, Any] = persons[relocation.person_id]
        to_type: CmdbType = types[relocation.to_type_id]

        if relocation.blocked:
            _copy(context, ledger, stored, users[relocation.user_id], to_type, result)
        else:
            _move(context, stores, ledger, stored, to_type, result)

    return result
