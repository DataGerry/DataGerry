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
Unit tests for cmdb.security.token.validator

The gate every protected request passes through, and it had **no test module of its own** until
2026-09-10: the only tests that reached it patched it out at the interface layer, which is why its
two refusal arms were its uncovered statements.

Real RSA keys are generated per test and the validator's KeyHolder is replaced with a stub, so
nothing here needs a database or a Flask app - the signatures are genuine and so are the joserfc
errors.

The properties pinned here are the ones a refactor would silently break:

* **the two-step contract**: `decode_token` verifies the signature ONLY - an expired token decodes
  successfully - and `validate_claims` is the single place a token expires. Three of the four call
  sites in the product call `decode_token` alone and are safe only because the header parser ran both
  steps first;
* **`exp` is required**: a signed token carrying no time claims used to validate forever, because a
  claims registry only checks what it is handed;
* **a server-side key problem is not a bad credential**: it raises `TokenKeyMaterialError`, which the
  routes answer with 500 rather than logging the user out with a 401;
* **the algorithm whitelist**: an RS256-signed token is refused under the RS512 whitelist.
"""
import time
from typing import Any

import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey

from cmdb.security.token.token_constants import (
    TOKEN_TIME_CLAIM_LEEWAY,
    TokenAlgorithm,
    TokenClaim,
    TokenClaimWrapperKey,
    TokenTimeClaim,
)
from cmdb.security.token.validator import TokenValidator

from cmdb.errors.security import TokenKeyMaterialError, TokenValidationError
# -------------------------------------------------------------------------------------------------------------------- #

ISSUER: str = 'DataGerry'
USER_ID: int = 1


class _StubKeyHolder:
    """Stands in for KeyHolder: holds the public key, and nothing else."""

    def __init__(self, public_key: Any) -> None:
        """Stores the key material the validator will read."""
        self.rsa_public = public_key
        self.rsa_private = None


@pytest.fixture(name='key')
def fixture_key() -> RSAKey:
    """A freshly generated RSA key pair."""
    return RSAKey.generate_key(2048)


@pytest.fixture(name='validator')
def fixture_validator(key: RSAKey) -> TokenValidator:
    """A TokenValidator verifying against the generated key, with no database behind it."""
    validator = TokenValidator.__new__(TokenValidator)
    validator.key_holder = _StubKeyHolder(key.as_pem(private=False))

    return validator


def _claims(**overrides: Any) -> dict[str, Any]:
    """The claims a DataGerry token carries, wrapper shape included."""
    now = int(time.time())
    claims: dict[str, Any] = {
        TokenClaim.ISSUER.value: {
            TokenClaimWrapperKey.ESSENTIAL.value: True,
            TokenClaimWrapperKey.VALUE.value: ISSUER,
        },
        TokenTimeClaim.ISSUED_AT.value: now,
        TokenTimeClaim.EXPIRATION.value: now + 3600,
        TokenClaim.DATAGERRY.value: {
            TokenClaimWrapperKey.ESSENTIAL.value: True,
            TokenClaimWrapperKey.VALUE.value: {'user': {'public_id': USER_ID}},
        },
    }
    claims.update(overrides)

    return claims


def _token(key: RSAKey, algorithm: str = TokenAlgorithm.RS512.value, **overrides: Any) -> str:
    """Signs the claims with the given key and algorithm."""
    return jwt.encode({'alg': algorithm}, _claims(**overrides), key, algorithms=[algorithm])


# -------------------------------------------------------------------------------------------------------------------- #
#                                             step one: the signature                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDecodeToken:
    """Verifying the signature and the algorithm."""

    def test_a_valid_token_answers_its_claims(self, validator: TokenValidator, key: RSAKey) -> None:
        """The claims are what every consumer reads the acting user out of"""
        claims = validator.decode_token(_token(key))

        assert claims[TokenClaim.DATAGERRY.value][TokenClaimWrapperKey.VALUE.value]['user'] == {
            'public_id': USER_ID,
        }

    def test_an_expired_token_still_decodes(self, validator: TokenValidator, key: RSAKey) -> None:
        """
        The property the whole two-step contract rests on

        `joserfc.jwt.decode` inspects no claim, so expiry is NOT enforced here - and three of the
        four call sites in the product call only this method. If this test ever starts failing
        because decode began refusing expired tokens, the caching in `route_utils` can be simplified;
        if `validate_claims` is ever dropped instead, expired tokens are accepted everywhere.
        """
        past = int(time.time()) - 7200
        claims = validator.decode_token(_token(key, iat=past, exp=past + 60))

        assert claims[TokenTimeClaim.EXPIRATION.value] < int(time.time())

    def test_a_foreign_signature_is_refused(self, validator: TokenValidator) -> None:
        """A token signed with another key is not this installation's token"""
        with pytest.raises(TokenValidationError):
            validator.decode_token(_token(RSAKey.generate_key(2048)))

    def test_a_tampered_token_is_refused(self, validator: TokenValidator, key: RSAKey) -> None:
        """Flipping a byte of the payload invalidates the signature"""
        header, payload, signature = _token(key).split('.')

        with pytest.raises(TokenValidationError):
            validator.decode_token(f"{header}.{payload[:-2]}xx.{signature}")

    @pytest.mark.parametrize('token', ['', 'not-a-token', 'a.b.c', None])
    def test_garbage_is_refused(self, validator: TokenValidator, token: Any) -> None:
        """Whatever arrives in the Authorization header reaches this method unchecked"""
        with pytest.raises(TokenValidationError):
            validator.decode_token(token)

    def test_another_algorithm_is_refused(self, validator: TokenValidator, key: RSAKey) -> None:
        """
        The whitelist is the point: RS512 only

        An attacker who could choose the algorithm could choose a weaker one - the check runs before
        the signature is verified.
        """
        with pytest.raises(TokenValidationError):
            validator.decode_token(_token(key, algorithm='RS256'))

    def test_unusable_key_material_is_not_a_token_error(self, validator: TokenValidator, key: RSAKey) -> None:
        """
        A server-side key problem must not be answered as a bad credential

        An unset DG_RSA_PUBLIC_KEY or an unreadable settings document used to surface as
        TokenValidationError, i.e. 401 'Invalid Token!' for every client of a misconfigured
        installation.
        """
        validator.key_holder.rsa_public = b'not a key'

        with pytest.raises(TokenKeyMaterialError):
            validator.decode_token(_token(key))


