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
Document keys of an IsmsImpact

The keys of the ``isms.impact`` documents, named once - they were spelled out as bare literals in the
model's ``from_data``, its ``to_json`` and the Cerberus schema.

``IMPACT_REQUIRED_DOCUMENT_KEYS`` is the pair a stored document must carry. The model reads its keys
through the shared ``CmdbDAO.from_data``, which uses ``data.get()``; declaring these as
``REQUIRED_INIT_KEYS`` keeps the strictness the model had while it read them with ``data['key']``, so a
document missing a name or a calculation basis is still refused instead of becoming an instance holding
None.

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo filter
key or a projection key, so what reaches the database is a plain string
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ImpactKey',
    'IMPACT_REQUIRED_DOCUMENT_KEYS',
]


class ImpactKey(BaseStrEnum):
    """
    Field keys of an IsmsImpact document
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    CALCULATION_BASIS = 'calculation_basis'
    DESCRIPTION = 'description'


# The keys without which an impact level means nothing: its label and its numeric weight
IMPACT_REQUIRED_DOCUMENT_KEYS: list[str] = [
    ImpactKey.NAME.value,
    ImpactKey.CALCULATION_BASIS.value,
]
