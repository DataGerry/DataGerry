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
Database update 20261012: persons and person groups become CmdbObjects of the PERSON / PERSON_GROUP SpecialTypes

Until now a person lived in ``management.person`` and a group in ``management.personGroup``, both outside the CMDB.
This update moves them into it:

1. **the types** - a CmdbType of each person SpecialType is created from its predefined schema, unless one exists
2. **the objects** - every stored person and group becomes an object of that type. A person keeps its display name,
   names, email and phone number; a group its name and email, and its members go into the MEMBERS person field -
   the union of both stored sides of the old two-sided membership, so a one-sided leftover is not lost
3. **the ISMS references** - every IsmsRiskAssessment and IsmsControlMeasureAssignment reference is rewritten from
   the old id to the new object id, by the reference's kind (an old person and an old group could share an id)
4. **the old collections** are renamed to ``<name>.migrated`` and kept as a backup

Nothing is done on a database holding no person and no group: the types are then created by an administrator, like
any other SpecialType.

Re-runnable: the old->new id mapping of step 2 is stored in ``management.personMigration`` as it is written, so a
run stopped part-way reuses every object already created instead of creating it again; step 3 stores a marker
there once its single bulk write went through and is skipped when the marker is present; step 4 runs last, and
once the old collections are renamed a further run finds nothing to migrate
"""
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.manager import SectionTemplatesManager
from cmdb.framework.datagerry_assistant.predefined_template_provider import PredefinedTemplateProvider
from cmdb.framework.datagerry_assistant.profile_type_constructor import ProfileTypeConstructor
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_constants import PersonField, PersonGroupField, PersonValueKey
from cmdb.models.special_type_model.schemas.schema_provider import SchemaProvider
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType, FieldKey, TypeSchemaKey
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.manager.person_reference_helper import (
    CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS,
    POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS,
    ref_type_key,
)

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

PERSON_COLLECTION: str = 'management.person'
PERSON_GROUP_COLLECTION: str = 'management.personGroup'
MIGRATION_COLLECTION: str = 'management.personMigration'
USERS_COLLECTION: str = 'management.users'
MIGRATED_SUFFIX: str = '.migrated'

PUBLIC_ID: str = 'public_id'
MONGO_ID: str = '_id'
ISMS_REMAPPED_MARKER: str = 'isms_remapped'

# The SpecialTypes, the name/label/icon of the type created for each, and the old collection each replaces
TARGETS: tuple[tuple[SpecialType, str, str, str, str], ...] = (
    (SpecialType.PERSON, 'dg_person', 'Person', 'fas fa-user', PERSON_COLLECTION),
    (SpecialType.PERSON_GROUP, 'dg_person_group', 'Person Group', 'fas fa-users', PERSON_GROUP_COLLECTION),
)

FALLBACK_AUTHOR_ID: int = 1


def text(document: dict[str, Any], key: str) -> str:
    """
    A text value of an old person or group document, '' when it is missing or no string

    Args:
        document (dict[str, Any]): The old document
        key (str): The key to read

    Returns:
        str: The value
    """
    value: Any = document.get(key)

    return value if isinstance(value, str) else ''


def int_ids(value: Any) -> list[int]:
    """
    The integer ids of an old id list, in order and without duplicates

    Args:
        value (Any): The stored list (or anything else, read as empty)

    Returns:
        list[int]: The ids
    """
    ids: list[int] = []

    for entry in value if isinstance(value, list) else []:
        if isinstance(entry, int) and not isinstance(entry, bool) and entry not in ids:
            ids.append(entry)

    return ids


def build_person_fields(person: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The object fields of a migrated person

    Args:
        person (dict[str, Any]): The old ``management.person`` document

    Returns:
        list[dict[str, Any]]: One entry per field of the PERSON schema
    """
    values: dict[str, Any] = {
        PersonField.DISPLAY_NAME.value: text(person, 'display_name') or
        ' '.join(part for part in (text(person, 'first_name'), text(person, 'last_name')) if part),
        PersonField.SALUTATION.value: None,
        PersonField.FIRST_NAME.value: text(person, 'first_name'),
        PersonField.LAST_NAME.value: text(person, 'last_name'),
        PersonField.EMAIL.value: text(person, 'email'),
        PersonField.PHONE_NUMBER.value: text(person, 'phone_number'),
    }

    return _fields_of(SpecialType.PERSON, values)


