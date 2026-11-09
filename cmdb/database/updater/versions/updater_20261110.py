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
Database update 20261110: a Risk's and an ImpactCategory's id lists name stored documents, each once

The Risk writes now refuse a ``threats`` / ``vulnerabilities`` / ``protection_goals`` item that is no whole number
from 1, a boolean, an id nothing carries or an id named twice; the ImpactCategory writes the same for the Impact a
description names. A document stored before could hold any of them, and the frontend sends a stored Risk or category
back as it reads it - so editing it would be refused. This update brings every stored one in line, changing nothing a
reader shows (every reader already resolves such an id to nothing):

- each of a Risk's three lists keeps the items that are stored ids, the first of each repeat
- an ImpactCategory keeps the descriptions whose ``impact_id`` is a stored Impact, the first of each repeat

A list or a description list that is no list is left alone. Re-run safe: a second run finds every item valid and
named once, and writes nothing
"""
from logging import Logger, getLogger
from typing import Any, Callable, NamedTuple

from pymongo import UpdateOne

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
RISKS_COLLECTION: str = 'isms.risk'
IMPACT_CATEGORIES_COLLECTION: str = 'isms.impactCategory'
THREATS_COLLECTION: str = 'isms.threat'
VULNERABILITIES_COLLECTION: str = 'isms.vulnerability'
PROTECTION_GOALS_COLLECTION: str = 'isms.protectionGoal'
IMPACTS_COLLECTION: str = 'isms.impact'
MONGO_ID_FIELD: str = '_id'
PUBLIC_ID_FIELD: str = 'public_id'
THREATS_FIELD: str = 'threats'
VULNERABILITIES_FIELD: str = 'vulnerabilities'
PROTECTION_GOALS_FIELD: str = 'protection_goals'
IMPACT_DESCRIPTIONS_FIELD: str = 'impact_descriptions'
IMPACT_ID_FIELD: str = 'impact_id'
MIN_PUBLIC_ID: int = 1
ID_PROJECTION: dict[str, int] = {MONGO_ID_FIELD: 0, PUBLIC_ID_FIELD: 1}
RISK_PROJECTION: dict[str, int] = {
    MONGO_ID_FIELD: 1, PUBLIC_ID_FIELD: 1, THREATS_FIELD: 1, VULNERABILITIES_FIELD: 1, PROTECTION_GOALS_FIELD: 1,
}
CATEGORY_PROJECTION: dict[str, int] = {MONGO_ID_FIELD: 1, PUBLIC_ID_FIELD: 1, IMPACT_DESCRIPTIONS_FIELD: 1}

# -------------------------------------------------------------------------------------------------------------------- #

class StoredIds(NamedTuple):
    """The ids each referenced collection holds"""
    threats: set[int]
    vulnerabilities: set[int]
    protection_goals: set[int]
    impacts: set[int]


def is_public_id(value: Any) -> bool:
    """
    Whether a stored value is a public_id: an int from 1; a bool is none

    Args:
        value (Any): The stored value

    Returns:
        bool: True for an id
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= MIN_PUBLIC_ID


def kept_ids(values: list[Any], stored: set[int]) -> list[int]:
    """
    The items of an id list that name a stored document, the first of each repeat, in their order

    Args:
        values (list[Any]): The stored list
        stored (set[int]): The ids the collection holds

    Returns:
        list[int]: The kept ids
    """
    kept: list[int] = []

    for value in values:
        if is_public_id(value) and value in stored and value not in kept:
            kept.append(value)

    return kept


def risk_changes(risk: dict[str, Any], stored: StoredIds) -> dict[str, Any]:
    """
    The fields of one stored Risk to rewrite

    Args:
        risk (dict[str, Any]): The stored Risk (its three id lists)
        stored (StoredIds): What is stored

    Returns:
        dict[str, Any]: The ``$set`` document; empty when every list is in line
    """
    changes: dict[str, Any] = {}

    for field, ids in ((THREATS_FIELD, stored.threats), (VULNERABILITIES_FIELD, stored.vulnerabilities),
                       (PROTECTION_GOALS_FIELD, stored.protection_goals)):
        values: Any = risk.get(field)

        if isinstance(values, list) and (kept := kept_ids(values, ids)) != values:
            changes[field] = kept

    return changes


