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
Plans the sync of an imported OSCAL catalog with its IsmsControlMeasures

A catalog import is a sync keyed by (catalog_id, identifier):

  - a requirement not imported yet is **created** as a REQUIREMENT control
  - an imported one whose catalog content (title, chapter, description) changed is **updated** - only those three
    fields; what the ISMS team maintains (implementation state, applicability, reason, source) is kept
  - an imported one that is unchanged is left alone
  - an imported control whose identifier is no longer in the catalog is reported as **obsolete** and kept: it may
    carry assessments or assignments, and deleting it is the catalog delete action's decision, not an update's
"""
from dataclasses import dataclass, field
from typing import Any

from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey
# -------------------------------------------------------------------------------------------------------------------- #

# The fields an update takes over from the catalog
CATALOG_OWNED_KEYS: tuple[str, ...] = (
    ControlMeasureKey.TITLE.value,
    ControlMeasureKey.CHAPTER.value,
    ControlMeasureKey.DESCRIPTION.value,
)


@dataclass
class CatalogSyncPlan:
    """What a catalog sync has to write"""
    to_insert: list[dict[str, Any]] = field(default_factory=list)
    # (public_id, {key: new value}) for every control whose catalog-owned content changed
    to_update: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    unchanged: int = 0
    obsolete: list[str] = field(default_factory=list)


def catalog_values(control: dict[str, Any]) -> dict[str, Any]:
    """The catalog-owned values of one control of the import payload, normalised like the stored ones"""
    return {
        ControlMeasureKey.TITLE.value: control['title'].strip(),
        ControlMeasureKey.CHAPTER.value: (control.get('chapter') or '').strip() or None,
        ControlMeasureKey.DESCRIPTION.value: (control.get('description') or '').strip() or None,
    }


def plan_catalog_sync(
        existing: list[dict[str, Any]],
        controls: list[dict[str, Any]],
        new_document: Any,
    ) -> CatalogSyncPlan:
    """
    Compares the stored controls of a catalog with the catalog's current requirements

    Args:
        existing (list[dict[str, Any]]): The stored controls of the catalog (public_id, identifier and the
            catalog-owned keys)
        controls (list[dict[str, Any]]): The flattened requirements of the catalog (import payload)
        new_document (Callable[[str, dict[str, Any]], dict[str, Any]]): Builds the document of a new control from
            its identifier and catalog values

    Returns:
        CatalogSyncPlan: inserts, updates, the number of unchanged controls and the obsolete identifiers
    """
    plan = CatalogSyncPlan()
    stored = {doc.get(ControlMeasureKey.IDENTIFIER.value): doc for doc in existing}
    seen: set[str] = set()

    for control in controls:
        identifier = control['identifier'].strip()

        if not identifier or identifier in seen:
            continue

        seen.add(identifier)
        values = catalog_values(control)
        doc = stored.get(identifier)

        if doc is None:
            plan.to_insert.append(new_document(identifier, values))
            continue

        changes = {key: value for key, value in values.items() if (doc.get(key) or None) != value}

        if changes:
            plan.to_update.append((doc['public_id'], changes))
        else:
            plan.unchanged += 1

    plan.obsolete = sorted(identifier for identifier in stored if identifier not in seen)

    return plan