def build_group_fields(group: dict[str, Any], member_ids: list[int]) -> list[dict[str, Any]]:
    """
    The object fields of a migrated group

    Args:
        group (dict[str, Any]): The old ``management.personGroup`` document
        member_ids (list[int]): The NEW object ids of its members

    Returns:
        list[dict[str, Any]]: One entry per field of the PERSON_GROUP schema
    """
    values: dict[str, Any] = {
        PersonGroupField.NAME.value: text(group, 'name') or f"#{group.get(PUBLIC_ID)}",
        PersonGroupField.EMAIL.value: text(group, 'email'),
        PersonGroupField.MEMBERS.value: [
            {PersonValueKey.REF_TYPE.value: SpecialType.PERSON.value, PersonValueKey.ID.value: member_id}
            for member_id in member_ids
        ],
    }

    return _fields_of(SpecialType.PERSON_GROUP, values)


def _fields_of(special_type: SpecialType, values: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The object field entries of a SpecialType's schema, filled from the given values

    Args:
        special_type (SpecialType): PERSON or PERSON_GROUP
        values (dict[str, Any]): {field name: value}

    Returns:
        list[dict[str, Any]]: {'name', 'value', 'type'} per schema field, in schema order
    """
    # The schema holds enum members; the stored document holds their plain string values
    return [
        {
            'name': field[FieldKey.NAME].value,
            'value': values.get(field[FieldKey.NAME].value),
            'type': field[FieldKey.TYPE].value,
        }
        for field in SchemaProvider().get_schema(special_type)[TypeSchemaKey.FIELDS]
    ]


def remap_reference(document: dict[str, Any], key: str, kind: str | None, mapping: dict[str, dict[int, int]]) -> Any:
    """
    The new id of one old ISMS reference

    Args:
        document (dict[str, Any]): The ISMS document
        key (str): The reference key
        kind (str | None): 'PERSON' or 'PERSON_GROUP' - the reference's kind; None leaves the value as it is
        mapping (dict[str, dict[int, int]]): {kind: {old id: new id}}

    Returns:
        Any: The new id; None for an id that names nothing migrated; the stored value when it is unset
    """
    value: Any = document.get(key)

    if value is None or kind not in mapping:
        return value

    return mapping[kind].get(value)


def build_risk_assessment_remap(document: dict[str, Any], mapping: dict[str, dict[int, int]]) -> dict[str, Any]:
    """
    The ``$set`` rewriting every person reference of one IsmsRiskAssessment

    Args:
        document (dict[str, Any]): The stored IsmsRiskAssessment
        mapping (dict[str, dict[int, int]]): {kind: {old id: new id}}

    Returns:
        dict[str, Any]: {key: new value} for every reference key the document holds a value in
    """
    updates: dict[str, Any] = {}

    for key in POLYMORPHIC_RISK_ASSESSMENT_PERSON_KEYS:
        if document.get(key) is not None:
            updates[key] = remap_reference(document, key, document.get(ref_type_key(key)), mapping)

    assessor_key: str = RiskAssessmentKey.RISK_ASSESSOR_ID.value

    if document.get(assessor_key) is not None:
        updates[assessor_key] = remap_reference(document, assessor_key, SpecialType.PERSON.value, mapping)

    interviewed_key: str = RiskAssessmentKey.INTERVIEWED_PERSONS.value

    if isinstance(document.get(interviewed_key), list):
        updates[interviewed_key] = [
            mapping[SpecialType.PERSON.value][old_id]
            for old_id in int_ids(document[interviewed_key])
            if old_id in mapping[SpecialType.PERSON.value]
        ]

    return updates


def build_assignment_remap(document: dict[str, Any], mapping: dict[str, dict[int, int]]) -> dict[str, Any]:
    """
    The ``$set`` rewriting the person reference of one IsmsControlMeasureAssignment

    Args:
        document (dict[str, Any]): The stored IsmsControlMeasureAssignment
        mapping (dict[str, dict[int, int]]): {kind: {old id: new id}}

    Returns:
        dict[str, Any]: {key: new value} for the reference key when it holds a value
    """
    return {
        key: remap_reference(document, key, document.get(ref_type_key(key)), mapping)
        for key in CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS.polymorphic
        if document.get(key) is not None
    }


class Update20261012(BaseDatabaseUpdate):
    """
    Moves the persons and person groups into the CMDB as objects of the PERSON / PERSON_GROUP SpecialTypes

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261012


    def description(self) -> str:
        return "Migrates persons and person groups to objects of the Person / Person group special types"


    def start_update(self) -> None:
        """
        Creates the types and objects, rewrites the ISMS references, renames the old collections, bumps the version

        Raises:
            UpdaterException: If any read or write failed
        """
        try:
            persons: list[dict[str, Any]] = self._read_old(PERSON_COLLECTION)
            groups: list[dict[str, Any]] = self._read_old(PERSON_GROUP_COLLECTION)

            if persons or groups:
                self._migrate(persons, groups)

            for _, _, _, _, collection in TARGETS:
                self._rename_old(collection)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def _collection_names(self) -> list[str]:
        return self.dbm.get_collection(PERSON_COLLECTION, self.db_name).database.list_collection_names()


    def _read_old(self, collection: str) -> list[dict[str, Any]]:
        """
        Every document of an old collection, empty when it does not exist

        Args:
            collection (str): The old collection

        Returns:
            list[dict[str, Any]]: The documents
        """
        if collection not in self._collection_names():
            return []

        return self.dbm.find_all(collection, self.db_name, filter={})


    def _rename_old(self, collection: str) -> None:
        """
        Renames an old collection to '<name>.migrated', keeping it as a backup

        Args:
            collection (str): The old collection
        """
        names: list[str] = self._collection_names()

        if collection not in names:
            return

        target: str = f'{collection}{MIGRATED_SUFFIX}'

        if target in names:
            target = f'{target}.{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}'

        self.dbm.get_collection(collection, self.db_name).rename(target)


    def _author_id(self) -> int:
        """
        The author of the created types and objects: the user with the lowest public_id, normally the admin

        Returns:
            int: A user public_id
        """
        users: list[dict[str, Any]] = self.dbm.find_all(
            USERS_COLLECTION, self.db_name, filter={}, projection={PUBLIC_ID: 1}, sort=[(PUBLIC_ID, 1)], limit=1,
        )

        return users[0][PUBLIC_ID] if users else FALLBACK_AUTHOR_ID


    def _ensure_type(self, special_type: SpecialType, name: str, label: str, icon: str, author_id: int) -> int:
        """
        The CmdbType of a person SpecialType, created from its predefined schema when none exists

        Args:
            special_type (SpecialType): PERSON or PERSON_GROUP
            name (str): The name of a created type; suffixed when a type already carries it
            label (str): The label of a created type
            icon (str): The icon of a created type
            author_id (int): The author of a created type

        Returns:
            int: public_id of the type
        """
        existing: dict[str, Any] | None = self.dbm.find_one_by(
            CmdbType.COLLECTION, self.db_name, filter={TypeSchemaKey.SPECIAL_TYPE.value: special_type.value},
        )

        if existing:
            return existing[PUBLIC_ID]

        unique_name: str = name
        suffix: int = 1

        while self.dbm.find_one_by(CmdbType.COLLECTION, self.db_name, filter={TypeSchemaKey.NAME.value: unique_name}):
            suffix += 1
            unique_name = f'{name}_{suffix}'

        constructor = ProfileTypeConstructor(
            PredefinedTemplateProvider(SectionTemplatesManager(self.dbm, self.db_name)), author_id,
        )
        type_config: dict[str, Any] = constructor.create_special_type_config(
            SchemaProvider().get_schema(special_type), unique_name, label, icon, selectable_as_parent=False,
        )

        return self.dbm.insert(CmdbType.COLLECTION, self.db_name, type_config)


    def _mapping(self) -> dict[str, dict[int, int]]:
        """
        The old->new id mapping a previous, interrupted run stored

        Returns:
            dict[str, dict[int, int]]: {kind: {old id: new id}}
        """
        mapping: dict[str, dict[int, int]] = {SpecialType.PERSON.value: {}, SpecialType.PERSON_GROUP.value: {}}

        for row in self.dbm.find_all(MIGRATION_COLLECTION, self.db_name, filter={'kind': {'$exists': True}}):
            mapping.setdefault(row['kind'], {})[row['old_id']] = row['new_id']

        return mapping


    def _insert_object(self, kind: str, old_id: int, type_id: int, fields: list[dict[str, Any]], author_id: int) -> int:
        """
        Inserts one migrated object and records its mapping

        Args:
            kind (str): 'PERSON' or 'PERSON_GROUP'
            old_id (int): public_id of the old document
            type_id (int): public_id of the object's type
            fields (list[dict[str, Any]]): The object's fields
            author_id (int): The object's author

        Returns:
            int: public_id of the new object
        """
        new_id: int = self.dbm.reserve_public_ids(CmdbObject.COLLECTION, self.db_name, 1)[0]
        document: dict[str, Any] = CmdbObject.to_json(CmdbObject(
            public_id=new_id,
            type_id=type_id,
            author_id=author_id,
            fields=fields,
            creation_time=datetime.now(timezone.utc),
            special_type=kind,
        ))

        self.dbm.insert(CmdbObject.COLLECTION, self.db_name, document)
        self.dbm.insert(
            MIGRATION_COLLECTION, self.db_name, {'kind': kind, 'old_id': old_id, 'new_id': new_id}, skip_public=True,
        )

        return new_id


    def _migrate(self, persons: list[dict[str, Any]], groups: list[dict[str, Any]]) -> None:
        """
        Steps 1 to 3: the types, the objects and the ISMS references

        Args:
            persons (list[dict[str, Any]]): The old person documents
            groups (list[dict[str, Any]]): The old group documents
        """
        author_id: int = self._author_id()
        type_ids: dict[str, int] = {
            special_type.value: self._ensure_type(special_type, name, label, icon, author_id)
            for special_type, name, label, icon, _ in TARGETS
        }
        mapping: dict[str, dict[int, int]] = self._mapping()
        person_map: dict[int, int] = mapping[SpecialType.PERSON.value]
        group_map: dict[int, int] = mapping[SpecialType.PERSON_GROUP.value]

        for person in persons:
            if person.get(PUBLIC_ID) not in person_map:
                person_map[person[PUBLIC_ID]] = self._insert_object(
                    SpecialType.PERSON.value, person[PUBLIC_ID], type_ids[SpecialType.PERSON.value],
                    build_person_fields(person), author_id,
                )

        # The old membership was stored on both sides; the union keeps a side an earlier failure left alone
        members_of: dict[int, list[int]] = {group[PUBLIC_ID]: int_ids(group.get('group_members')) for group in groups}

        for person in persons:
            for group_id in int_ids(person.get('groups')):
                if group_id in members_of and person[PUBLIC_ID] not in members_of[group_id]:
                    members_of[group_id].append(person[PUBLIC_ID])

        for group in groups:
            if group.get(PUBLIC_ID) not in group_map:
                member_ids: list[int] = [
                    person_map[old_id] for old_id in members_of[group[PUBLIC_ID]] if old_id in person_map
                ]
                group_map[group[PUBLIC_ID]] = self._insert_object(
                    SpecialType.PERSON_GROUP.value, group[PUBLIC_ID], type_ids[SpecialType.PERSON_GROUP.value],
                    build_group_fields(group, member_ids), author_id,
                )

        # Projected explicitly: the manager's find hides '_id' by default, which would turn the marker into {}
        remapped: dict[str, Any] | None = self.dbm.find_one_by(
            MIGRATION_COLLECTION, self.db_name, filter={MONGO_ID: ISMS_REMAPPED_MARKER}, projection={MONGO_ID: 1},
        )

        if remapped is None:
            self._remap_isms(IsmsRiskAssessment.COLLECTION, build_risk_assessment_remap, mapping)
            self._remap_isms(IsmsControlMeasureAssignment.COLLECTION, build_assignment_remap, mapping)
            self.dbm.insert(MIGRATION_COLLECTION, self.db_name, {MONGO_ID: ISMS_REMAPPED_MARKER}, skip_public=True)


    def _remap_isms(self, collection: str, build_remap: Any, mapping: dict[str, dict[int, int]]) -> None:
        """
        Step 3 for one ISMS collection: every document's person references rewritten in one bulk write

        Args:
            collection (str): The ISMS collection
            build_remap (Callable): Builds the ``$set`` of one document
            mapping (dict[str, dict[int, int]]): {kind: {old id: new id}}
        """
        operations: list[UpdateOne] = []

        for document in self.dbm.find_all(collection, self.db_name, filter={}):
            updates: dict[str, Any] = build_remap(document, mapping)

            if updates:
                operations.append(UpdateOne({PUBLIC_ID: document[PUBLIC_ID]}, {'$set': updates}))

        if operations:
            self.dbm.bulk_write(collection, self.db_name, operations)
