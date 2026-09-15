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

**A DataGerry token's non-registered claims are wrapped**: `iss` and `DATAGERRY` each hold
`{'essential': True, 'value': <the actual value>}` rather than the value itself. That shape is a
leftover of the authlib claims *specification* the generator used to hand to its validator, which
now gets persisted as claim *data* - which is why every consumer reads
`token['DATAGERRY']['value']['user']` and why `iss` cannot be checked by a plain claims registry.
It is frontend- and token-compatibility contract: changing it would invalidate every token in
circulation, so it is named here (`TokenClaim`, `TokenClaimWrapperKey`) and read through the enum
instead of being fixed
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


class TokenClaim(BaseStrEnum):
    """
    The non-registered claims a DataGerry token carries, both wrapped (see the module docstring)

    ISSUER holds the product title and identifies a token as DataGerry's own; DATAGERRY holds the
    payload every consumer reads the acting user out of
    """
    ISSUER = 'iss'
    DATAGERRY = 'DATAGERRY'


class TokenClaimWrapperKey(BaseStrEnum):
    """
    The two keys of the wrapper around a `TokenClaim` value

    `VALUE` carries the claim's actual content; `ESSENTIAL` is the authlib specification flag that
    ended up in the token as data and is not read by anything
    """
    ESSENTIAL = 'essential'
    VALUE = 'value'


# Tolerance in seconds for the registered time claims. DataGerry stamps 'iat' in one process and
# validates in another - a gunicorn worker, or another node behind a load balancer - so a host clock
# a second ahead must not make a freshly issued token invalid
TOKEN_TIME_CLAIM_LEEWAY: int = 60
