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
The two default system Types - one carrying PERSON, one carrying PERSON_GROUP

Every system has exactly one default Type per marker: created by the system (``system_type``, so it cannot be
deleted), found by its marker and never by its name. Further Types may carry the markers; they are ordinary Types.

**Seeding is insert-if-missing** and runs wherever a system may lack them: every bring-up, after a configuration
reset (which clears every Type) and at the end of a configuration import (which replaces the system Types with the
file's). A marker that already has a system Type is left alone, so seeding again changes nothing. A default name
another Type already holds is replaced by the first free ``<name>_<n>``.

A partial unique index (``CmdbType.INDEX_KEYS``, ``special_type_system_default``) keeps two processes seeding the same
database at once from storing two defaults of a marker: the one that loses gets a duplicate-key refusal
"""
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from cmdb.manager.base_manager import BaseManager
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.schemas.schema_provider import SchemaProvider
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_types.person_types_constants import (
    DEFAULT_TYPE_SPECS,
    FIRST_FREE_NAME_SUFFIX,
    FREE_NAME_SEPARATOR,
    SEED_PROJECTION,
    SYSTEM_AUTHOR_ID,
    DefaultTypeSpec,
)
# -------------------------------------------------------------------------------------------------------------------- #

def free_type_name(name: str, taken: set[str]) -> str:
    """
    Answers the name itself when no Type holds it, else the first free ``<name>_<n>`` from n = 2

    Args:
        name (str): The wanted name
        taken (set[str]): The names stored Types hold

    Returns:
        str: A name no stored Type holds
    """
    if name not in taken:
        return name

    suffix: int = FIRST_FREE_NAME_SUFFIX

    while f"{name}{FREE_NAME_SEPARATOR}{suffix}" in taken:
        suffix += 1

    return f"{name}{FREE_NAME_SEPARATOR}{suffix}"


def markers_with_default(stored_types: Iterable[dict[str, Any]]) -> set[str]:
    """
    Answers the markers a stored system Type already carries - the markers whose default exists

    Args:
        stored_types (Iterable[dict[str, Any]]): The stored Types, at least their marker and system flag

    Returns:
        set[str]: The markers of the stored system Types
    """
    return {
        stored.get(TypeSchemaKey.SPECIAL_TYPE.value) for stored in stored_types
        if stored.get(TypeSchemaKey.SYSTEM_TYPE.value) is True and stored.get(TypeSchemaKey.SPECIAL_TYPE.value)
    }


def plan_default_person_types(stored_types: list[dict[str, Any]]) -> list[tuple[SpecialType, str]]:
    """
    Answers which default Types are missing and the name each is created with

    The names are chosen together, so the second default does not take a name the first one was just given

    Args:
        stored_types (list[dict[str, Any]]): Every stored Type, at least name, marker and system flag

    Returns:
        list[tuple[SpecialType, str]]: The missing markers with their free names, in seeding order; empty when both
            defaults exist
    """
    existing: set[str] = markers_with_default(stored_types)
    taken: set[str] = {
        stored[TypeSchemaKey.NAME.value] for stored in stored_types
        if isinstance(stored.get(TypeSchemaKey.NAME.value), str)
    }
    planned: list[tuple[SpecialType, str]] = []

    for marker, spec in DEFAULT_TYPE_SPECS.items():
        if marker.value in existing:
            continue

        name: str = free_type_name(spec.name, taken)
        taken.add(name)
        planned.append((marker, name))

    return planned


def _plain(value: Any) -> Any:
    """
    Turns a schema blueprint into plain JSON values - its keys and kinds are string enums

    Args:
        value (Any): The blueprint part

    Returns:
        Any: The same content with every enum member replaced by its string
    """
    return json.loads(json.dumps(value))


def build_default_person_type(marker: SpecialType, name: str, public_id: int,
                              creation_time: datetime | None = None) -> dict[str, Any]:
    """
    Builds the stored document of a default person Type, from the marker's schema

    Goes through the CmdbType model, so the document carries every key a Type created through the API carries (the
    default ACL included). The Type is a system Type authored by the system (``SYSTEM_AUTHOR_ID``), may not hold
    child locations, and its summary line and CI Explorer label show the marker's name field

    Args:
        marker (SpecialType): PERSON or PERSON_GROUP
        name (str): The name, already known to be free
        public_id (int): The public_id, already reserved
        creation_time (datetime | None): The creation time; now when None

    Raises:
        KeyError: For a marker without a default Type

    Returns:
        dict[str, Any]: The document to insert
    """
    spec: DefaultTypeSpec = DEFAULT_TYPE_SPECS[marker]
    blueprint: dict[str, Any] = _plain(SchemaProvider().get_schema(marker))

    data: dict[str, Any] = {
        TypeSchemaKey.PUBLIC_ID.value: public_id,
        TypeSchemaKey.NAME.value: name,
        TypeSchemaKey.LABEL.value: spec.label,
        TypeSchemaKey.AUTHOR_ID.value: SYSTEM_AUTHOR_ID,
        TypeSchemaKey.CREATION_TIME.value: creation_time or datetime.now(timezone.utc),
        TypeSchemaKey.SPECIAL_TYPE.value: marker.value,
        TypeSchemaKey.SYSTEM_TYPE.value: True,
        TypeSchemaKey.SELECTABLE_AS_PARENT.value: False,
        TypeSchemaKey.FIELDS.value: blueprint[TypeSchemaKey.FIELDS.value],
        TypeSchemaKey.CI_EXPLORER_LABEL.value: spec.summary_field,
        TypeSchemaKey.RENDER_META.value: {
            TypeSchemaKey.ICON.value: spec.icon,
            TypeSchemaKey.SECTIONS.value: blueprint[TypeSchemaKey.SECTIONS.value],
            TypeSchemaKey.SUMMARY.value: {TypeSchemaKey.FIELDS.value: [spec.summary_field]},
            TypeSchemaKey.EXTERNALS.value: [],
        },
    }

    return CmdbType.to_json(CmdbType.from_data(data))


def seed_default_person_types(types_manager: BaseManager, ledger: WriteLedger | None = None) -> list[int]:
    """
    Stores the default person Types that are missing - nothing when both exist

    One projected read of every Type, then the missing ones under ids reserved from the counter, in one batch. On a
    ledger the batch is recorded before it runs, so an undo removes exactly these

    Args:
        types_manager (BaseManager): The Types' manager of the database to seed
        ledger (WriteLedger | None): The caller's ledger, when the seeding is part of an undoable write

    Raises:
        BaseManagerGetError: When the Types or the ids could not be read
        BaseManagerInsertError: When the Types could not be stored - a duplicate-key refusal when another process
            stored a default meanwhile

    Returns:
        list[int]: The public_ids of the Types stored, empty when none was missing
    """
    stored: list[dict[str, Any]] = types_manager.find(criteria={}, projection=dict(SEED_PROJECTION))
    planned: list[tuple[SpecialType, str]] = plan_default_person_types(stored)

    if not planned:
        return []

    public_ids: list[int] = types_manager.reserve_public_ids(len(planned))
    documents: list[dict[str, Any]] = [
        build_default_person_type(marker, name, public_id)
        for (marker, name), public_id in zip(planned, public_ids)
    ]

    if ledger is not None:
        ledger.inserted_where(types_manager, {TypeSchemaKey.PUBLIC_ID.value: {'$in': public_ids}})

    types_manager.insert_many(documents, skip_public=True)

    return public_ids
