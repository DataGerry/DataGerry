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
Implementation of IsmsRiskClass in DataGerry - ISMS

An IsmsRiskClass is one severity band of the ISMS configuration (collection ``isms.riskClass``): a
name, a colour and a sort order, applied to calculated risk values.

**The matrix references it by public_id alone.** Every cell of the singleton IsmsRiskMatrix carries a
``risk_class_id``, and `0` means "not yet assigned" - so deleting a class does not cascade, it resets
the cells that named it (`remove_deleted_risk_class_from_matrix`). Nothing outside this document reads
its other four keys; the ISMS report aggregations name ``color`` as a dotted path inside a pipeline
literal, which is a string by design.

``RiskClassKey`` names every persisted key and drives the shared ``CmdbDAO`` ``from_data`` / ``to_json``,
so this model defines neither
"""
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_risk_class_constants import RiskClassKey, RISK_CLASS_REQUIRED_DOCUMENT_KEYS

from cmdb.class_schema.isms_model.isms_risk_class_schema import get_isms_risk_class_schema

from cmdb.errors.models.isms_risk_class import (
    IsmsRiskClassInitError,
    IsmsRiskClassInitFromDataError,
    IsmsRiskClassToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                                 IsmsRiskClass - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsRiskClass(CmdbDAO):
    """
    Implementation of IsmsRiskClass which represents a risk class of the ISMS general configuration

    Extends: CmdbDAO
    """
    COLLECTION = "isms.riskClass"

    SCHEMA: dict[str, Any] = get_isms_risk_class_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither
    KEYS = RiskClassKey
    REQUIRED_INIT_KEYS: list[str] = RISK_CLASS_REQUIRED_DOCUMENT_KEYS
    INIT_FROM_DATA_ERROR = IsmsRiskClassInitFromDataError
    TO_JSON_ERROR = IsmsRiskClassToJsonError

    def __init__(
            self,
            *,
            public_id: int,
            name: str,
            color: str,
            sort: int | None = None,
            description: str | None = None,
        ) -> None:
        """
        Initialises an IsmsRiskClass

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        Args:
            public_id (int): public_id of the IsmsRiskClass
            name (str): The name of the IsmsRiskClass
            color (str): The display colour of the IsmsRiskClass, as a hex / css value
            sort (int, optional): The sort order of the IsmsRiskClass
            description (str, optional): The description of the IsmsRiskClass

        Raises:
            IsmsRiskClassInitError: When the IsmsRiskClass could not be initialised
        """
        try:
            self.name = name
            self.color = color
            self.sort = sort
            self.description = description

            super().__init__(public_id=public_id)
        except Exception as err:
            raise IsmsRiskClassInitError(err) from err
