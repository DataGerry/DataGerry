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
The id lists an ISMS write names: each id stored, and named once

Two writes carry lists of other documents' ids that the schema holds to the id rule (a whole number from 1, never a
boolean) and these checks hold to what is stored, before anything is written:

- a Risk's ``threats``, ``vulnerabilities`` and ``protection_goals`` - each IsmsThreat / IsmsVulnerability /
  IsmsProtectionGoal has to exist (``guard_risk_references``)
- an ImpactCategory's ``impact_descriptions`` - each describes a stored IsmsImpact (``guard_impact_description_ids``),
  on the single create / update and on every item of the bulk reorder

Within one document an id is named once: a repeated id is refused before anything is read. Every unknown id is named
with its field in one 400, so a client fixes the whole payload at once; each referenced collection is read once, with
a projected ``$in``. A failed read is its own 400
"""
from collections import Counter
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.database.database_constants import PUBLIC_ID_FIELD
from cmdb.models.isms_model import IsmsImpact, IsmsProtectionGoal, IsmsThreat, IsmsVulnerability
from cmdb.models.isms_model.isms_impact_category_constants import ImpactCategoryKey, ImpactDescriptionKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey
from cmdb.errors.manager import BaseManagerGetError
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    ID_REFERENCE_REASON,
    ID_REFERENCE_REASON_SEPARATOR,
    IMPACT_CATEGORY_ENTITY,
    IMPACT_DESCRIPTION_ID_FIELD,
    IMPACT_LABEL,
    PROTECTION_GOAL_LABEL,
    REFERENCE_LOOKUP_FAILED_MSG,
    REPEATED_REFERENCED_IDS_MSG,
    RISK_LABEL,
    THREAT_LABEL,
    UNKNOWN_REFERENCED_IDS_MSG,
    VULNERABILITY_LABEL,
    IsmsEntityLabel,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# What each id list of a Risk names: the field, the collection its ids live in, and the label of a failed read
RISK_REFERENCE_FIELDS: tuple[tuple[RiskKey, str, IsmsEntityLabel], ...] = (
    (RiskKey.THREATS, IsmsThreat.COLLECTION, THREAT_LABEL),
    (RiskKey.VULNERABILITIES, IsmsVulnerability.COLLECTION, VULNERABILITY_LABEL),
    (RiskKey.PROTECTION_GOALS, IsmsProtectionGoal.COLLECTION, PROTECTION_GOAL_LABEL),
)
# The projection of an existence read: the id alone
PUBLIC_ID_PROJECTION: dict[str, int] = {PUBLIC_ID_FIELD: 1}


def repeated_ids(ids: list[int]) -> list[int]:
    """
    The ids a list names more than once

    Args:
        ids (list[int]): The ids, as the schema let them through

    Returns:
        list[int]: Each repeated id once, sorted; empty when every id is named once
    """
    return sorted(public_id for public_id, count in Counter(ids).items() if count > 1)


def id_reasons(fields: list[tuple[str, list[int]]]) -> str:
    """
    The joined refusal reasons of the fields that name any id

    Args:
        fields (list[tuple[str, list[int]]]): (field, ids) pairs, in the order the reasons are named

    Returns:
        str: One ``field: [ids]`` reason per field with ids, joined; empty when none has any
    """
    return ID_REFERENCE_REASON_SEPARATOR.join(
        ID_REFERENCE_REASON.format(field=field, ids=ids) for field, ids in fields if ids
    )


def read_missing_ids(manager: Any, collection: str, ids: list[int], label: IsmsEntityLabel) -> set[int]:
    """
    The ids no document of a collection carries, one projected read; a failed read answers its own 400

    Args:
        manager (Any): A manager of the database, anything with ``get_many_from_other_collection``
        collection (str): The collection the ids name documents of
        ids (list[int]): The ids; nothing is read when empty
        label (IsmsEntityLabel): What the ids name, for the failed read's message

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 when the documents could not be read

    Returns:
        set[int]: The ids not stored
    """
    if not ids:
        return set()

    try:
        stored: list[dict[str, Any]] = manager.get_many_from_other_collection(
            collection,
            projection=PUBLIC_ID_PROJECTION,
            criteria={PUBLIC_ID_FIELD: {'$in': sorted(set(ids))}},
        )
    except BaseManagerGetError as err:
        LOGGER.error("[read_missing_ids] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, REFERENCE_LOOKUP_FAILED_MSG.format(label=label.singular))

    return set(ids) - {document.get(PUBLIC_ID_FIELD) for document in stored}


def guard_risk_references(risk_manager: Any, data: dict[str, Any]) -> None:
    """
    Refuses a Risk write naming a Threat, Vulnerability or ProtectionGoal twice or one that is not stored

    Args:
        risk_manager (Any): The RiskManager, anything with ``get_many_from_other_collection``
        data (dict[str, Any]): The validated Risk payload

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming every repeated id, else every unknown id, with its
            field; or when a referenced collection could not be read
    """
    named: list[tuple[str, list[int], str, IsmsEntityLabel]] = [
        (field.value, list(data.get(field.value) or []), collection, label)
        for field, collection, label in RISK_REFERENCE_FIELDS
    ]

    repeated: str = id_reasons([(field, repeated_ids(ids)) for field, ids, _collection, _label in named])

    if repeated:
        abort(400, REPEATED_REFERENCED_IDS_MSG.format(entity=RISK_LABEL.singular, reasons=repeated))

    unknown: str = id_reasons([
        (field, sorted(read_missing_ids(risk_manager, collection, ids, label)))
        for field, ids, collection, label in named
    ])

    if unknown:
        abort(400, UNKNOWN_REFERENCED_IDS_MSG.format(entity=RISK_LABEL.singular, reasons=unknown))


def described_impact_ids(document: dict[str, Any]) -> list[int]:
    """
    The Impact ids an ImpactCategory's descriptions name, in their order

    Args:
        document (dict[str, Any]): The validated ImpactCategory payload

    Returns:
        list[int]: One id per description
    """
    return [
        description.get(ImpactDescriptionKey.IMPACT_ID.value)
        for description in document.get(ImpactCategoryKey.IMPACT_DESCRIPTIONS.value) or []
    ]


def guard_impact_description_ids(manager: Any, documents: list[tuple[str, dict[str, Any]]]) -> None:
    """
    Refuses ImpactCategory writes describing one Impact twice or an Impact that is not stored

    The single create / update hands one document, the bulk reorder every item; the Impacts of all of them are read
    once

    Args:
        manager (Any): The ImpactCategoryManager, anything with ``get_many_from_other_collection``
        documents (list[tuple[str, dict[str, Any]]]): (entity name for the message, validated payload) pairs

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming, per document, every repeated id, else every unknown
            id; or when the Impacts could not be read
    """
    described: list[tuple[str, list[int]]] = [
        (entity, described_impact_ids(document)) for entity, document in documents
    ]

    for entity, ids in described:
        repeated: str = id_reasons([(IMPACT_DESCRIPTION_ID_FIELD, repeated_ids(ids))])

        if repeated:
            abort(400, REPEATED_REFERENCED_IDS_MSG.format(entity=entity, reasons=repeated))

    missing: set[int] = read_missing_ids(
        manager, IsmsImpact.COLLECTION, [public_id for _entity, ids in described for public_id in ids], IMPACT_LABEL,
    )

    for entity, ids in described:
        unknown: str = id_reasons([(IMPACT_DESCRIPTION_ID_FIELD, sorted(set(ids) & missing))])

        if unknown:
            abort(400, UNKNOWN_REFERENCED_IDS_MSG.format(entity=entity, reasons=unknown))


def bulk_category_entity(public_id: int) -> str:
    """
    How one item of the ImpactCategory bulk reorder is named in its refusals

    Args:
        public_id (int): The item's public_id

    Returns:
        str: E.g. ``"ImpactCategory 7"``
    """
    return IMPACT_CATEGORY_ENTITY.format(public_id=public_id)
