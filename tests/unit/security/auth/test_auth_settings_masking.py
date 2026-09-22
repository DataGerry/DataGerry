"""
Unit tests for cmdb.security.auth.auth_settings_masking

The `auth` section holds one credential - the LDAP bind password - and it used to be served in
cleartext by every read. Masking it is only half a rule: the update route takes the WHOLE section, so
a client that reads, edits one field and posts the object back would write the mask as the new
password. These tests pin both halves and the boundary between them:

* a secret is masked on the way out, everything else is carried through untouched
* the mask sent back unchanged resolves to the STORED value, not to the mask
* a real value at a secret path is a deliberate change and survives
* nothing here mutates what it was handed - a masked copy must never become the document a later
  write reads its stored values from
* which paths are secret comes from the provider's own declaration, not from a list in this module
"""
from copy import deepcopy
from typing import Any

from cmdb.security.auth.auth_module import AuthModule
from cmdb.security.auth.base_provider_config import BaseAuthProviderConfig
from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig
from cmdb.security.auth.auth_settings_masking import (
    MASKED_SECRET,
    mask_auth_settings,
    mask_provider_config,
    restore_masked_secrets,
)
# -------------------------------------------------------------------------------------------------------------------- #

LDAP: str = 'LdapAuthenticationProvider'
LOCAL: str = 'LocalAuthenticationProvider'

STORED_PASSWORD: str = 'the-real-bind-password'


def _settings(password: Any = STORED_PASSWORD) -> dict[str, Any]:
    """Builds an auth settings document with one configured LDAP provider"""
    return {
        '_id': 'auth',
        'enable_external': True,
        'token_lifetime': 1400,
        'providers': [
            {'class_name': LOCAL, 'config': {'active': True}},
            {
                'class_name': LDAP,
                'config': {
                    'active': True,
                    'server_config': {'host': 'ldap.example.com', 'port': 389},
                    'connection_config': {'user': 'cn=reader', 'password': password, 'version': 3},
                },
            },
        ],
    }


def _ldap_config(settings: dict[str, Any]) -> dict[str, Any]:
    """Reads the LDAP provider's config out of a settings document, skipping malformed entries"""
    return next(
        entry['config'] for entry in settings['providers']
        if isinstance(entry, dict) and entry.get('class_name') == LDAP
    )


def _password(settings: dict[str, Any]) -> Any:
    """Reads the LDAP bind password out of a settings document"""
    return _ldap_config(settings)['connection_config']['password']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 THE DECLARATION                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSecretDeclaration:
    """Which values are secret is the provider's own statement, not a list in the masking module."""

    def test_the_ldap_config_declares_its_bind_password(self) -> None:
        """The one credential in the authentication settings."""
        assert ('connection_config', 'password') in LdapAuthenticationProviderConfig.SECRET_CONFIG_PATHS

    def test_a_provider_declares_nothing_by_default(self) -> None:
        """A provider without a credential needs no opt-out."""
        assert BaseAuthProviderConfig.SECRET_CONFIG_PATHS == ()

    def test_every_installed_provider_declares_a_tuple(self) -> None:
        """A string would iterate per character and mask nothing recognisable."""
        for provider in AuthModule.get_installed_providers():
            assert isinstance(provider.PROVIDER_CONFIG_CLASS.SECRET_CONFIG_PATHS, tuple)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     MASKING                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMaskProviderConfig:
    """One provider's config."""

    def test_it_masks_the_declared_secret(self) -> None:
        """The whole point."""
        masked = mask_provider_config(LDAP, _ldap_config(_settings()))

        assert masked['connection_config']['password'] == MASKED_SECRET

    def test_it_leaves_everything_else_alone(self) -> None:
        """A hostname is not a credential."""
        masked = mask_provider_config(LDAP, _ldap_config(_settings()))

        assert masked['connection_config']['user'] == 'cn=reader'
        assert masked['server_config']['host'] == 'ldap.example.com'

    def test_a_provider_without_secrets_is_unchanged(self) -> None:
        """The local provider stores no credential."""
        config = {'active': True}

        assert mask_provider_config(LOCAL, config) == config

    def test_an_unknown_provider_is_left_alone(self) -> None:
        """A settings entry for a provider that is not installed declares nothing."""
        config = {'connection_config': {'password': STORED_PASSWORD}}

        assert mask_provider_config('NoSuchProvider', config) == config

    def test_it_does_not_mutate_its_input(self) -> None:
        """A masked copy must never become the document a later write reads from."""
        config = _ldap_config(_settings())

        mask_provider_config(LDAP, config)

        assert config['connection_config']['password'] == STORED_PASSWORD

    def test_a_config_missing_the_secret_path_is_not_given_one(self) -> None:
        """Masking only ever rewrites a value the document already carries."""
        masked = mask_provider_config(LDAP, {'active': True})

        assert masked == {'active': True}


