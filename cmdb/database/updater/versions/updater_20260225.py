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
Database update 20260225: normalise every object's stored field entries against its type schema

A stored field entry - both a top-level ``fields`` entry and an entry inside a multi-data-section
row's ``data`` list - must be a complete {name, value, type} triple, where ``type`` mirrors the
FieldType of the field's definition on the CmdbType. Installations that predate that rule stored the
entries without a ``type``, so the frontend render layer has nothing to switch on. This update brings
an existing installation to the new state, per type:

1. **Strip** every field entry whose ``name`` the type schema no longer declares. Removing a field
   from a type drops its definition but leaves the stored value on every object, and nothing else
   ever cleans those up - they can never be given a ``type`` because no definition remains to take it
   from. A type whose schema reports no field names at all is skipped entirely (an empty name set is
   indistinguishable from an unreadable schema, and stripping on it would empty every object).
2. **Backfill** the ``type`` of every remaining entry from the type schema. An entry counts as
   untyped when the key is absent, ``null`` or an empty string; an entry that already carries a
   non-empty type is left untouched, so a field whose definition later changed type is NOT rewritten.

Operator notes:

* The migration is **one-way**: stripped entries are deleted, not archived. The values they held were
  already unreachable through the type schema.
* Objects are matched per type via the indexed ``type_id`` (``CmdbObject.INDEX_KEYS`` declares a
  ``type_id`` index), so each write is index-supported on its leading predicate; the array predicates
  then apply per candidate document.
* Both writes traverse the multi-data-section arrays through **guarded** positional identifiers
  (``$[s]`` / ``$[v]`` with a ``$type: "array"`` filter) rather than the all-positional ``$[]``. ``$[]``
  requires the path to exist on every traversed element, so one section without ``values`` - or one row
  without ``data`` - would abort the entire migration with "The path ... must exist in the document in
  order to apply array updates", and abort it again on every subsequent boot. The rest of the codebase
  reads these structures defensively, so the shape is not guaranteed; malformed sections and rows are
  now skipped instead of failing the run.
* The multi-data-section writes are issued only for a type that declares a multi-data-section, which
  is the minority of types.

**Re-run safety.** The updater framework applies a migration only once, but the version is persisted as
the very last statement of ``start_update`` and there are no multi-document transactions, so any
failure re-enters this migration on the next boot on top of whatever the crashed run committed. Every
write here is repeatable and converges to the same end state: the strip is a ``$pull`` of entries that
are no longer declared (already-pulled entries stay pulled), and the backfill only ever fills an
untyped entry (an already-typed one no longer matches). A second run reports zero modified documents.

Every literal this module writes or queries is a **local, frozen constant**: a migration is a
historical record of the 2026-02-25 schema, so it must keep reading and writing those names even if
the live models rename them later. That is why nothing here is imported from the model classes or
their key enums - see the constants block below.

The pure schema readers are module-level functions (directly importable and testable); the methods on
the class are exactly the ones that touch the database.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# ------------------------------------------- FROZEN SCHEMA CONSTANTS ------------------------------------------------ #
# Keys of a stored CmdbType document
TYPE_PUBLIC_ID_KEY: str = "public_id"
TYPE_FIELDS_KEY: str = "fields"
TYPE_RENDER_META_KEY: str = "render_meta"
TYPE_SECTIONS_KEY: str = "sections"

# Keys of one entry inside a type schema's 'fields' list
FIELD_NAME_KEY: str = "name"
FIELD_TYPE_KEY: str = "type"

# Keys of one entry inside a type schema's 'render_meta.sections' list, and the section type that
# makes a type carry multi-data-section rows on its objects
SECTION_TYPE_KEY: str = "type"
MDS_SECTION_TYPE: str = "multi-data-section"

# Keys of a stored CmdbObject document and of its nested multi-data-section structure
OBJECT_TYPE_ID_KEY: str = "type_id"
OBJECT_FIELDS_KEY: str = "fields"
OBJECT_MDS_KEY: str = "multi_data_sections"
MDS_VALUES_KEY: str = "values"
MDS_DATA_KEY: str = "data"

# Dotted query path and positional update paths composed from the keys above. 's' identifies a
# multi-data-section, 'v' one of its rows and 'f' one field entry
MDS_DATA_QUERY_PATH: str = f"{OBJECT_MDS_KEY}.{MDS_VALUES_KEY}.{MDS_DATA_KEY}"
FIELD_TYPE_UPDATE_PATH: str = f"{OBJECT_FIELDS_KEY}.$[f].{FIELD_TYPE_KEY}"
MDS_FIELD_TYPE_UPDATE_PATH: str = (
    f"{OBJECT_MDS_KEY}.$[s].{MDS_VALUES_KEY}.$[v].{MDS_DATA_KEY}.$[f].{FIELD_TYPE_KEY}"
)
MDS_DATA_PULL_PATH: str = f"{OBJECT_MDS_KEY}.$[s].{MDS_VALUES_KEY}.$[v].{MDS_DATA_KEY}"

