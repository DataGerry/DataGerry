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
Masking of the credentials stored in the `auth` settings section

The authentication settings hold one secret: the LDAP **bind password**, the credential the search
bind uses. Until 2026-09-16 every read served it in cleartext - `GET /auth/settings`,
`GET /auth/providers/<class>` and the body the update route echoes back - because the settings are
serialised verbatim and nothing distinguished a credential from a hostname.

**Masking a value on read is only half a rule.** The update route takes the WHOLE section
(`require_complete=True`, because an absent key and a reset to the default are indistinguishable), so
any client that reads the settings, changes one field and sends the object back would post the mask
where the password used to be - and write the mask as the new bind password, breaking every LDAP
login. Read-modify-write is the normal way to use that route, not a frontend quirk, so the two halves
have to ship together:

* `mask_auth_settings` / `mask_provider_config` replace a secret with `MASKED_SECRET` on the way out
* `restore_masked_secrets` puts the stored value back on the way in, wherever the payload sends the
  mask unchanged

**Which values are secret is declared by the provider that owns them** - `SECRET_CONFIG_PATHS` on the
provider's config class - rather than listed here. A new provider carrying a credential registers it
by declaring it, which is what keeps this module from becoming a hand-maintained registry that can
silently fall behind (the shape `G14` records elsewhere).

