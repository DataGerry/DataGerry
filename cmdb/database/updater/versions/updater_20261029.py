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
Database update 20261029: make a CmdbSectionTemplate's name unique

A section template's ``name`` is the key consuming types claim it by (``global_template_ids``), and every propagation,
usage count and delete cleanup finds the types by it - so two templates of one name share every consumer, and
deleting either one strips the section from all of them. Since this version a unique index on the name is the
guarantee. MongoDB refuses to build a unique index over a collection that holds a duplicate, and the startup index
reconciliation only logs that refusal, so this update first renames every duplicate and then builds the index itself.

**Which template keeps the name.** A predefined template, when one of the name is stored - the seeding and the
predefined guards find it by that name. Otherwise the lowest public_id: the oldest, the one the consuming types were
most likely built from. Every other template of the name becomes ``<name>-<public_id>``; when that is taken too,
``-<public_id>`` is appended again until it is free. Names are compared exactly, as the index compares them.

**The consuming types follow the kept template**, because they claim the name. A type whose section was last written
by the propagation of a renamed template may still hold that template's fields; this update cannot tell which
template a section came from, so it writes nothing to types and logs every rename with the ids of the types claiming
the name, for an administrator to check.

Re-run safe: the duplicates are recomputed from the stored names, each rename is conditioned on the name it read,
and an index of that name that is already unique is left alone - one that is not is dropped and rebuilt
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import ASCENDING, IndexModel

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
SECTION_TEMPLATE_COLLECTION: str = 'framework.sectionTemplates'
TYPE_COLLECTION: str = 'framework.types'
NAME_FIELD: str = 'name'
PREDEFINED_FIELD: str = 'predefined'
PUBLIC_ID_FIELD: str = 'public_id'
GLOBAL_TEMPLATE_IDS_FIELD: str = 'global_template_ids'
MONGO_ID_FIELD: str = '_id'
NAME_INDEX: str = 'name'
INDEX_UNIQUE_KEY: str = 'unique'
RENAME_SEPARATOR: str = '-'


def _keeps_first(template: dict[str, Any]) -> tuple[bool, int]:
    """
    The order in which templates of one name claim it: a predefined one first, then by public_id

    Args:
        template (dict[str, Any]): A stored template with a readable name and public_id

    Returns:
        tuple[bool, int]: The sort key - False sorts first, so a predefined template is (False, id)
    """
    return template.get(PREDEFINED_FIELD) is not True, template[PUBLIC_ID_FIELD]


def duplicate_renames(templates: list[dict[str, Any]]) -> list[tuple[int, str, str]]:
    """
    The renames that leave every template name held once - all but the keeper of each name

    The keeper is a predefined template of the name, else the lowest public_id

    Args:
        templates (list[dict[str, Any]]): The stored templates, each with its public_id, name and predefined flag

    Returns:
        list[tuple[int, str, str]]: (public_id, stored name, new name) per template to rename, in keeping order
    """
    ordered: list[dict[str, Any]] = sorted(
        (template for template in templates
         if isinstance(template.get(NAME_FIELD), str) and isinstance(template.get(PUBLIC_ID_FIELD), int)),
        key=_keeps_first,
    )
    taken: set[str] = {template[NAME_FIELD] for template in ordered}
    kept: set[str] = set()
    renames: list[tuple[int, str, str]] = []

    for template in ordered:
        name: str = template[NAME_FIELD]

        if name not in kept:
            kept.add(name)
            continue

        public_id: int = template[PUBLIC_ID_FIELD]
        new_name: str = f'{name}{RENAME_SEPARATOR}{public_id}'

        while new_name in taken:
            new_name = f'{new_name}{RENAME_SEPARATOR}{public_id}'

        taken.add(new_name)
        renames.append((public_id, name, new_name))

    return renames

# -------------------------------------------------------------------------------------------------------------------- #
# ---------------------------------------------- Update20261029 - CLASS ---------------------------------------------- #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20261029(BaseDatabaseUpdate):
    """
    Renames duplicate CmdbSectionTemplate names and makes the name unique

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261029


    def description(self) -> str:
        return "Renames duplicate section template names and makes a section template's name unique"


    def start_update(self) -> None:
        """
        Renames first, then builds the index, then bumps the version

        The order is not optional: the unique index cannot be built while a duplicate is stored

        Raises:
            UpdaterException: If a read, a rename or the index build failed
        """
        try:
            self.rename_duplicates()

            if self.build_unique_name_index():
                LOGGER.info("[Update20261029] Built the unique '%s' index on %s",
                            NAME_INDEX, SECTION_TEMPLATE_COLLECTION)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def rename_duplicates(self) -> list[tuple[int, str, str]]:
        """
        Renames every template whose name its keeper holds, and logs the types claiming that name

        Each rename is conditioned on the name that was read, so a name changed since is left alone

        Returns:
            list[tuple[int, str, str]]: (public_id, stored name, new name) of every rename attempted
        """
        templates: list[dict[str, Any]] = list(self.dbm.find(
            SECTION_TEMPLATE_COLLECTION,
            self.db_name,
            filter={},
            projection={PUBLIC_ID_FIELD: 1, NAME_FIELD: 1, PREDEFINED_FIELD: 1, MONGO_ID_FIELD: 0},
        ))
        renames: list[tuple[int, str, str]] = duplicate_renames(templates)

        for public_id, name, new_name in renames:
            self.dbm.update(
                SECTION_TEMPLATE_COLLECTION,
                self.db_name,
                {PUBLIC_ID_FIELD: public_id, NAME_FIELD: name},
                {NAME_FIELD: new_name},
            )
            LOGGER.warning("[Update20261029] Section template %s %s: the name %r is held by another template - "
                           "renamed to %r. The types claiming %r follow the template that kept it; check their "
                           "section: %s", PUBLIC_ID_FIELD, public_id, name, new_name, name,
                           self.claiming_type_ids(name))

        return renames


    def claiming_type_ids(self, name: str) -> list[int]:
        """
        The public_ids of the types that claim a template name in their ``global_template_ids``

        Args:
            name (str): The template name

        Returns:
            list[int]: The ids, ascending
        """
        claiming: list[dict[str, Any]] = list(self.dbm.find(
            TYPE_COLLECTION,
            self.db_name,
            filter={GLOBAL_TEMPLATE_IDS_FIELD: name},
            projection={PUBLIC_ID_FIELD: 1, MONGO_ID_FIELD: 0},
        ))

        return sorted(a_type[PUBLIC_ID_FIELD] for a_type in claiming if PUBLIC_ID_FIELD in a_type)


    def build_unique_name_index(self) -> bool:
        """
        Builds the unique index on the template name, unless it is already in place

        An index of that name that is not unique (an older declaration) is dropped first: MongoDB refuses to
        recreate an index under the same name with other options

        Returns:
            bool: True when the index was built, False when it was already unique
        """
        index_info: dict[str, Any] = dict(self.dbm.get_index_info(SECTION_TEMPLATE_COLLECTION, self.db_name))
        existing: dict[str, Any] | None = index_info.get(NAME_INDEX)

        if existing is not None and existing.get(INDEX_UNIQUE_KEY, False):
            return False

        if existing is not None:
            self.dbm.drop_index(SECTION_TEMPLATE_COLLECTION, self.db_name, NAME_INDEX)

        self.dbm.create_indexes(SECTION_TEMPLATE_COLLECTION, self.db_name, [
            IndexModel([(NAME_FIELD, ASCENDING)], name=NAME_INDEX, unique=True),
        ])

        return True
