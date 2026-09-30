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
Unit tests for CmdbAuthSettings, the stored `auth` settings section

The section decides how every login works, and it has to be validated in either
direction - `AuthModule` splatted the stored document into the constructor and the update route
splatted a client payload. These tests pin what that cost:

* an unknown key was a `TypeError` from signature binding, so the `AuthSettingsInitError` the route
  catches to answer 400 could never be raised and a bad payload answered 500
* `token_lifetime` was stored verbatim, including `null` - which made `int(None)` fail on every
  token issue until somebody edited the database
* `get_provider_settings` raised `StopIteration` for an unknown provider and `KeyError` for an entry
  missing `class_name` (the malformed shape a historical AuthModule bug wrote)
* `_id` travelled in the write payload, so a client-supplied one made MongoDB refuse the whole update

No database and no app context: the model is pure. The route behaviour on top of it is covered in
the functional login-route tests.
"""
from typing import Any

import pytest

from cmdb.models.security_models import (
    AUTH_SETTINGS_ID,
    DEFAULT_TOKEN_LIFETIME,
    AuthSettingsKey,
    CmdbAuthSettings,
    ProviderEntryKey,
)
from cmdb.models.security_models.auth_settings import CONTENT_KEYS

from cmdb.errors.models.cmdb_auth_settings import AuthSettingsInitError
# -------------------------------------------------------------------------------------------------------------------- #

LOCAL_PROVIDER: str = 'LocalAuthenticationProvider'
LDAP_PROVIDER: str = 'LdapAuthenticationProvider'

LOCAL_CONFIG: dict[str, Any] = {'active': True}
LDAP_CONFIG: dict[str, Any] = {'active': False, 'default_group': 2}


def _entry(class_name: str, config: dict[str, Any]) -> dict[str, Any]:
    """One provider entry in the shape the settings section stores."""
    return {
        ProviderEntryKey.CLASS_NAME.value: class_name,
        ProviderEntryKey.CONFIG.value: config,
    }


def _complete_payload(**overrides: Any) -> dict[str, Any]:
    """A payload carrying every content key, as the settings form posts it."""
    return {
        AuthSettingsKey.PROVIDERS.value: [_entry(LOCAL_PROVIDER, LOCAL_CONFIG)],
        AuthSettingsKey.ENABLE_EXTERNAL.value: True,
        AuthSettingsKey.TOKEN_LIFETIME.value: 1440,
        **overrides,
    }


class TestFromDataAcceptsValidInput:
    """The ordinary paths: a stored document and a settings-form payload."""

    def test_reads_every_field(self) -> None:
        """All four values reach the instance, not just the ones with interesting defaults."""
        settings = CmdbAuthSettings.from_data(_complete_payload(**{AuthSettingsKey.ID.value: AUTH_SETTINGS_ID}))

        assert settings._id == AUTH_SETTINGS_ID  # pylint: disable=protected-access
        assert settings.enable_external is True
        assert settings.token_lifetime == 1440
        assert settings.get_provider_list() == [_entry(LOCAL_PROVIDER, LOCAL_CONFIG)]

    def test_an_empty_document_is_all_defaults(self) -> None:
        """A section that was never written must still produce usable settings."""
        settings = CmdbAuthSettings.from_data({})

        assert settings._id == AUTH_SETTINGS_ID  # pylint: disable=protected-access
        assert settings.get_provider_list() == []
        assert settings.enable_external is False
        assert settings.token_lifetime == DEFAULT_TOKEN_LIFETIME

    def test_id_is_accepted_but_optional(self) -> None:
        """The Angular form posts `_id` back; an API client has no reason to send it."""
        settings = CmdbAuthSettings.from_data({}, require_complete=False)

        assert settings._id == AUTH_SETTINGS_ID  # pylint: disable=protected-access

    def test_an_empty_id_falls_back(self) -> None:
        """An empty string would address no section at all."""
        settings = CmdbAuthSettings.from_data({AuthSettingsKey.ID.value: ''})

        assert settings._id == AUTH_SETTINGS_ID  # pylint: disable=protected-access

    def test_providers_is_not_shared_between_instances(self) -> None:
        """A mutable default shared across instances would leak one section's providers into another."""
        first = CmdbAuthSettings.from_data({})
        first.get_provider_list().append(_entry(LDAP_PROVIDER, LDAP_CONFIG))

        assert CmdbAuthSettings.from_data({}).get_provider_list() == []