class TestMaskAuthSettings:
    """The whole section."""

    def test_it_masks_the_bind_password(self) -> None:
        """What `GET /auth/settings` used to serve in cleartext."""
        assert _password(mask_auth_settings(_settings())) == MASKED_SECRET

    def test_the_sections_own_keys_are_carried_through(self) -> None:
        """The masked document has the shape the route always answered, one value shorter."""
        masked = mask_auth_settings(_settings())

        assert masked['_id'] == 'auth'
        assert masked['enable_external'] is True
        assert masked['token_lifetime'] == 1400

    def test_it_does_not_mutate_the_stored_document(self) -> None:
        """The route masks what it just read; that read may still be used for the write."""
        stored = _settings()

        mask_auth_settings(stored)

        assert _password(stored) == STORED_PASSWORD

    def test_a_document_without_providers_is_returned_as_is(self) -> None:
        """Defensive: the section is another module's shape and may be anything."""
        assert mask_auth_settings({'_id': 'auth'}) == {'_id': 'auth'}

    def test_a_malformed_providers_entry_is_skipped(self) -> None:
        """One bad entry must not stop the rest of the section being masked."""
        settings = _settings()
        settings['providers'].insert(0, 'not-a-dict')

        assert _password(mask_auth_settings(settings)) == MASKED_SECRET

    def test_the_masked_password_is_not_the_real_one(self) -> None:
        """The mask is a fixed sentinel, so it never leaks the secret's length either."""
        masked = _password(mask_auth_settings(_settings(password='a-much-longer-password')))

        assert masked == MASKED_SECRET


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    RESTORING                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRestoreMaskedSecrets:
    """The write half - without it, masking would break every LDAP login."""

    def test_the_mask_resolves_to_the_stored_secret(self) -> None:
        """The read-modify-write case, which is the normal way to use the update route."""
        stored = _settings()
        payload = mask_auth_settings(stored)

        assert _password(restore_masked_secrets(payload, stored)) == STORED_PASSWORD

    def test_an_edit_elsewhere_still_applies(self) -> None:
        """The client changed the host and left the credential masked."""
        stored = _settings()
        payload = mask_auth_settings(stored)
        _ldap_config(payload)['server_config']['host'] = 'ldap.internal'

        restored = restore_masked_secrets(payload, stored)

        assert _ldap_config(restored)['server_config']['host'] == 'ldap.internal'
        assert _password(restored) == STORED_PASSWORD

    def test_a_real_value_is_written_through(self) -> None:
        """A deliberate password change must not be swallowed by the restore."""
        stored = _settings()
        payload = mask_auth_settings(stored)
        _ldap_config(payload)['connection_config']['password'] = 'a-new-password'

        assert _password(restore_masked_secrets(payload, stored)) == 'a-new-password'

    def test_it_does_not_mutate_the_payload(self) -> None:
        """The caller's own object is not rewritten under it."""
        stored = _settings()
        payload = mask_auth_settings(stored)

        restore_masked_secrets(payload, stored)

        assert _password(payload) == MASKED_SECRET

    def test_no_stored_settings_falls_back_to_the_provider_default(self) -> None:
        """A first configuration from a masked read must not store the mask as the credential."""
        payload = mask_auth_settings(_settings())

        restored = restore_masked_secrets(payload, None)
        default = LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES['connection_config']['password']

        assert _password(restored) == default

    def test_a_stored_mask_falls_back_to_the_provider_default(self) -> None:
        """Defensive: a database that already holds the mask must not keep it forever."""
        stored = _settings(password=MASKED_SECRET)
        payload = mask_auth_settings(stored)

        restored = restore_masked_secrets(payload, stored)
        default = LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES['connection_config']['password']

        assert _password(restored) == default

    def test_an_unknown_provider_is_left_alone(self) -> None:
        """Nothing is declared secret for it, so nothing is resolved."""
        payload = {'providers': [{'class_name': 'NoSuchProvider', 'config': {'x': MASKED_SECRET}}]}

        assert restore_masked_secrets(deepcopy(payload), None) == payload

    def test_a_payload_without_providers_is_returned_as_is(self) -> None:
        """Defensive: the payload is client-supplied and may be anything."""
        assert restore_masked_secrets({'enable_external': False}, None) == {'enable_external': False}

    def test_a_malformed_entry_is_skipped(self) -> None:
        """One bad entry must not stop the rest of the payload resolving."""
        stored = _settings()
        payload = mask_auth_settings(stored)
        payload['providers'].insert(0, 'not-a-dict')

        assert _password(restore_masked_secrets(payload, stored)) == STORED_PASSWORD


