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
Implementation of IsmsRisk in DataGerry - ISMS

An IsmsRisk is one risk of the ISMS (collection ``isms.risk``): the thing an IsmsRiskAssessment
evaluates for a CmdbObject or CmdbObjectGroup. Four properties of this document are worth knowing
before changing it:

**What a risk describes depends on its ``risk_type``**, and that rule lives outside this model:

  - ``THREAT_X_VULNERABILITY`` - threats AND vulnerabilities, no consequences
  - ``THREAT`` - threats only, no vulnerabilities and no consequences
  - ``EVENT`` - consequences only, neither threats nor vulnerabilities

The frontend blanks the fields its type does not use (``risks-add.component.ts``) and the CSV importer
rejects a row that contradicts the rule (``risk_row_is_valid``). Neither this model nor the Cerberus
schema expresses it - a per-field schema cannot - so a direct API write can still store a combination
no client would produce.

**Its four reference fields are public_ids of other collections**: ``protection_goals`` →
``isms.protectionGoal``, ``threats`` → ``isms.threat``, ``vulnerabilities`` → ``isms.vulnerability``,
and ``category_id`` → a ``CmdbExtendableOption`` of option type ``RISK_CLASS``. The first three are
indexed because the delete guard of each of those entities asks this collection whether a risk still
references it (``delete_isms_item_if_unused_by_risk``); without the index that question is a
collection scan.

**The three reference lists are always lists, never null.** The constructor coerces each one, so a
document that predates a field, or an API write that omits it, reads back as ``[]`` - which is what
the report ``$lookup`` stages and the frontend's ``|| []`` guards already assume.

**Its key set is closed.** ``RiskKey`` names every persisted key and drives the shared
``CmdbDAO.from_data`` / ``to_json``, so the round trip is over exactly that set. ``risk_type`` holds
the raw ``RiskType`` value rather than a member, pinned by the schema's ``allowed`` list - validation,
not the model, is what refuses an unknown type
"""
from typing import Any

from cmdb.class_schema.isms_model.isms_risk_schema import get_isms_risk_schema
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_risk_constants import RiskKey

from cmdb.errors.models.isms_risk import (
    IsmsRiskInitError,
    IsmsRiskInitFromDataError,
    IsmsRiskToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                                   IsmsRisk - CLASS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsRisk(CmdbDAO):
    """
    Implementation of IsmsRisk which represents a risk in ISMS

    Extends: CmdbDAO
    """
    COLLECTION = "isms.risk"

    INDEX_KEYS: list[dict[str, Any]] = [
        # Serves the client driven '?filter=' / '?sort=' on the risk list; no backend query reads it
        {
            'keys': [(RiskKey.RISK_TYPE.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskKey.RISK_TYPE.value,
            'unique': False,
        },
        # The three reference lists are multikey indexes, and each one answers the delete guard of the
        # entity it points at: delete_isms_item_if_unused_by_risk looks up this collection by the
        # field before letting a ProtectionGoal / Threat / Vulnerability go. protection_goals was
        # missing until 2026-09-07, so that one guard scanned every risk on every delete
        {
            'keys': [(RiskKey.PROTECTION_GOALS.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskKey.PROTECTION_GOALS.value,
            'unique': False,
        },
        {
            'keys': [(RiskKey.THREATS.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskKey.THREATS.value,
            'unique': False,
        },
        {
            'keys': [(RiskKey.VULNERABILITIES.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskKey.VULNERABILITIES.value,
            'unique': False,
        },
        # Not read by any backend query either - the risk-assessment report only projects it
        {
            'keys': [(RiskKey.IDENTIFIER.value, CmdbDAO.DAO_ASCENDING)],
            'name': RiskKey.IDENTIFIER.value,
            'unique': False,
        },
    ]

    SCHEMA: dict = get_isms_risk_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither
    KEYS = RiskKey
    INIT_FROM_DATA_ERROR = IsmsRiskInitFromDataError
    TO_JSON_ERROR = IsmsRiskToJsonError

    # R0913 stays: ten flat, independent fields, so a parameter object would only move the same names
    # one level down. R0917 does not apply - the signature is keyword-only, which it must be, because
    # CmdbDAO.__new__ looks for public_id in **kwargs and runs before __init__
    # pylint: disable=R0913
    def __init__(
            self,
            *,
            public_id: int,
            name: str,
            risk_type: str,
            protection_goals: list[int] | None = None,
            threats: list[int] | None = None,
            vulnerabilities: list[int] | None = None,
            category_id: int | None = None,
            identifier: str | None = None,
            consequences: str | None = None,
            description: str | None = None,
        ) -> None:
        """
        Initialises an IsmsRisk

        The three reference lists are coerced to ``[]``: a missing key and a stored null both mean
        "nothing referenced", and every reader downstream assumes a list

        Args:
            public_id (int): public_id of the IsmsRisk
            name (str): The name of the IsmsRisk
            risk_type (str): A RiskType value of the IsmsRisk - it decides which of the fields below
                             the risk actually uses (see the module docstring)
            protection_goals (list[int], optional): public_ids of the affected IsmsProtectionGoals
            threats (list[int], optional): public_ids of the IsmsThreats linked with this IsmsRisk
            vulnerabilities (list[int], optional): public_ids of the linked IsmsVulnerabilities
            category_id (int, optional): public_id of the CmdbExtendableOption holding the risk's
                                         category
            identifier (str, optional): Identifier of the IsmsRisk
            consequences (str, optional): Consequences of the IsmsRisk - used by an EVENT risk
            description (str, optional): Description of the IsmsRisk

        Raises:
            IsmsRiskInitError: If the IsmsRisk could not be initialised
        """
        try:
            self.name = name
            self.risk_type = risk_type
            self.protection_goals = protection_goals or []
            self.threats = threats or []
            self.vulnerabilities = vulnerabilities or []
            self.category_id = category_id
            self.identifier = identifier
            self.consequences = consequences
            self.description = description

            super().__init__(public_id = public_id)
        except Exception as err:
            raise IsmsRiskInitError(err) from err