class TestFromDataRejectsBadInput:
    """Validation is the reason from_data exists - the constructor could not do it."""

    def test_an_unknown_key_is_refused(self) -> None:
        """A TypeError from signature binding here would be reported by the route as a 500."""
        with pytest.raises(AuthSettingsInitError):
            CmdbAuthSettings.from_data({'bogus': 1})

    def test_the_message_names_the_offending_key(self) -> None:
        """The route puts this text in its 400, so it has to say which key was wrong."""
        with pytest.raises(AuthSettingsInitError) as excinfo:
            CmdbAuthSettings.from_data({'bogus': 1, 'alsobad': 2})

        assert 'bogus' in str(excinfo.value)
        assert 'alsobad' in str(excinfo.value)

    @pytest.mark.parametrize('data', ['a string', 42, None, ['a', 'list']], ids=str)
    def test_a_non_object_payload_is_refused(self, data: Any) -> None:
        """`request.get_json()` can return any JSON type, not only an object."""
        with pytest.raises(AuthSettingsInitError):
            CmdbAuthSettings.from_data(data)

    @pytest.mark.parametrize('value', [123, ['auth'], {'a': 1}], ids=str)
    def test_a_non_string_id_is_refused(self, value: Any) -> None:
        """The id addresses a settings section, so it has to be a string."""
        with pytest.raises(AuthSettingsInitError):
            CmdbAuthSettings.from_data({AuthSettingsKey.ID.value: value})

    @pytest.mark.parametrize('value', ['not-a-list', {'a': 1}, 5, ['not-an-object']], ids=str)
    def test_a_malformed_provider_list_is_refused(self, value: Any) -> None:
        """`providers` was previously stored as whatever arrived, including a bare string."""
        with pytest.raises(AuthSettingsInitError):
            CmdbAuthSettings.from_data({AuthSettingsKey.PROVIDERS.value: value})

    @pytest.mark.parametrize('value', ['yes', 'true', 1, 0], ids=str)
    def test_a_non_boolean_external_flag_is_refused(self, value: Any) -> None:
        """This flag gates external authentication entirely; a truthy string is not a yes."""
        with pytest.raises(AuthSettingsInitError):
            CmdbAuthSettings.from_data({AuthSettingsKey.ENABLE_EXTERNAL.value: value})

    def test_an_absent_external_flag_defaults_to_off(self) -> None:
        """Absent is not the same as malformed: external authentication is off unless enabled."""
        assert CmdbAuthSettings.from_data({}).enable_external is False


class TestTokenLifetimeValidation:
    """Every issued token's expiry comes from this one number."""

    def test_a_valid_lifetime_is_kept(self) -> None:
        """The ordinary case: a positive whole number of minutes."""
        assert CmdbAuthSettings.from_data({AuthSettingsKey.TOKEN_LIFETIME.value: 1440}).get_token_lifetime() == 1440

    def test_an_absent_lifetime_is_the_default(self) -> None:
        """A document written before the key existed still has to produce a working token."""
        assert CmdbAuthSettings.from_data({}).get_token_lifetime() == DEFAULT_TOKEN_LIFETIME

    @pytest.mark.parametrize('value', [0, -1, -1440], ids=str)
    def test_a_non_positive_lifetime_is_refused(self, value: int) -> None:
        """A zero or negative lifetime issues tokens that have already expired."""
        with pytest.raises(AuthSettingsInitError):
            CmdbAuthSettings.from_data({AuthSettingsKey.TOKEN_LIFETIME.value: value})

    @pytest.mark.parametrize('value', ['abc', '1440', 14.4, [1440], {'m': 1440}], ids=str)
    def test_a_non_integer_lifetime_is_refused(self, value: Any) -> None:
        """TokenGenerator does int(...) on this; a string that does not parse fails every login."""
        with pytest.raises(AuthSettingsInitError):
            CmdbAuthSettings.from_data({AuthSettingsKey.TOKEN_LIFETIME.value: value})

    def test_a_boolean_lifetime_is_refused(self) -> None:
        """bool subclasses int, so True would silently become a one-minute token lifetime."""
        with pytest.raises(AuthSettingsInitError):
            CmdbAuthSettings.from_data({AuthSettingsKey.TOKEN_LIFETIME.value: True})