# Only these three keys of a type document are read, so only these are fetched
TYPE_PROJECTION: dict[str, int] = {
    "_id": 0,
    TYPE_PUBLIC_ID_KEY: 1,
    TYPE_FIELDS_KEY: 1,
    f"{TYPE_RENDER_META_KEY}.{TYPE_SECTIONS_KEY}": 1,
}

# A stored 'type' counts as untyped when the key is absent, null, or an empty string. '$in: [None]'
# matches an absent key as well as an explicit null
UNTYPED_MATCH: dict[str, list[Any]] = {"$in": [None, ""]}

# Traversal guards: skip a section without a 'values' array and a row without a 'data' array instead
# of aborting the whole update on it
SECTION_HAS_VALUES_FILTER: dict[str, Any] = {f"s.{MDS_VALUES_KEY}": {"$type": "array"}}
ROW_HAS_DATA_FILTER: dict[str, Any] = {f"v.{MDS_DATA_KEY}": {"$type": "array"}}

# --------------------------------------------- SCHEMA READERS ------------------------------------------------------- #

def collect_schema_field_names(type_doc: dict[str, Any]) -> set[str]:
    """
    Collects every field name a type schema declares

    Names are collected regardless of whether the definition carries a usable field type, so a
    definition with a broken 'type' still protects its stored entries from being stripped

    Args:
        type_doc (dict[str, Any]): A stored CmdbType document

    Returns:
        set[str]: Every declared field name; empty when the schema declares none
    """
    names: set[str] = set()

    for field in type_doc.get(TYPE_FIELDS_KEY) or []:
        if not isinstance(field, dict):
            continue

        name = field.get(FIELD_NAME_KEY)

        if isinstance(name, str) and name:
            names.add(name)

    return names


def collect_field_names_by_type(type_doc: dict[str, Any]) -> dict[str, list[str]]:
    """
    Groups a type schema's field names by the field type their definition declares

    Definitions without a usable name or a non-empty string field type are skipped: writing their
    field type onto the objects would store exactly the missing/empty value this migration removes

    Args:
        type_doc (dict[str, Any]): A stored CmdbType document

    Returns:
        dict[str, list[str]]: Maps a field type to the field names declared with it, e.g.
            {"text": ["text-f96955e2..."], "ref": ["ref-391f8254..."]}
    """
    names_by_field_type: dict[str, list[str]] = {}

    for field in type_doc.get(TYPE_FIELDS_KEY) or []:
        if not isinstance(field, dict):
            continue

        name = field.get(FIELD_NAME_KEY)
        field_type = field.get(FIELD_TYPE_KEY)

        if not (isinstance(name, str) and name) or not (isinstance(field_type, str) and field_type):
            continue

        names_by_field_type.setdefault(field_type, []).append(name)

    return names_by_field_type


def declares_multi_data_section(type_doc: dict[str, Any]) -> bool:
    """
    Checks whether a type schema declares at least one multi-data-section

    Only such a type can have objects carrying multi_data_sections rows, so the two nested writes are
    skipped for every other type

    Args:
        type_doc (dict[str, Any]): A stored CmdbType document

    Returns:
        bool: True when the schema declares a multi-data-section
    """
    render_meta = type_doc.get(TYPE_RENDER_META_KEY)

    if not isinstance(render_meta, dict):
        return False

    for section in render_meta.get(TYPE_SECTIONS_KEY) or []:
        if isinstance(section, dict) and section.get(SECTION_TYPE_KEY) == MDS_SECTION_TYPE:
            return True

    return False


# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260225 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260225(BaseDatabaseUpdate):
    """
    Strips undeclared field entries from every object and backfills the 'type' on the rest
    """
    def creation_date(self) -> int:
        return 20260225


    def description(self) -> str:
        return "Strips undeclared object fields and adds the 'type' property to the remaining ones"


    def start_update(self) -> None:
        """
        Normalises every object's field entries, then bumps the updater version

        Raises:
            UpdaterException: If the normalisation fails; startup aborts on it deliberately
        """
        try:
            self.normalise_object_fields()

            self.increase_updater_version(self.creation_date())
        except UpdaterException:
            raise
        except Exception as err:
            raise UpdaterException(str(err)) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def load_type_plans(self) -> list[dict[str, Any]]:
        """
        Reduces every type schema to what the per-type writes need

        Only the three projected keys of a type document are fetched. A type without a usable
        public_id is skipped with a warning - it cannot be matched against any object

        Returns:
            list[dict[str, Any]]: One plan per usable type, each holding 'type_id', the declared
                'known_names', the 'names_by_field_type' grouping and the 'has_mds' flag
        """
        type_docs: list[dict[str, Any]] = self.types_manager.find(criteria={}, projection=TYPE_PROJECTION)

        plans: list[dict[str, Any]] = []

        for type_doc in type_docs:
            type_id = type_doc.get(TYPE_PUBLIC_ID_KEY)

            if not isinstance(type_id, int):
                LOGGER.warning("[Update20260225] Skipping a type without a usable public_id: %s", type_id)
                continue

            plans.append({
                'type_id': type_id,
                'known_names': collect_schema_field_names(type_doc),
                'names_by_field_type': collect_field_names_by_type(type_doc),
                'has_mds': declares_multi_data_section(type_doc),
            })

        return plans


    def strip_undeclared_fields(self, type_id: int, known_names: set[str], has_mds: bool) -> None:
        """
        Removes every field entry of a type's objects whose name the schema no longer declares

        A `$pull` of the entries that are not declared any more; already-pulled entries no longer
        match, so the write is repeatable. Nothing is stripped when the schema declares no names at
        all - see the module docstring

        Args:
            type_id (int): public_id of the type whose objects are normalised
            known_names (set[str]): Every field name the type schema declares
            has_mds (bool): Whether the type declares a multi-data-section
        """
        if not known_names:
            LOGGER.warning(
                "[Update20260225] Type %s declares no field names - skipping the strip for its objects", type_id
            )
            return

        declared: list[str] = sorted(known_names)
        undeclared_match: dict[str, Any] = {FIELD_NAME_KEY: {"$nin": declared}}

        self.objects_manager.update_many_raw(
            filter_query={
                OBJECT_TYPE_ID_KEY: type_id,
                OBJECT_FIELDS_KEY: {"$elemMatch": undeclared_match},
            },
            update={"$pull": {OBJECT_FIELDS_KEY: undeclared_match}},
        )

        if not has_mds:
            return

        self.objects_manager.update_many_raw(
            filter_query={
                OBJECT_TYPE_ID_KEY: type_id,
                MDS_DATA_QUERY_PATH: {"$elemMatch": undeclared_match},
            },
            update={"$pull": {MDS_DATA_PULL_PATH: undeclared_match}},
            array_filters=[SECTION_HAS_VALUES_FILTER, ROW_HAS_DATA_FILTER],
        )


    def backfill_field_types(self, type_id: int, names_by_field_type: dict[str, list[str]], has_mds: bool) -> None:
        """
        Writes the schema's field type onto every untyped field entry of a type's objects

        One pair of writes per field type: an entry matches only while its 'type' is absent, null or
        empty, so an already-typed entry is never rewritten and the write is repeatable

        Args:
            type_id (int): public_id of the type whose objects are normalised
            names_by_field_type (dict[str, list[str]]): Field names grouped by their declared type
            has_mds (bool): Whether the type declares a multi-data-section
        """
        for field_type, names in names_by_field_type.items():
            untyped_match: dict[str, Any] = {
                FIELD_NAME_KEY: {"$in": names},
                FIELD_TYPE_KEY: UNTYPED_MATCH,
            }
            entry_filter: dict[str, Any] = {
                f"f.{FIELD_NAME_KEY}": {"$in": names},
                f"f.{FIELD_TYPE_KEY}": UNTYPED_MATCH,
            }

            self.objects_manager.update_many_raw(
                filter_query={
                    OBJECT_TYPE_ID_KEY: type_id,
                    OBJECT_FIELDS_KEY: {"$elemMatch": untyped_match},
                },
                update={"$set": {FIELD_TYPE_UPDATE_PATH: field_type}},
                array_filters=[entry_filter],
            )

            if not has_mds:
                continue

            self.objects_manager.update_many_raw(
                filter_query={
                    OBJECT_TYPE_ID_KEY: type_id,
                    MDS_DATA_QUERY_PATH: {"$elemMatch": untyped_match},
                },
                update={"$set": {MDS_FIELD_TYPE_UPDATE_PATH: field_type}},
                array_filters=[SECTION_HAS_VALUES_FILTER, ROW_HAS_DATA_FILTER, entry_filter],
            )


    def normalise_object_fields(self) -> None:
        """
        Strips undeclared field entries and backfills the 'type' on the rest, type by type

        Raises:
            UpdaterException: If the normalisation fails
        """
        try:
            for plan in self.load_type_plans():
                self.strip_undeclared_fields(plan['type_id'], plan['known_names'], plan['has_mds'])
                self.backfill_field_types(plan['type_id'], plan['names_by_field_type'], plan['has_mds'])
        except Exception as err:
            raise UpdaterException(f"Failed to normalise the field entries of the objects: {err}") from err
