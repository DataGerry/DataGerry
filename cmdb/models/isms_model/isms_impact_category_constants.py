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
Document keys of an IsmsImpactCategory

The keys of the ``isms.impactCategory`` documents, named once - they were spelled out as bare literals
in the model's ``from_data``, its ``to_json``, the Cerberus schema and the manager's push/pull updates:
18 occurrences for six keys.

**Two enums, because the document nests.** A category holds one description entry PER IsmsImpact in
``impact_descriptions``, and those entries have their own two keys - so ``ImpactDescriptionKey`` names
the inner shape the way ``RiskMatrixCellKey`` names the matrix's cells. The manager's
``add_new_impact_to_categories`` / ``remove_deleted_impact_from_categories`` write that inner shape
directly (a ``$addToSet`` and a ``$pull`` on the same path), which is precisely where a misspelled key
does nothing at all rather than failing.

``IMPACT_CATEGORY_REQUIRED_DOCUMENT_KEYS`` is what a stored document must carry. The shared
``CmdbDAO.from_data`` reads with ``data.get()``, so without this a category missing its name would
become an instance holding None and serialise back into a document its own schema rejects.
``impact_descriptions`` is deliberately NOT in that list: a category written before any impact existed
carries none, and the constructor normalises the absence to an empty list instead of refusing the read

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo filter
key or a projection key, so what reaches the database is a plain string
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ImpactCategoryKey',
    'ImpactDescriptionKey',
    'IMPACT_CATEGORY_REQUIRED_DOCUMENT_KEYS',
    'NEW_IMPACT_DESCRIPTION_PLACEHOLDER',
]


class ImpactCategoryKey(BaseStrEnum):
    """
    Field keys of an IsmsImpactCategory document
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    IMPACT_DESCRIPTIONS = 'impact_descriptions'
    SORT = 'sort'


class ImpactDescriptionKey(BaseStrEnum):
    """
    Field keys of one entry inside an IsmsImpactCategory's ``impact_descriptions`` list
    """
    IMPACT_ID = 'impact_id'
    VALUE = 'value'


# The key without which a category means nothing: its label. 'impact_descriptions' is absent on purpose
# - a category that predates every impact carries none, and the constructor reads that as an empty list
IMPACT_CATEGORY_REQUIRED_DOCUMENT_KEYS: list[str] = [
    ImpactCategoryKey.NAME.value,
]


# What a freshly pushed description entry says until an admin fills it in: creating an IsmsImpact adds
# one entry to every category, and the grid has to render something in that cell meanwhile
NEW_IMPACT_DESCRIPTION_PLACEHOLDER: str = '-'