class TestDefensiveShapes:
    """The settings section and the incoming payload are other people's documents."""

    def test_a_provider_entry_whose_config_is_not_a_dict_is_skipped_on_read(self) -> None:
        """A stored entry may be anything; masking must not raise over it."""
        settings = _settings()
        settings['providers'].append({'class_name': LDAP, 'config': 'not-a-dict'})

        assert _password(mask_auth_settings(settings)) == MASKED_SECRET

    def test_a_provider_entry_whose_config_is_not_a_dict_is_skipped_on_write(self) -> None:
        """The same on the way in, where the document is client-supplied."""
        stored = _settings()
        payload = mask_auth_settings(stored)
        payload['providers'].append({'class_name': LDAP, 'config': None})

        assert _password(restore_masked_secrets(payload, stored)) == STORED_PASSWORD

    def test_stored_settings_without_a_providers_list_resolve_to_the_default(self) -> None:
        """A stored section carrying no providers indexes to nothing."""
        payload = mask_auth_settings(_settings())

        restored = restore_masked_secrets(payload, {'_id': 'auth', 'providers': 'not-a-list'})
        default = LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES['connection_config']['password']

        assert _password(restored) == default

    def test_an_unknown_provider_has_no_default_to_fall_back_to(self) -> None:
        """`_default_config_value` answers None rather than raising for a provider that is gone."""
        payload = {'providers': [{'class_name': 'NoSuchProvider', 'config': {'password': MASKED_SECRET}}]}

        assert restore_masked_secrets(payload, None)['providers'][0]['config']['password'] == MASKED_SECRET

    def test_a_secret_path_whose_parent_is_missing_is_not_created(self) -> None:
        """Masking rewrites values; it never adds a key the document did not have."""
        masked = mask_provider_config(LDAP, {'connection_config': {'user': 'cn=reader'}})

        assert 'password' not in masked['connection_config']


class TestTheRoundTrip:
    """Mask, edit, restore - the sequence the two routes actually perform."""

    def test_a_full_round_trip_preserves_the_credential(self) -> None:
        """Read the settings, change something, write them back: the password survives untouched."""
        stored = _settings()

        served = mask_auth_settings(stored)
        served['token_lifetime'] = 3600
        written = restore_masked_secrets(served, stored)

        assert written['token_lifetime'] == 3600
        assert _password(written) == STORED_PASSWORD

    def test_the_credential_never_appears_in_a_served_document(self) -> None:
        """The property the whole module exists for."""
        assert STORED_PASSWORD not in str(mask_auth_settings(_settings()))
