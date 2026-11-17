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
from typing import Any, Callable

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.control_measure_type_enum import ControlMeasureType
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
    """
    The catalog-owned values of one control of the import payload, normalised like the stored ones

    Args:
        control (dict[str, Any]): One validated control of the import payload

    Returns:
        dict[str, Any]: The title stripped; chapter and description stripped, None when blank
    """
    return {
        ControlMeasureKey.TITLE.value: control[ControlMeasureKey.TITLE.value].strip(),
        ControlMeasureKey.CHAPTER.value: (control.get(ControlMeasureKey.CHAPTER.value) or '').strip() or None,
        ControlMeasureKey.DESCRIPTION.value: (control.get(ControlMeasureKey.DESCRIPTION.value) or '').strip() or None,
    }


def build_catalog_control(identifier: str, values: dict[str, Any], catalog_id: str, source_id: int,
                          state_id: int) -> dict[str, Any]:
    """
    The document of a requirement imported for the first time: a REQUIREMENT control of the catalog

    Args:
        identifier (str): The requirement's identifier in the catalog
        values (dict[str, Any]): Its catalog-owned values (``catalog_values``)
        catalog_id (str): id of the catalog
        source_id (int): public_id of the CONTROL_MEASURE option named after the catalog
        state_id (int): public_id of the IMPLEMENTATION_STATE option 'None'

    Returns:
        dict[str, Any]: The document, not applicable and without a reason until the ISMS team answers
    """
    return {
        **values,
        ControlMeasureKey.CONTROL_MEASURE_TYPE.value: ControlMeasureType.REQUIREMENT.value,
        ControlMeasureKey.SOURCE.value: source_id,
        ControlMeasureKey.IMPLEMENTATION_STATE.value: state_id,
        ControlMeasureKey.IDENTIFIER.value: identifier,
        ControlMeasureKey.IS_APPLICABLE.value: False,
        ControlMeasureKey.REASON.value: None,
        ControlMeasureKey.CATALOG_ID.value: catalog_id,
    }


def plan_catalog_sync(
        existing: list[dict[str, Any]],
        controls: list[dict[str, Any]],
        new_document: Callable[[str, dict[str, Any]], dict[str, Any]],
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
    stored: dict[str, dict[str, Any]] = {doc.get(ControlMeasureKey.IDENTIFIER.value): doc for doc in existing}
    seen: set[str] = set()

    for control in controls:
        identifier: str = control[ControlMeasureKey.IDENTIFIER.value].strip()

        if not identifier or identifier in seen:
            continue

        seen.add(identifier)
        values: dict[str, Any] = catalog_values(control)
        doc: dict[str, Any] | None = stored.get(identifier)

        if doc is None:
            plan.to_insert.append(new_document(identifier, values))
            continue

        changes: dict[str, Any] = {key: value for key, value in values.items() if (doc.get(key) or None) != value}

        if changes:
            plan.to_update.append((doc[CmdbDAO.PUBLIC_ID_KEY], changes))
        else:
            plan.unchanged += 1

    plan.obsolete = sorted(identifier for identifier in stored if identifier not in seen)

    return plan
