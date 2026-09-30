"""
Unit tests for cmdb.security.key.secret_resolver

The one place that answers "where does this secret come from". The ladder it implements - app value
in cloud+local, Base64 environment variable in hosted cloud, settings section on-premise - it is easy to
written out three times, once in `SecurityManager` and twice byte-for-byte in `KeyHolder`, which is
how the same missing-environment-variable bug came to exist in both copies.

Two properties matter beyond "it picks the right branch":

* **the source that does not apply is never evaluated** - both are callables precisely so the
  on-premise settings read does not happen when the environment already holds the answer
* **a malformed Base64 value is refused the same way an absent one is** - decoding it unguarded raises
  `binascii.Error` out of a login request as an unexplained 500
"""
import base64

import pytest

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.security.key.secret_resolver import (
    SYMMETRIC_KEY_BYTES,
    decode_env_secret,
    new_symmetric_aes_key,
    resolve_secret,
)
# -------------------------------------------------------------------------------------------------------------------- #

ENV_VAR: str = 'DG_TEST_SECRET'
LABEL: str = 'test secret'
SECRET: bytes = b'the-real-secret-value'


def _app(cloud_mode: bool, local_mode: bool) -> BaseCmdbApp:
    """Builds an app flagged for one of the three deployment shapes."""
    app = BaseCmdbApp(__name__)
    app.cloud_mode = cloud_mode
    app.local_mode = local_mode

    return app


class _Recorder:
    """A source callable that records whether it was asked for its value."""

    def __init__(self, value: bytes) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> bytes:
        self.calls += 1

        return self.value


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 decode_env_secret                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDecodeEnvSecret:
    """Reading a Base64 secret out of the environment."""

    def test_it_decodes_a_valid_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The happy path: what the operator set, Base64-decoded."""
        monkeypatch.setenv(ENV_VAR, base64.b64encode(SECRET).decode())

        assert decode_env_secret(ENV_VAR, LABEL) == SECRET

    def test_an_absent_variable_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A hosted installation with no key configured must fail loudly."""
        monkeypatch.delenv(ENV_VAR, raising=False)

        with pytest.raises(ValueError, match=ENV_VAR):
            decode_env_secret(ENV_VAR, LABEL)

    def test_an_empty_variable_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Set-but-empty is the same operator mistake as unset."""
        monkeypatch.setenv(ENV_VAR, '')

        with pytest.raises(ValueError, match=ENV_VAR):
            decode_env_secret(ENV_VAR, LABEL)

    def test_a_malformed_value_is_refused_as_a_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        A binascii.Error out of a login request is an unexplained 500

        The absent case was handled precisely and the malformed one was not, although both are the
        same mistake seen from different angles.
        """
        monkeypatch.setenv(ENV_VAR, 'not-base64-at-all!!')

        with pytest.raises(ValueError, match='Base64'):
            decode_env_secret(ENV_VAR, LABEL)

    def test_the_refusal_names_the_variable_and_the_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An operator reading the log should not have to guess which of three keys is wrong."""
        monkeypatch.setenv(ENV_VAR, '%%%')

        with pytest.raises(ValueError) as err:
            decode_env_secret(ENV_VAR, LABEL)

        assert ENV_VAR in str(err.value)
        assert LABEL in str(err.value)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  resolve_secret                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestResolveSecret:
    """Which source answers, per deployment shape."""

    def test_cloud_and_local_uses_the_app_value(self) -> None:
        """A developer's own stack carries its dev keys on the app."""
        dev, stored = _Recorder(SECRET), _Recorder(b'stored')

        with _app(cloud_mode=True, local_mode=True).app_context():
            assert resolve_secret(dev, ENV_VAR, LABEL, stored) == SECRET

    def test_hosted_cloud_uses_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A hosted installation is configured by environment, not by its database."""
        monkeypatch.setenv(ENV_VAR, base64.b64encode(SECRET).decode())
        dev, stored = _Recorder(b'dev'), _Recorder(b'stored')

        with _app(cloud_mode=True, local_mode=False).app_context():
            assert resolve_secret(dev, ENV_VAR, LABEL, stored) == SECRET

    def test_on_premise_uses_the_settings_section(self) -> None:
        """The only shape that reads a database for its keys."""
        dev, stored = _Recorder(b'dev'), _Recorder(SECRET)

        with _app(cloud_mode=False, local_mode=False).app_context():
            assert resolve_secret(dev, ENV_VAR, LABEL, stored) == SECRET

    def test_the_stored_source_is_not_read_in_cloud_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Laziness is the reason both sources are callables

        Evaluating the settings read to answer a question the environment already answers would be a
        database round trip per token signed.
        """
        monkeypatch.setenv(ENV_VAR, base64.b64encode(SECRET).decode())
        dev, stored = _Recorder(b'dev'), _Recorder(b'stored')

        with _app(cloud_mode=True, local_mode=False).app_context():
            resolve_secret(dev, ENV_VAR, LABEL, stored)

        assert stored.calls == 0
        assert dev.calls == 0

    def test_the_environment_is_not_read_on_premise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An on-premise installation must not need any DG_* variable set."""
        monkeypatch.delenv(ENV_VAR, raising=False)
        dev, stored = _Recorder(b'dev'), _Recorder(SECRET)

        with _app(cloud_mode=False, local_mode=False).app_context():
            assert resolve_secret(dev, ENV_VAR, LABEL, stored) == SECRET

        assert dev.calls == 0

    def test_a_missing_environment_value_still_raises_through_the_ladder(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The hosted branch does not silently fall through to the stored value."""
        monkeypatch.delenv(ENV_VAR, raising=False)
        dev, stored = _Recorder(b'dev'), _Recorder(b'stored')

        with _app(cloud_mode=True, local_mode=False).app_context():
            with pytest.raises(ValueError):
                resolve_secret(dev, ENV_VAR, LABEL, stored)

        assert stored.calls == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                               new_symmetric_aes_key                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestNewSymmetricAesKey:
    """The single definition of what a symmetric key is."""

    def test_it_is_the_declared_length(self) -> None:
        """32 bytes: AES-256, and the key of the HMAC-SHA256 that stores passwords."""
        assert len(new_symmetric_aes_key()) == SYMMETRIC_KEY_BYTES

    def test_two_keys_differ(self) -> None:
        """It is randomness, not a constant."""
        assert new_symmetric_aes_key() != new_symmetric_aes_key()