# -------------------------------------------------------------------------------------------------------------------- #
#                                              step two: the claims                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestValidateClaims:
    """The only place a token expires."""

    def test_fresh_claims_pass(self, validator: TokenValidator) -> None:
        """A token inside its lifetime validates silently"""
        assert validator.validate_claims(_claims()) is None

    def test_an_expired_token_is_refused(self, validator: TokenValidator) -> None:
        """The refusal the whole product relies on"""
        past = int(time.time()) - 7200

        with pytest.raises(TokenValidationError):
            validator.validate_claims(_claims(iat=past, exp=past + 60))

    def test_claims_without_an_expiration_are_refused(self, validator: TokenValidator) -> None:
        """
        `exp` is essential

        A claims registry only checks what it is handed, so a signed token carrying no time claims
        used to be valid forever.
        """
        claims = _claims()
        del claims[TokenTimeClaim.EXPIRATION.value]

        with pytest.raises(TokenValidationError):
            validator.validate_claims(claims)

    def test_a_not_yet_valid_token_is_refused(self, validator: TokenValidator) -> None:
        """`nbf` is honoured when a token carries one"""
        future = int(time.time()) + 7200

        with pytest.raises(TokenValidationError):
            validator.validate_claims(_claims(nbf=future))

    def test_a_clock_a_little_ahead_is_tolerated(self, validator: TokenValidator) -> None:
        """
        The leeway exists because the stamping and the validating process need not share a clock

        DataGerry issues a token in one worker and validates it in another, possibly on another node.
        """
        just_ahead = int(time.time()) + int(TOKEN_TIME_CLAIM_LEEWAY / 2)

        assert validator.validate_claims(_claims(iat=just_ahead, nbf=just_ahead)) is None

    def test_a_clock_far_ahead_is_still_refused(self, validator: TokenValidator) -> None:
        """The tolerance is bounded - it is skew, not a licence to accept future tokens"""
        far_ahead = int(time.time()) + TOKEN_TIME_CLAIM_LEEWAY + 3600

        with pytest.raises(TokenValidationError):
            validator.validate_claims(_claims(nbf=far_ahead))

    @pytest.mark.parametrize('exp', ['soon', None, [1], {'at': 1}])
    def test_a_claim_of_the_wrong_type_is_a_token_error(self, validator: TokenValidator, exp: Any) -> None:
        """
        A non-numeric expiration is an invalid token, not a server error

        joserfc answers these with InvalidClaimError / MissingClaimError - both JoseErrors - which is
        the correction to the audit's assumption that a wrong-typed claim escaped the JoseError arm.
        """
        with pytest.raises(TokenValidationError):
            validator.validate_claims(_claims(exp=exp))

    def test_claims_that_are_not_a_mapping_are_a_token_error(self, validator: TokenValidator) -> None:
        """
        The arm that does catch a non-JoseError

        Handing this method something that is not a claims dict is a caller mistake, and it still
        has to surface as the domain error the routes map - not as a 500.
        """
        with pytest.raises(TokenValidationError):
            validator.validate_claims(None)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the issuer                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestValidateIssuer:
    """The claim a plain registry cannot check."""

    def test_the_products_own_token_passes(self, validator: TokenValidator) -> None:
        """The wrapper's `value` is where the issuer actually sits"""
        assert validator.validate_issuer(_claims(), ISSUER) is None

    def test_a_plain_string_issuer_passes(self, validator: TokenValidator) -> None:
        """
        What the JWT spec asks for, accepted too

        So the wrapper can be dropped one day without this check having to change with it.
        """
        assert validator.validate_issuer(_claims(iss=ISSUER), ISSUER) is None

    def test_a_foreign_issuer_is_refused(self, validator: TokenValidator) -> None:
        """A validly signed token from somewhere else is still not ours"""
        with pytest.raises(TokenValidationError):
            validator.validate_issuer(_claims(iss='SomethingElse'), ISSUER)

    def test_a_missing_issuer_is_refused(self, validator: TokenValidator) -> None:
        """Every token the generator issues carries one"""
        claims = _claims()
        del claims[TokenClaim.ISSUER.value]

        with pytest.raises(TokenValidationError):
            validator.validate_issuer(claims, ISSUER)

    def test_an_empty_wrapper_is_refused(self, validator: TokenValidator) -> None:
        """A wrapper without its `value` names no issuer at all"""
        with pytest.raises(TokenValidationError):
            validator.validate_issuer(_claims(iss={TokenClaimWrapperKey.ESSENTIAL.value: True}), ISSUER)

    def test_the_error_names_the_expected_issuer(self, validator: TokenValidator) -> None:
        """The message is what an operator debugging a rejected token reads"""
        with pytest.raises(TokenValidationError) as err:
            validator.validate_issuer(_claims(iss='SomethingElse'), ISSUER)

        assert ISSUER in str(err.value)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the key material                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheKeyHolder:
    """What the validator asks the KeyHolder for."""

    def test_it_asks_for_the_public_key_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Verifying needs no private key

        Loading it was a settings read per validator that could not be used for anything - and a key
        that is never loaded cannot leak.
        """
        recorded: dict[str, Any] = {}

        class _RecordingKeyHolder:
            """Records how the validator constructs its key holder."""

            def __init__(self, dbm: Any, with_private_key: bool = True) -> None:
                """Captures the flag and the database manager."""
                recorded['dbm'] = dbm
                recorded['with_private_key'] = with_private_key
                self.rsa_public = None
                self.rsa_private = None

        monkeypatch.setattr('cmdb.security.token.validator.KeyHolder', _RecordingKeyHolder)

        TokenValidator('the-dbm')

        assert recorded == {'dbm': 'the-dbm', 'with_private_key': False}

    def test_the_public_key_is_not_re_read_per_decode(
            self, key: RSAKey, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        The key the holder already loaded is the one used

        Calling get_public_key() again cost one settings read per decode, on the hottest path in the
        product - so a holder whose accessor refuses to run a second time must still decode.
        """
        public_pem = key.as_pem(private=False)

        class _OneShotKeyHolder:
            """Answers the key once, then refuses - as a settings read would be a second query."""

            def __init__(self, dbm: Any, with_private_key: bool = True) -> None:
                """Loads the key exactly once, like the real holder's constructor."""
                del dbm, with_private_key
                self.rsa_public = public_pem
                self.rsa_private = None

            def get_public_key(self) -> bytes:
                """Fails the test if the validator re-reads the key."""
                raise AssertionError('the public key was read again during decode')

        monkeypatch.setattr('cmdb.security.token.validator.KeyHolder', _OneShotKeyHolder)

        validator = TokenValidator('the-dbm')

        assert validator.decode_token(_token(key))[TokenTimeClaim.EXPIRATION.value] > int(time.time())