Everything here works on plain documents and returns copies: the callers hand in a settings dict or a
config dict and get a new one back, so a masked payload can never be the object a later write reads
its stored values from.
"""
from copy import deepcopy
from logging import Logger, getLogger
from typing import Any

from cmdb.models.security_models.auth_settings_constants import AuthSettingsKey, ProviderEntryKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

__all__: list[str] = [
    'MASKED_SECRET',
    'mask_auth_settings',
    'mask_provider_config',
    'restore_masked_secrets',
]

# What a masked credential reads as on the wire. A fixed, recognisable sentinel rather than a run of
# asterisks of the secret's length, which would leak the length
MASKED_SECRET: str = '********'


def _config_class(provider_class_name: Any) -> Any:
    """
    Resolves an installed provider's config class by the class name a settings entry carries

    Args:
        provider_class_name (Any): Class name of the provider, as stored in a settings entry

    Returns:
        Any: The provider's config class, or None when no such provider is installed
    """
    # Imported inside the function: AuthModule imports this module's callers, and the provider
    # registry is what this lookup needs - resolving it at call time keeps the import one-directional
    # pylint: disable=import-outside-toplevel
    from cmdb.security.auth.auth_module import AuthModule

    if not AuthModule.provider_exists(provider_name=provider_class_name):
        return None

    return AuthModule.get_provider_class(provider_class_name).PROVIDER_CONFIG_CLASS


def _secret_paths(config_class: Any) -> tuple[tuple[str, ...], ...]:
    """
    Reads the secret paths a provider's config class declares

    Args:
        config_class (Any): The provider's config class, or None when it is not installed

    Returns:
        tuple[tuple[str, ...], ...]: The declared paths, empty when there is no class or it declares
            none
    """
    if config_class is None:
        return ()

    return config_class.SECRET_CONFIG_PATHS


def _default_config_value(config_class: Any, path: tuple[str, ...]) -> Any:
    """
    Reads a provider's default value at one config path

    The fallback when a payload sends the mask for a secret the stored settings do not carry - a
    provider configured for the first time through a masked read, which would otherwise store the
    mask itself as the credential

    Args:
        config_class (Any): The provider's config class
        path (tuple[str, ...]): The config path to read

    Returns:
        Any: The default value, or None when the path is not in the defaults
    """
    return _read_path(config_class.DEFAULT_CONFIG_VALUES, path)


def _read_path(document: Any, path: tuple[str, ...]) -> Any:
    """
    Reads the value at a nested path, or None when any step is missing

    Args:
        document (Any): The document to read from
        path (tuple[str, ...]): The keys to walk, outermost first

    Returns:
        Any: The value at the path, or None when it is not present
    """
    current: Any = document

    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None

        current = current[key]

    return current


def _write_path(document: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """
    Writes a value at a nested path, in place, creating nothing that is not already there

    A path whose parent is missing is skipped rather than created: this only ever rewrites a value the
    document already carries, so a config that does not use a secret is left exactly as it was

    Args:
        document (dict[str, Any]): The document to edit in place
        path (tuple[str, ...]): The keys to walk, outermost first
        value (Any): The value to write at the path
    """
    current: Any = document

    for key in path[:-1]:
        if not isinstance(current, dict) or key not in current:
            return

        current = current[key]

    if isinstance(current, dict) and path[-1] in current:
        current[path[-1]] = value


def mask_provider_config(provider_class_name: str, config: dict[str, Any]) -> dict[str, Any]:
    """
    Returns a copy of one provider's config with its declared secrets masked

    Args:
        provider_class_name (str): Class name of the provider the config belongs to
        config (dict[str, Any]): The provider's stored config values

    Returns:
        dict[str, Any]: A copy carrying MASKED_SECRET wherever the provider declares a secret
    """
    masked: dict[str, Any] = deepcopy(config)

    for path in _secret_paths(_config_class(provider_class_name)):
        _write_path(masked, path, MASKED_SECRET)

    return masked


def mask_auth_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """
    Returns a copy of the whole `auth` section with every provider's secrets masked

    The section's own keys (`_id`, `enable_external`, `token_lifetime`) are carried through unchanged,
    so the masked document has exactly the shape the route answered before - one value shorter

    Args:
        settings (dict[str, Any]): The stored auth settings document

    Returns:
        dict[str, Any]: A copy safe to serve to a client
    """
    masked: dict[str, Any] = deepcopy(settings)
    providers: Any = masked.get(AuthSettingsKey.PROVIDERS.value)

    if not isinstance(providers, list):
        return masked

    for entry in providers:
        if not isinstance(entry, dict):
            continue

        config: Any = entry.get(ProviderEntryKey.CONFIG.value)

        if not isinstance(config, dict):
            continue

        entry[ProviderEntryKey.CONFIG.value] = mask_provider_config(
            entry.get(ProviderEntryKey.CLASS_NAME.value), config,
        )

    return masked


def restore_masked_secrets(
        new_settings: dict[str, Any],
        stored_settings: dict[str, Any] | None) -> dict[str, Any]:
    """
    Returns a copy of an incoming settings payload with masked secrets replaced by the stored ones

    The write half of the rule. A payload that sends MASKED_SECRET where a credential belongs is
    saying "leave it as it was", which is what a read-modify-write client produces after a masked
    read. A payload carrying anything else at that path is a deliberate change and is written through.

    When the stored settings hold no value at that path - a provider configured for the first time
    from a masked read - the provider's default is used instead, so the mask itself can never become
    the credential.

    Args:
        new_settings (dict[str, Any]): The incoming payload
        stored_settings (dict[str, Any] | None): The currently stored auth settings, or None

    Returns:
        dict[str, Any]: A copy with every masked secret resolved to a real value
    """
    restored: dict[str, Any] = deepcopy(new_settings)
    providers: Any = restored.get(AuthSettingsKey.PROVIDERS.value)

    if not isinstance(providers, list):
        return restored

    stored_by_name: dict[Any, dict[str, Any]] = _stored_configs_by_provider(stored_settings)

    for entry in providers:
        if not isinstance(entry, dict):
            continue

        config: Any = entry.get(ProviderEntryKey.CONFIG.value)

        if not isinstance(config, dict):
            continue

        class_name: Any = entry.get(ProviderEntryKey.CLASS_NAME.value)
        config_class: Any = _config_class(class_name)

        for path in _secret_paths(config_class):
            if _read_path(config, path) != MASKED_SECRET:
                continue

            stored_value: Any = _read_path(stored_by_name.get(class_name, {}), path)

            if stored_value is None or stored_value == MASKED_SECRET:
                stored_value = _default_config_value(config_class, path)

                LOGGER.warning(
                    '[restore_masked_secrets] No stored secret for %s at %s - using the provider default',
                    class_name, '.'.join(path),
                )

            _write_path(config, path, stored_value)

    return restored


def _stored_configs_by_provider(stored_settings: dict[str, Any] | None) -> dict[Any, dict[str, Any]]:
    """
    Indexes the stored provider configs by class name

    Args:
        stored_settings (dict[str, Any] | None): The currently stored auth settings, or None

    Returns:
        dict[Any, dict[str, Any]]: Class name to stored config; empty when nothing is stored
    """
    if not isinstance(stored_settings, dict):
        return {}

    providers: Any = stored_settings.get(AuthSettingsKey.PROVIDERS.value)

    if not isinstance(providers, list):
        return {}

    return {
        entry.get(ProviderEntryKey.CLASS_NAME.value): entry.get(ProviderEntryKey.CONFIG.value, {})
        for entry in providers
        if isinstance(entry, dict) and isinstance(entry.get(ProviderEntryKey.CONFIG.value), dict)
    }
