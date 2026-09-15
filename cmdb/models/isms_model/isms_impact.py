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
Implementation of IsmsImpact in DataGerry - ISMS

An IsmsImpact is one level of the ISMS impact scale (collection ``isms.impact``) - the "how bad would
it be" axis of the risk matrix. Four properties of this document are worth knowing before changing it:

**``calculation_basis`` is a number, and it is the reason this entity exists.** It is the weight the
risk matrix multiplies and the value every risk assessment's ``maximum_impact_value`` is recomputed
from, which ``ImpactManager.update_with_follow_up`` does across the whole assessment collection when
this field changes. It is stored as a float (the schema's ``'type': 'float', 'min': 0.0``); the model
annotated it ``str`` until 2026-09-07, which was the only claim of that anywhere.

**The collection is a small fixed scale**, three to six rows in practice - the whole set is preloaded
in one query by ``load_impact_calculation_basis``. That is why it declares no ``INDEX_KEYS`` even
though the frontend's table sorts on ``calculation_basis`` server-side: sorting a handful of documents
needs no index, and the other ISMS scale entities declare none either.

**``IsmsLikelihood`` is its structural twin.** Both carry exactly ``public_id`` / ``name`` /
``calculation_basis`` / ``description``, so one serialises cleanly as the other - a mix-up produces a
valid-looking payload rather than an error. The shared ``CmdbDAO.to_json`` type-checks its instance for
that reason, a guard this model had of its own before the check was lifted into the base class.

**Its key set is closed.** ``ImpactKey`` names every persisted key and drives the shared
``CmdbDAO.from_data`` / ``to_json``; ``IMPACT_REQUIRED_DOCUMENT_KEYS`` keeps a document that lacks a
name or a calculation basis from becoming an instance holding None
"""
from typing import Any

from cmdb.class_schema.isms_model.isms_impact_schema import get_isms_impact_schema
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_impact_constants import IMPACT_REQUIRED_DOCUMENT_KEYS, ImpactKey

from cmdb.errors.models.isms_impact import (
    IsmsImpactInitError,
    IsmsImpactInitFromDataError,
    IsmsImpactToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                                  IsmsImpact - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsImpact(CmdbDAO):
    """
    Implementation of IsmsImpact which represents one level of the ISMS impact scale

    Extends: CmdbDAO
    """
    COLLECTION = "isms.impact"
    SCHEMA: dict[str, Any] = get_isms_impact_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither;
    # REQUIRED_INIT_KEYS is what keeps from_data refusing a document that carries no name or basis
    KEYS = ImpactKey
    REQUIRED_INIT_KEYS: list[str] = IMPACT_REQUIRED_DOCUMENT_KEYS
    INIT_FROM_DATA_ERROR = IsmsImpactInitFromDataError
    TO_JSON_ERROR = IsmsImpactToJsonError

    def __init__(
        self,
        *,
        public_id: int,
        name: str,
        calculation_basis: float,
        description: str | None = None
    ) -> None:
        """
        Initialises an IsmsImpact

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        Args:
            public_id (int): public_id of the IsmsImpact
            name (str): The name of the impact level
            calculation_basis (float): The numeric weight of this impact level in the risk calculation
            description (str | None): The description of the impact level

        Raises:
            IsmsImpactInitError: If the IsmsImpact could not be initialised
        """
        try:
            self.name = name
            self.calculation_basis = calculation_basis
            self.description = description

            super().__init__(public_id = public_id)
        except Exception as err:
            raise IsmsImpactInitError(err) from err