class TestRequireComplete:
    """A client update carries the whole section; a stored document may be older than a key."""

    def test_a_complete_payload_is_accepted(self) -> None:
        """What the Angular settings form posts, minus the `_id` it also sends."""
        assert CmdbAuthSettings.from_data(_complete_payload(), require_complete=True).token_lifetime == 1440

    @pytest.mark.parametrize('missing', sorted(CONTENT_KEYS), ids=str)
    def test_every_content_key_is_required(self, missing: str) -> None:
        """
        Omitting one silently blanks it

        A payload without `providers` must not reset the list to empty - that deletes the configured LDAP
        provider - because an absent key and a reset to the default are indistinguishable.
        """
        payload = _complete_payload()
        del payload[missing]

        with pytest.raises(AuthSettingsInitError):
            CmdbAuthSettings.from_data(payload, require_complete=True)

    def test_the_id_is_not_required(self) -> None:
        """It addresses the section rather than living in it, and to_json does not emit it."""
        payload = _complete_payload()

        assert AuthSettingsKey.ID.value not in payload
        assert CmdbAuthSettings.from_data(payload, require_complete=True) is not None

    def test_a_partial_stored_document_still_loads(self) -> None:
        """Applying the same strictness to reads would break the login path on an older section."""
        settings = CmdbAuthSettings.from_data({AuthSettingsKey.ENABLE_EXTERNAL.value: True})

        assert settings.token_lifetime == DEFAULT_TOKEN_LIFETIME


class TestToJson:
    """What actually goes back into the settings collection."""

    def test_omits_the_id(self) -> None:
        """SettingsManager.write takes the id separately, and MongoDB refuses a $set on _id."""
        stored = CmdbAuthSettings.to_json(CmdbAuthSettings.from_data(_complete_payload()))

        assert AuthSettingsKey.ID.value not in stored

    def test_carries_every_content_key(self) -> None:
        """The write is a full replacement of the section's contents."""
        stored = CmdbAuthSettings.to_json(CmdbAuthSettings.from_data(_complete_payload()))

        assert set(stored) == CONTENT_KEYS

    def test_round_trips(self) -> None:
        """What was written has to read back as the same settings."""
        original = CmdbAuthSettings.from_data(_complete_payload())
        restored = CmdbAuthSettings.from_data(CmdbAuthSettings.to_json(original))

        assert restored.token_lifetime == original.token_lifetime
        assert restored.enable_external == original.enable_external
        assert restored.get_provider_list() == original.get_provider_list()


class TestGetProviderSettings:
    """Reading one provider's configuration out of the list."""

    @pytest.fixture(name='settings')
    def fixture_settings(self) -> CmdbAuthSettings:
        """A section carrying two good entries and one malformed one."""
        return CmdbAuthSettings.from_data({
            AuthSettingsKey.PROVIDERS.value: [
                _entry(LOCAL_PROVIDER, LOCAL_CONFIG),
                {'default_group': 2},
                _entry(LDAP_PROVIDER, LDAP_CONFIG),
            ],
        })

    def test_returns_the_config_sub_document(self, settings: CmdbAuthSettings) -> None:
        """The caller hands the result straight to the provider's config class."""
        assert settings.get_provider_settings(LOCAL_PROVIDER) == LOCAL_CONFIG

    def test_an_unknown_provider_is_none_not_an_exception(self, settings: CmdbAuthSettings) -> None:
        """A bare next() raises StopIteration, which the one caller would have to catch to fall back."""
        assert settings.get_provider_settings('NoSuchProvider') is None

    def test_a_malformed_entry_does_not_break_the_lookup(self, settings: CmdbAuthSettings) -> None:
        """
        An entry with no `class_name` must not raise KeyError, because nothing catches it

        That shape is what a historical AuthModule bug wrote into this list, so a lookup must walk
        past it rather than fail on it - including for a provider listed AFTER the bad entry.
        """
        assert settings.get_provider_settings(LDAP_PROVIDER) == LDAP_CONFIG

    def test_an_entry_without_a_config_is_none(self) -> None:
        """A half-written entry must not hand the provider class a KeyError either."""
        half_written = CmdbAuthSettings.from_data({
            AuthSettingsKey.PROVIDERS.value: [{ProviderEntryKey.CLASS_NAME.value: LOCAL_PROVIDER}],
        })

        assert half_written.get_provider_settings(LOCAL_PROVIDER) is None

    def test_an_empty_list_is_none(self) -> None:
        """A section with no providers at all is normal on a fresh installation."""
        assert CmdbAuthSettings.from_data({}).get_provider_settings(LOCAL_PROVIDER) is None
