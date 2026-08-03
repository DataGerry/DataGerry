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
Signing and claim-name constants shared by TokenGenerator and TokenValidator

The signing algorithm is centralised here so the generator (which stamps it into the JWT
header) and the validator (which whitelists it when decoding) can never drift apart. The
time-claim enum names the registered JWT claims whose expiration semantics the validator
enforces. All enums extend BaseStrEnum so members are interchangeable with their string
values for JSON serialization, dict lookup and equality
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class TokenAlgorithm(BaseStrEnum):
    """
    RSA signature algorithms permitted for DataGerry JWTs
    """
    RS512 = 'RS512'


class TokenTimeClaim(BaseStrEnum):
    """
    Registered JWT claim names carrying time/expiration semantics validated on decode
    """
    ISSUED_AT = 'iat'
    EXPIRATION = 'exp'
    NOT_BEFORE = 'nbf'
