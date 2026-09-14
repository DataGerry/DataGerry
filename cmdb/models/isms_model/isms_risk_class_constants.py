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
Document keys of an IsmsRiskClass

The keys of the ``isms.riskClass`` documents, named once - they were spelled out as bare literals in
the model's ``from_data``, its ``to_json`` and the Cerberus schema: 15 occurrences for five keys.

A risk class is a severity band applied to a calculated risk value, and the matrix references it by
``public_id`` only (``RiskMatrixCellKey.RISK_CLASS_ID``), so nothing outside this document needs the
other four keys - which is why the key set stayed invisible until the model was migrated onto the
shared ``CmdbDAO`` document triple, where ``KEYS`` is what drives ``from_data`` / ``to_json``.

The ISMS report aggregations name ``color`` and ``public_id`` as **dotted paths inside pipeline
literals** (``"$risk_before_class.color"``). Those deliberately stay as strings: a pipeline literal is
not a dict lookup, and an enum buys nothing there - the same boundary the risk-matrix helper drew for
its cell paths.

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo filter
key or a projection key, so what reaches the database is a plain string
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RiskClassKey',
]


class RiskClassKey(BaseStrEnum):
    """
    Field keys of an IsmsRiskClass document
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    COLOR = 'color'
    SORT = 'sort'
    DESCRIPTION = 'description'
