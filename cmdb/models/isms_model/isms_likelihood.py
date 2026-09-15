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
Implementation of IsmsLikelihood in DataGerry - ISMS

An IsmsLikelihood is one level of the ISMS likelihood scale (collection ``isms.likelihood``) - the
"how probable is it" axis of the risk matrix, whose other axis is the impact scale. Four properties of
this document are worth knowing before changing it:

**``calculation_basis`` is a number, and it is the reason this entity exists.** It is the probability
weight the risk matrix reads, and the value ``LikelihoodManager.update_with_follow_up`` writes into
``likelihood_value`` in the before and after matrices of every risk assessment that names this level
when the weight changes. It is stored as a float, greater than zero (``'min': 1e-9``, matching the
impact scale and the frontend's ``nonZeroValidator``): a zero-weight level would flatten every risk
using it. The model annotated it ``str`` until 2026-09-07, which was the only claim of that anywhere.

**The collection is a small fixed scale**, three to six rows in practice. That is why it declares no
``INDEX_KEYS`` even though the manager queries it by ``calculation_basis`` for the uniqueness
pre-check: at this size the scan is free, and the other ISMS scale entities declare none either.

**``IsmsImpact`` is its structural twin.** Both carry exactly ``public_id`` / ``name`` /
``calculation_basis`` / ``description``, so one serialises cleanly as the other - a mix-up produces a
valid-looking payload rather than an error. Until this model started sharing ``CmdbDAO.to_json``,
``IsmsLikelihood.to_json(an_impact)`` returned an impact serialised as a likelihood and said nothing;
the shared implementation type-checks its instance, which is what closed that.

**Its key set is closed.** ``LikelihoodKey`` names every persisted key and drives the shared
``CmdbDAO.from_data`` / ``to_json``; ``LIKELIHOOD_REQUIRED_DOCUMENT_KEYS`` keeps a document that lacks
a name or a weight from becoming an instance holding None
"""
from typing import Any

from cmdb.class_schema.isms_model.isms_likelihood_schema import get_isms_likelihood_schema
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_likelihood_constants import (
    LIKELIHOOD_REQUIRED_DOCUMENT_KEYS,
    LikelihoodKey,
)

from cmdb.errors.models.isms_likelihood import (
    IsmsLikelihoodInitError,
    IsmsLikelihoodInitFromDataError,
    IsmsLikelihoodToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                                IsmsLikelihood - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsLikelihood(CmdbDAO):
    """
    Implementation of IsmsLikelihood which represents one level of the ISMS likelihood scale

    Extends: CmdbDAO
    """
    COLLECTION = "isms.likelihood"
    SCHEMA: dict[str, Any] = get_isms_likelihood_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither;
    # REQUIRED_INIT_KEYS is what keeps from_data refusing a document with no name or weight
    KEYS = LikelihoodKey
    REQUIRED_INIT_KEYS: list[str] = LIKELIHOOD_REQUIRED_DOCUMENT_KEYS
    INIT_FROM_DATA_ERROR = IsmsLikelihoodInitFromDataError
    TO_JSON_ERROR = IsmsLikelihoodToJsonError

    def __init__(
        self,
        *,
        public_id: int,
        name: str,
        calculation_basis: float,
        description: str | None = None
    ) -> None:
        """
        Initialises an IsmsLikelihood

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        Args:
            public_id (int): public_id of the IsmsLikelihood
            name (str): The name of the likelihood level
            calculation_basis (float): The numeric weight of this level in the risk calculation
            description (str | None): The description of the likelihood level

        Raises:
            IsmsLikelihoodInitError: When the IsmsLikelihood could not be initialised
        """
        try:
            self.name = name
            self.calculation_basis = calculation_basis
            self.description = description

            super().__init__(public_id = public_id)
        except Exception as err:
            raise IsmsLikelihoodInitError(err) from err
