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
Database update 20261119: the person and person group records become objects of the default person Types

Step 6 of the persons plan. Every ``management.person`` document becomes an object of the default PERSON Type, every
``management.personGroup`` document one of the default PERSON_GROUP Type, its ``members`` taken from the group's
``group_members`` (a person's own ``groups`` list is dropped - membership lives on the group side). Each old id is
recorded with its new object id in ``management.personIdMap`` (``kind``, ``old_id``, ``new_object_id``; unique per
kind and old id), every ISMS reference to a person or a group is rewritten to the new id (the ``*_ref_type`` siblings
are kept), the old person rights become entries of the default Types' ACL, which is switched on, and every migrated
object gets one CREATE log written by the system. The two old collections are renamed with ``_migrated``, not dropped.

The phases, in order, and why each is re-run safe:

    1. the default Types - insert-if-missing by marker: only this migration stores them, a re-run finds them
    2. the persons, then the groups - an old id gets its new id from the counter and the map entry is written FIRST;
       only then is the object written, and only where no object holds that id. A run stopped between the two writes
       finds the map entry and writes the missing object under it - never a second object for one record
    3. the ISMS references - each document is rewritten and flagged (``person_ids_migrated``) in one update, and only
       unflagged documents are read, so no id is ever mapped twice. The phase runs only while the old collections are
       not renamed yet: after the rename the flags are cleared, and a rewritten id must never meet the map again
    4. the creation logs - written only for migrated objects that carry no CREATE log yet
    5. the rights - merged into the ACL as a set, the ACL switched on: merging again changes nothing
    6. the rename - only a collection that exists and whose ``_migrated`` name is free
    7. the ISMS flags cleared

A database without an old record - a new one, whose empty old collections the bring-up created, or a configuration
import's staging database - is left alone: no default Type is seeded, no ACL switched on, nothing renamed. The
literals are frozen: this migration must keep meaning what it meant when it shipped
"""
import json
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any, Callable, Iterable

from flask import Flask

from cmdb.database.json_codec import default
from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate
from cmdb.manager import LogsManager, ObjectsManager, TypesManager
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.object_log_constants import ObjectLogKey
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.framework.person_types.default_person_types import seed_default_person_types
from cmdb.framework.rendering.render_constants import RenderObjectInfoKey, RenderTypeInfoKey

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# ------------------------------------------- frozen literals: collections ------------------------------------------- #
PERSONS: str = 'management.person'
PERSON_GROUPS: str = 'management.personGroup'
MIGRATED_SUFFIX: str = '_migrated'
ID_MAP: str = 'management.personIdMap'
TYPES: str = 'framework.types'
OBJECTS: str = 'framework.objects'
LOGS: str = 'framework.logs'
USER_GROUPS: str = 'management.groups'
RISK_ASSESSMENTS: str = 'isms.riskAssessment'
CONTROL_MEASURE_ASSIGNMENTS: str = 'isms.controlMeasureAssignment'

# ---------------------------------------------- frozen literals: keys ---------------------------------------------- #
PUBLIC_ID: str = 'public_id'
MONGO_ID: str = '_id'
PERSON: str = 'PERSON'
PERSON_GROUP: str = 'PERSON_GROUP'
MAP_KIND: str = 'kind'
MAP_OLD_ID: str = 'old_id'
MAP_NEW_ID: str = 'new_object_id'
MAP_INDEX_NAME: str = 'kind_old_id'
SPECIAL_TYPE: str = 'special_type'
SYSTEM_TYPE: str = 'system_type'
FIELDS: str = 'fields'
NAME: str = 'name'
VALUE: str = 'value'
FIELD_KIND: str = 'type'
ACL: str = 'acl'
ACTIVATED: str = 'activated'
ACL_GROUPS: str = 'groups'
INCLUDES: str = 'includes'
RIGHTS: str = 'rights'
ISMS_FLAG: str = 'person_ids_migrated'
REF_TYPE_SUFFIX: str = '_ref_type'

# The old documents' keys
PERSON_GROUPS_KEY: str = 'groups'
GROUP_MEMBERS_KEY: str = 'group_members'

# Each old person key with the base field of a PERSON object it fills
PERSON_FIELDS: dict[str, str] = {
    'display_name': 'display_name',
    'first_name': 'first_name',
    'last_name': 'last_name',
    'phone_number': 'phone_number',
    'email': 'email',
}
# Each old group key with the base field of a PERSON_GROUP object it fills; 'members' is built from group_members
GROUP_FIELDS: dict[str, str] = {'name': 'name', 'email': 'email'}
MEMBERS_FIELD: str = 'members'

# The ISMS keys holding a person or a group (with a '<key>_ref_type' sibling), a person only, a list of persons
POLYMORPHIC_KEYS: dict[str, tuple[str, ...]] = {
    RISK_ASSESSMENTS: ('risk_owner_id', 'responsible_persons_id', 'auditor_id'),
    CONTROL_MEASURE_ASSIGNMENTS: ('responsible_for_implementation_id',),
}
PERSON_ONLY_KEYS: dict[str, tuple[str, ...]] = {RISK_ASSESSMENTS: ('risk_assessor_id',)}
PERSON_LIST_KEYS: dict[str, tuple[str, ...]] = {RISK_ASSESSMENTS: ('interviewed_persons',)}

# The old rights per marker, each with the ACL permission it becomes and the object right that permission needs
RIGHT_PREFIXES: dict[str, str] = {
    PERSON: 'base.user-management.person',
    PERSON_GROUP: 'base.user-management.personGroup',
}
RIGHT_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ('add', 'CREATE'), ('view', 'READ'), ('edit', 'UPDATE'), ('delete', 'DELETE'),
)
OBJECT_RIGHTS: dict[str, str] = {
    'CREATE': ObjectRightName.ADD.value,
    'READ': ObjectRightName.VIEW.value,
    'UPDATE': ObjectRightName.EDIT.value,
    'DELETE': ObjectRightName.DELETE.value,
}
WILDCARD: str = '*'

# What the system writes as itself
SYSTEM_AUTHOR_ID: int = 0
SYSTEM_USER_NAME: str = 'DataGerry'
ADMIN_GROUP_ID: int = 1
OBJECT_VERSION: str = '1.0.0'
LOG_COMMENT: str = 'Migrated from the person records'
LOG_ACTION: str = 'action'
LOG_TYPE: str = 'log_type'
LOG_OBJECT_ID: str = 'object_id'
# What ManagerProvider reads off the application
APP_DATABASE_MANAGER: str = 'database_manager'
APP_CLOUD_MODE: str = 'cloud_mode'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    pure rules                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def holds_right(rights: Iterable[str], right_name: str) -> bool:
    """
    Whether a group's rights grant a right - by its name, or a wildcard of any parent (``base.*``, ``base.x.*``)

    Args:
        rights (Iterable[str]): The group's stored right names
        right_name (str): The qualified right name

    Returns:
        bool: True when granted
    """
    held: set[str] = set(rights)

    if right_name in held:
        return True

    parts: list[str] = right_name.split('.')

    return any('.'.join(parts[:depth] + [WILDCARD]) in held for depth in range(1, len(parts)))


def granted_permissions(rights: Iterable[str], marker: str) -> list[str]:
    """
    The ACL permissions a group's old person (or person group) rights become, in a fixed order

    Args:
        rights (Iterable[str]): The group's stored right names
        marker (str): PERSON or PERSON_GROUP

    Returns:
        list[str]: The permissions, empty when the group holds none of the rights
    """
    held: list[str] = list(rights)
    prefix: str = RIGHT_PREFIXES[marker]

    return [permission for right, permission in RIGHT_PERMISSIONS if holds_right(held, f'{prefix}.{right}')]


def missing_object_rights(rights: Iterable[str], permissions: Iterable[str]) -> list[str]:
    """
    The object rights a group lacks for the ACL permissions it is granted - without them the permission is of no use

    Args:
        rights (Iterable[str]): The group's stored right names
        permissions (Iterable[str]): The ACL permissions granted

    Returns:
        list[str]: The missing object rights, in permission order
    """
    held: list[str] = list(rights)

    return [OBJECT_RIGHTS[permission] for permission in permissions
            if not holds_right(held, OBJECT_RIGHTS[permission])]


def merged_acl(stored_acl: Any, grants: dict[int, list[str]]) -> dict[str, Any]:
    """
    The ACL with the grants merged in as a set per group, and switched on

    Args:
        stored_acl (Any): The stored ``acl`` value, whatever its shape
        grants (dict[int, list[str]]): The permissions per user group public_id

    Returns:
        dict[str, Any]: The ACL to store
    """
    acl: dict[str, Any] = stored_acl if isinstance(stored_acl, dict) else {}
    groups: Any = acl.get(ACL_GROUPS) if isinstance(acl.get(ACL_GROUPS), dict) else {}
    includes: dict[str, list[str]] = dict(groups.get(INCLUDES) or {})

    for group_id, permissions in grants.items():
        merged: set[str] = set(includes.get(str(group_id)) or []) | set(permissions)
        includes[str(group_id)] = [permission for permission in OBJECT_RIGHTS if permission in merged]

    return {ACTIVATED: True, ACL_GROUPS: {INCLUDES: includes}}


def person_values(person: dict[str, Any]) -> dict[str, Any]:
    """
    The base field values of the PERSON object an old person record becomes

    Args:
        person (dict[str, Any]): The old record

    Returns:
        dict[str, Any]: Value by base field name
    """
    return {field: person.get(key) for key, field in PERSON_FIELDS.items()}


def group_values(group: dict[str, Any], person_ids: dict[int, int]) -> tuple[dict[str, Any], list[Any]]:
    """
    The base field values of the PERSON_GROUP object an old group record becomes

    ``members`` are the new ids of the persons ``group_members`` names, in their order, each once

    Args:
        group (dict[str, Any]): The old record
        person_ids (dict[int, int]): New object id by old person id

    Returns:
        tuple[dict[str, Any], list[Any]]: Value by base field name, and the member ids naming no migrated person
    """
    values: dict[str, Any] = {field: group.get(key) for key, field in GROUP_FIELDS.items()}
    members: list[int] = []
    unknown: list[Any] = []

    for old_id in group.get(GROUP_MEMBERS_KEY) or []:
        new_id: int | None = person_ids.get(old_id)

        if new_id is None:
            unknown.append(old_id)
        elif new_id not in members:
            members.append(new_id)

    values[MEMBERS_FIELD] = members

    return values, unknown


def build_object(public_id: int, object_type: dict[str, Any], values: dict[str, Any],
                 creation_time: datetime) -> dict[str, Any]:
    """
    The stored document of a migrated object: every field of its Type, valued from ``values`` (else empty)

    Args:
        public_id (int): The reserved object id
        object_type (dict[str, Any]): The default Type the object belongs to
        values (dict[str, Any]): Value by field name
        creation_time (datetime): The creation time

    Returns:
        dict[str, Any]: The object document
    """
    return {
        PUBLIC_ID: public_id,
        'type_id': object_type[PUBLIC_ID],
        'active': True,
        FIELDS: [
            {NAME: field[NAME], VALUE: values.get(field[NAME]), FIELD_KIND: field.get(FIELD_KIND)}
            for field in object_type.get(FIELDS) or []
        ],
        'multi_data_sections': [],
        'creation_time': creation_time,
        'last_edit_time': None,
        'author_id': SYSTEM_AUTHOR_ID,
        'editor_id': None,
        'version': OBJECT_VERSION,
        SPECIAL_TYPE: object_type.get(SPECIAL_TYPE),
        'ci_explorer_tooltip': None,
    }


def rewritten_references(document: dict[str, Any], collection: str,
                         id_maps: dict[str, dict[int, int]]) -> tuple[dict[str, Any], int]:
    """
    The new values of an ISMS document's person references, and how many named no migrated record

    A polymorphic key maps through the map its ``_ref_type`` names; a person-only key through the persons'. An id
    without a migrated record is emptied (a list drops it): kept, it could name an unrelated object

    Args:
        document (dict[str, Any]): The ISMS document
        collection (str): Its collection
        id_maps (dict[str, dict[int, int]]): New object id by old id, per kind

    Returns:
        tuple[dict[str, Any], int]: The values to set (every reference key the document carries), the dropped count
    """
    updates: dict[str, Any] = {}
    dropped: int = 0

    keys: list[tuple[str, str | None]] = [(key, None) for key in POLYMORPHIC_KEYS.get(collection, ())]
    keys += [(key, PERSON) for key in PERSON_ONLY_KEYS.get(collection, ())]

    for key, kind in keys:
        old_id: Any = document.get(key)

        if old_id is None:
            continue

        new_id: int | None = id_maps.get(kind or document.get(f'{key}{REF_TYPE_SUFFIX}'), {}).get(old_id)
        dropped += new_id is None
        updates[key] = new_id

    for key in PERSON_LIST_KEYS.get(collection, ()):
        old_ids: list[Any] = document.get(key) or []
        new_ids: list[int] = [id_maps[PERSON][old_id] for old_id in old_ids if old_id in id_maps[PERSON]]
        dropped += len(old_ids) - len(new_ids)

        if key in document:
            updates[key] = new_ids

    return updates, dropped


def membership_disagreements(persons: list[dict[str, Any]], groups: list[dict[str, Any]]) -> int:
    """
    Counts the memberships a person lists that its group does not - those are dropped with the person's own list

    Args:
        persons (list[dict[str, Any]]): The old person records
        groups (list[dict[str, Any]]): The old group records

    Returns:
        int: The number of (person, group) pairs only the person side holds
    """
    members: dict[Any, set[Any]] = {group.get(PUBLIC_ID): set(group.get(GROUP_MEMBERS_KEY) or []) for group in groups}

    return sum(
        1 for person in persons for group_id in person.get(PERSON_GROUPS_KEY) or []
        if person.get(PUBLIC_ID) not in members.get(group_id, set())
    )

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  creation logs                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def render_objects(dbm: MongoDatabaseManager, db_name: str, object_ids: list[int]) -> list[Any]:
    """
    Renders the migrated objects as the system - what their CREATE logs store

    The renderer reads its managers through ``ManagerProvider``, which needs an application context: a plain Flask app's
    is pushed, carrying the two attributes the provider reads - this database manager and cloud mode on - the render
    user carrying this database (the provider routes by the user's database when cloud mode is on). The administrator
    group decides what the render may read

    Args:
        dbm (MongoDatabaseManager): The update's database manager
        db_name (str): The database
        object_ids (list[int]): The objects to render

    Returns:
        list[Any]: The render results
    """
    # pylint: disable=import-outside-toplevel
    # Imported here: the renderer is loaded only by the run that writes logs, never when the updaters are listed
    from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender

    app: Flask = Flask(__name__)
    setattr(app, APP_DATABASE_MANAGER, dbm)
    setattr(app, APP_CLOUD_MODE, True)
    render_user: CmdbUser = CmdbUser(public_id=SYSTEM_AUTHOR_ID, user_name=SYSTEM_USER_NAME, active=True,
                                     group_id=ADMIN_GROUP_ID, database=db_name)

    with app.app_context():
        objects = ObjectsManager(dbm, db_name).find_objects({PUBLIC_ID: {'$in': object_ids}})

        return list(CmdbMultiRender(objects, render_user).result() or []) if objects else []


def creation_log_entry(render_result: Any) -> dict[str, Any]:
    """
    The CREATE log entry of one migrated object, written by the system

    Args:
        render_result (Any): The object's render result

    Returns:
        dict[str, Any]: The log-specific fields ``LogsManager.insert_logs`` stores
    """
    return {
        ObjectLogKey.OBJECT_ID.value: render_result.object_information[RenderObjectInfoKey.OBJECT_ID.value],
        ObjectLogKey.VERSION.value: render_result.object_information[RenderObjectInfoKey.VERSION.value],
        ObjectLogKey.USER_ID.value: SYSTEM_AUTHOR_ID,
        ObjectLogKey.USER_NAME.value: SYSTEM_USER_NAME,
        ObjectLogKey.COMMENT.value: LOG_COMMENT,
        ObjectLogKey.RENDER_STATE.value: json.dumps(render_result, default=default).encode('UTF-8'),
        ObjectLogKey.TYPE_ID.value: render_result.type_information.get(RenderTypeInfoKey.TYPE_ID.value),
    }

# ---------------------------------------------- Update20261119 - CLASS ---------------------------------------------- #

class Update20261119(BaseDatabaseUpdate):
    """
    Moves the person and person group records into objects of the default person Types

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261119


    def description(self) -> str:
        return "Migrates the person and person group records into objects of the default person Types"


    def start_update(self) -> None:
        """
        Runs every phase (module docstring) when the database holds the old collections, then bumps the version

        Raises:
            UpdaterException: If any read or write fails
        """
        try:
            if self._has_legacy_collections():
                self._migrate()

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def _migrate(self) -> None:
        """Runs the phases in order"""
        types: dict[str, dict[str, Any]] = self._default_types()

        if not self._renamed():
            self.dbm.get_collection(ID_MAP, self.db_name).create_index(
                [(MAP_KIND, 1), (MAP_OLD_ID, 1)], name=MAP_INDEX_NAME, unique=True,
            )
            persons: list[dict[str, Any]] = self._records(PERSONS)
            groups: list[dict[str, Any]] = self._records(PERSON_GROUPS)
            self._migrate_records(PERSON, persons, types[PERSON], lambda record, _ids: (person_values(record), []))
            person_ids: dict[int, int] = self._id_map(PERSON)
            self._migrate_records(PERSON_GROUP, groups, types[PERSON_GROUP], group_values)

            if disagreements := membership_disagreements(persons, groups):
                LOGGER.warning("[updater_20261119] %s membership(s) only the person record listed were dropped",
                               disagreements)

            self._rewrite_isms({PERSON: person_ids, PERSON_GROUP: self._id_map(PERSON_GROUP)})

        self._write_creation_logs()
        self._grant_person_rights(types)
        self._rename_legacy()
        self._clear_isms_flags()

# ------------------------------------------------------- reads ------------------------------------------------------ #

    def _collection_names(self) -> set[str]:
        """The database's collection names"""
        return set(self.dbm.connector.get_database(self.db_name).list_collection_names())


    def _has_legacy_collections(self) -> bool:
        """
        Whether there is anything to migrate: an old record, or a renamed collection a stopped run left

        Empty old collections are nothing: the bring-up creates them in every database, a new one too, and a database
        built at the current schema must stay as it is

        Returns:
            bool: True when the migration has to run (or finish)
        """
        if self._renamed():
            return True

        return any(self.dbm.get_collection(collection, self.db_name).find_one({}, {MONGO_ID: 1}) is not None
                   for collection in (PERSONS, PERSON_GROUPS))


    def _renamed(self) -> bool:
        """Whether a rename already ran - then the records and the ISMS references are migrated"""
        renamed: set[str] = {f'{PERSONS}{MIGRATED_SUFFIX}', f'{PERSON_GROUPS}{MIGRATED_SUFFIX}'}

        return bool(renamed & self._collection_names())


    def _records(self, collection: str) -> list[dict[str, Any]]:
        """Every old record of a collection, by public_id"""
        return list(self.dbm.get_collection(collection, self.db_name).find({}, sort=[(PUBLIC_ID, 1)]))


    def _id_map(self, kind: str) -> dict[int, int]:
        """New object id by old id, for one kind"""
        return {entry[MAP_OLD_ID]: entry[MAP_NEW_ID]
                for entry in self.dbm.get_collection(ID_MAP, self.db_name).find({MAP_KIND: kind})}


    def _default_types(self) -> dict[str, dict[str, Any]]:
        """
        The default Type of each marker, stored first where missing

        Returns:
            dict[str, dict[str, Any]]: The stored default Type by marker
        """
        seed_default_person_types(TypesManager(self.dbm, self.db_name))
        types = self.dbm.get_collection(TYPES, self.db_name)

        return {marker: types.find_one({SPECIAL_TYPE: marker, SYSTEM_TYPE: True}) for marker in (PERSON, PERSON_GROUP)}

# --------------------------------------------------- the records ---------------------------------------------------- #

    def _migrate_records(self, kind: str, records: list[dict[str, Any]], object_type: dict[str, Any],
                         values_of: Callable[[dict[str, Any], dict[int, int]], tuple[dict[str, Any], list[Any]]]
                         ) -> None:
        """
        Gives each record its new id (map entry first), then writes the object where none holds that id

        Args:
            kind (str): PERSON or PERSON_GROUP
            records (list[dict[str, Any]]): The old records
            object_type (dict[str, Any]): The default Type of the kind
            values_of (Callable): The record's field values and the member ids naming no migrated person
        """
        id_map: dict[int, int] = self._assign_new_ids(kind, records)
        objects = self.dbm.get_collection(OBJECTS, self.db_name)
        existing: set[int] = {document[PUBLIC_ID] for document in objects.find(
            {PUBLIC_ID: {'$in': list(id_map.values())}}, {PUBLIC_ID: 1})}
        person_ids: dict[int, int] = self._id_map(PERSON)
        now: datetime = datetime.now(timezone.utc)
        documents: list[dict[str, Any]] = []
        unknown_members: int = 0

        for record in records:
            if id_map[record[PUBLIC_ID]] in existing:
                continue

            values, unknown = values_of(record, person_ids)
            unknown_members += len(unknown)
            documents.append(build_object(id_map[record[PUBLIC_ID]], object_type, values, now))

        if documents:
            objects.insert_many(documents)

        LOGGER.info("[updater_20261119] %s %s record(s) written as objects", len(documents), kind)

        if unknown_members:
            LOGGER.warning("[updater_20261119] %s group member id(s) named no person and were dropped",
                           unknown_members)


    def _assign_new_ids(self, kind: str, records: list[dict[str, Any]]) -> dict[int, int]:
        """
        Draws a new object id for every record without one and records the pair in the map - before any object exists

        Args:
            kind (str): PERSON or PERSON_GROUP
            records (list[dict[str, Any]]): The old records

        Returns:
            dict[int, int]: New object id by old id, every record of the kind included
        """
        id_map: dict[int, int] = self._id_map(kind)
        unmapped: list[int] = [record[PUBLIC_ID] for record in records if record[PUBLIC_ID] not in id_map]

        if unmapped:
            new_ids: list[int] = self.dbm.reserve_public_ids(OBJECTS, self.db_name, len(unmapped))
            self.dbm.get_collection(ID_MAP, self.db_name).insert_many([
                {MAP_KIND: kind, MAP_OLD_ID: old_id, MAP_NEW_ID: new_id} for old_id, new_id in zip(unmapped, new_ids)
            ])
            id_map.update(zip(unmapped, new_ids))

        return id_map

# ------------------------------------------------ the ISMS references ----------------------------------------------- #

    def _rewrite_isms(self, id_maps: dict[str, dict[int, int]]) -> None:
        """
        Rewrites each unflagged ISMS document's person references and flags it, in one update per document

        Args:
            id_maps (dict[str, dict[int, int]]): New object id by old id, per kind
        """
        for collection in (RISK_ASSESSMENTS, CONTROL_MEASURE_ASSIGNMENTS):
            documents = self.dbm.get_collection(collection, self.db_name)
            dropped: int = 0

            for document in documents.find({ISMS_FLAG: {'$ne': True}}):
                updates, lost = rewritten_references(document, collection, id_maps)
                dropped += lost
                documents.update_one({MONGO_ID: document[MONGO_ID], ISMS_FLAG: {'$ne': True}},
                                     {'$set': {**updates, ISMS_FLAG: True}})

            if dropped:
                LOGGER.warning("[updater_20261119] %s: %s reference(s) named no migrated record and were emptied",
                               collection, dropped)


    def _clear_isms_flags(self) -> None:
        """Removes the per-document flags once the old collections are renamed"""
        for collection in (RISK_ASSESSMENTS, CONTROL_MEASURE_ASSIGNMENTS):
            self.dbm.get_collection(collection, self.db_name).update_many(
                {ISMS_FLAG: {'$exists': True}}, {'$unset': {ISMS_FLAG: ''}},
            )

# ---------------------------------------------- logs, rights, rename ------------------------------------------------ #

    def _write_creation_logs(self) -> None:
        """One CREATE log per migrated object that carries none yet, rendered as the system"""
        object_ids: list[int] = [entry[MAP_NEW_ID] for entry in self.dbm.get_collection(ID_MAP, self.db_name).find()]

        if not object_ids:
            return

        logged: set[int] = {entry[LOG_OBJECT_ID] for entry in self.dbm.get_collection(LOGS, self.db_name).find(
            {LOG_TYPE: CmdbObjectLog.__name__, LOG_ACTION: LogAction.CREATE.value,
             LOG_OBJECT_ID: {'$in': object_ids}}, {LOG_OBJECT_ID: 1})}
        missing: list[int] = [object_id for object_id in object_ids if object_id not in logged]

        if missing:
            entries = [creation_log_entry(result) for result in render_objects(self.dbm, self.db_name, missing)]
            LogsManager(self.dbm, self.db_name).insert_logs(LogAction.CREATE, CmdbObjectLog.__name__, entries)


    def _grant_person_rights(self, types: dict[str, dict[str, Any]]) -> None:
        """
        Turns the old person rights of every user group into entries of the default Types' ACL, and switches it on

        A group granted a permission without the object right it needs is reported - no object right is added

        Args:
            types (dict[str, dict[str, Any]]): The default Type by marker
        """
        user_groups: list[dict[str, Any]] = list(self.dbm.get_collection(USER_GROUPS, self.db_name).find())

        for marker, object_type in types.items():
            grants: dict[int, list[str]] = {}

            for group in user_groups:
                permissions: list[str] = granted_permissions(group.get(RIGHTS) or [], marker)

                if not permissions:
                    continue

                grants[group[PUBLIC_ID]] = permissions

                if missing := missing_object_rights(group.get(RIGHTS) or [], permissions):
                    LOGGER.warning("[updater_20261119] Group %s (%s) may %s %s objects but lacks %s",
                                   group[PUBLIC_ID], group.get(NAME), permissions, marker, missing)

            self.dbm.get_collection(TYPES, self.db_name).update_one(
                {PUBLIC_ID: object_type[PUBLIC_ID]}, {'$set': {ACL: merged_acl(object_type.get(ACL), grants)}},
            )


    def _rename_legacy(self) -> None:
        """Renames each old collection that exists and whose '_migrated' name is free"""
        names: set[str] = self._collection_names()

        for collection in (PERSONS, PERSON_GROUPS):
            target: str = f'{collection}{MIGRATED_SUFFIX}'

            if collection in names and target not in names:
                self.dbm.get_collection(collection, self.db_name).rename(target)