def category_changes(category: dict[str, Any], stored: StoredIds) -> dict[str, Any]:
    """
    The fields of one stored ImpactCategory to rewrite

    Args:
        category (dict[str, Any]): The stored ImpactCategory (its descriptions)
        stored (StoredIds): What is stored

    Returns:
        dict[str, Any]: The ``$set`` document; empty when every description names a stored Impact once
    """
    descriptions: Any = category.get(IMPACT_DESCRIPTIONS_FIELD)

    if not isinstance(descriptions, list):
        return {}

    kept: list[dict[str, Any]] = []
    described: set[int] = set()

    for description in descriptions:
        impact_id: Any = description.get(IMPACT_ID_FIELD) if isinstance(description, dict) else None

        if is_public_id(impact_id) and impact_id in stored.impacts and impact_id not in described:
            described.add(impact_id)
            kept.append(description)

    return {} if kept == descriptions else {IMPACT_DESCRIPTIONS_FIELD: kept}

# ---------------------------------------------- Update20261110 - CLASS ---------------------------------------------- #

class Update20261110(BaseDatabaseUpdate):
    """
    Drops a Risk's and an ImpactCategory's list items that name nothing stored, or name it twice

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261110


    def description(self) -> str:
        return "Drops Risk and ImpactCategory id list items that name nothing stored or repeat"


    def start_update(self) -> None:
        """
        Reads what is stored once, rewrites every Risk and ImpactCategory out of line, then bumps the version

        Raises:
            UpdaterException: If a read or a write fails
        """
        try:
            stored: StoredIds = StoredIds(
                threats=self.read_ids(THREATS_COLLECTION),
                vulnerabilities=self.read_ids(VULNERABILITIES_COLLECTION),
                protection_goals=self.read_ids(PROTECTION_GOALS_COLLECTION),
                impacts=self.read_ids(IMPACTS_COLLECTION),
            )

            risks: int = self.rewrite(RISKS_COLLECTION, RISK_PROJECTION, risk_changes, stored)
            categories: int = self.rewrite(IMPACT_CATEGORIES_COLLECTION, CATEGORY_PROJECTION, category_changes, stored)

            LOGGER.info("[updater_20261110] Rewrote %s Risk(s) and %s ImpactCategory(ies)", risks, categories)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def read_ids(self, collection: str) -> set[int]:
        """
        The public_ids a collection holds

        Args:
            collection (str): The collection

        Returns:
            set[int]: Every stored public_id
        """
        documents: list[dict[str, Any]] = list(self.dbm.find(
            collection=collection, db_name=self.db_name, filter={}, projection=ID_PROJECTION,
        ))

        return {document[PUBLIC_ID_FIELD] for document in documents if is_public_id(document.get(PUBLIC_ID_FIELD))}


    def rewrite(self,
                collection: str,
                projection: dict[str, int],
                changes_of: Callable[[dict[str, Any], StoredIds], dict[str, Any]],
                stored: StoredIds) -> int:
        """
        Rewrites the documents of one collection whose changes are not empty, in one bulk write

        Args:
            collection (str): The collection
            projection (dict[str, int]): What to read of each document
            changes_of (Callable[[dict[str, Any], StoredIds], dict[str, Any]]): The function answering a document's
                ``$set`` document
            stored (StoredIds): What is stored

        Returns:
            int: How many documents were rewritten
        """
        operations: list[UpdateOne] = []

        for document in self.dbm.find(collection=collection, db_name=self.db_name, filter={}, projection=projection):
            changes: dict[str, Any] = changes_of(document, stored)

            if changes:
                operations.append(UpdateOne({MONGO_ID_FIELD: document[MONGO_ID_FIELD]}, {'$set': changes}))
                LOGGER.warning("[updater_20261110] %s ID:%s - rewrote %s", collection,
                               document.get(PUBLIC_ID_FIELD), sorted(changes))

        if operations:
            self.dbm.bulk_write(collection, self.db_name, operations)

        return len(operations)
