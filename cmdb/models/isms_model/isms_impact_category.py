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
Implementation of IsmsImpactCategory in DataGerry - ISMS

An IsmsImpactCategory groups the per-impact-level descriptions of the ISMS impact scale (collection
``isms.impactCategory``): one category, one description per IsmsImpact.

**The nested list is maintained by the impact routes, not by this model.** Creating an IsmsImpact
pushes an entry into every category (`add_new_impact_to_categories`) and deleting one pulls it out
again, so a category's ``impact_descriptions`` mirrors the impact scale rather than being edited as a
whole. That is also why the absence of the key is normalised to an empty list here: a category written
before any impact existed carries none, and what the push writes into must be a list.

``ImpactCategoryKey`` names every persisted key and drives the shared ``CmdbDAO`` ``from_data`` /
``to_json``, so this model defines neither; ``ImpactDescriptionKey`` names the nested entry's keys
"""
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_impact_category_constants import (
    IMPACT_CATEGORY_REQUIRED_DOCUMENT_KEYS,
    ImpactCategoryKey,
)

from cmdb.class_schema.isms_model.isms_impact_category_schema import get_isms_impact_category_schema

from cmdb.errors.models.isms_impact_category import (
    IsmsImpactCategoryInitError,
    IsmsImpactCategoryInitFromDataError,
    IsmsImpactCategoryToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                              IsmsImpactCategory - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsImpactCategory(CmdbDAO):
    """
    Implementation of IsmsImpactCategory which represents an impact category

    Extends: CmdbDAO
    """
    COLLECTION = "isms.impactCategory"

    SCHEMA: dict[str, Any] = get_isms_impact_category_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither;
    # REQUIRED_INIT_KEYS is what keeps from_data refusing a document that carries no name
    KEYS = ImpactCategoryKey
    REQUIRED_INIT_KEYS: list[str] = IMPACT_CATEGORY_REQUIRED_DOCUMENT_KEYS
    INIT_FROM_DATA_ERROR = IsmsImpactCategoryInitFromDataError
    TO_JSON_ERROR = IsmsImpactCategoryToJsonError

    def __init__(
            self,
            *,
            public_id: int,
            name: str,
            impact_descriptions: list[dict[str, Any]] | None = None,
            sort: int | None = None,
        ) -> None:
        """
        Initialises an IsmsImpactCategory

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        Args:
            public_id (int): public_id of the IsmsImpactCategory
            name (str): The name of the IsmsImpactCategory
            impact_descriptions (list[dict[str, Any]], optional): One description entry per IsmsImpact.
                An absent value becomes an EMPTY LIST rather than None - a category that predates every
                impact carries none, and the impact routes push into this list
            sort (int | None): Sort order of the category. Defaults to None

        Raises:
            IsmsImpactCategoryInitError: When the IsmsImpactCategory could not be initialised
        """
        try:
            self.name = name
            self.impact_descriptions = impact_descriptions or []
            self.sort = sort

            super().__init__(public_id=public_id)
        except Exception as err:
            raise IsmsImpactCategoryInitError(err) from err
