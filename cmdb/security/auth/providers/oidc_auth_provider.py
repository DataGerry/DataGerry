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
Implementation of OpenIDConnectAuthenticationProvider

Standards-compliant OpenID Connect provider (confidential client, Authorization Code Flow
with the code exchange on the backend). Discovery via .well-known/openid-configuration.
"""
from logging import Logger, getLogger
from datetime import datetime, timezone
from time import time
from urllib.parse import urlencode
import secrets

import requests
from authlib.jose import jwt, JsonWebKey
from authlib.jose.errors import JoseError

from cmdb.manager import (
    UsersManager,
    SecurityManager,
    OidcRequestManager,
)
from cmdb.database import MongoDatabaseManager

from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.base_authentication_provider import BaseAuthenticationProvider
from cmdb.security.auth.providers.oidc_auth_config import OpenIDConnectAuthenticationProviderConfig

from cmdb.errors.provider import (
    GroupMappingError,
    AuthenticationError,
    OIDCDiscoveryError,
    OIDCTokenValidationError,
    OIDCStateMismatchError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Per-worker caches (gunicorn sync workers each cache independently - acceptable, 1h TTL)
_DISCOVERY_CACHE: dict[str, tuple[float, dict]] = {}   # discovery_url -> (fetched_at, doc)
_JWKS_CACHE: dict[str, tuple[float, object]] = {}      # jwks_uri -> (fetched_at, key_set)

DISCOVERY_CACHE_TTL = 3600
HTTP_TIMEOUT = 10

# -------------------------------------------------------------------------------------------------------------------- #
#                                     OpenIDConnectAuthenticationProvider - CLASS                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class OpenIDConnectAuthenticationProvider(BaseAuthenticationProvider):
    """
    OpenID Connect authentication provider

    The password-based authenticate() always raises so the AuthModule login fallback loop
    can never be tricked into a password-less login. The interactive login uses the separate
    get_authorization_url()/handle_callback() flow driven by the OIDC REST routes.

    Extends: BaseAuthenticationProvider
    """
    PASSWORD_ABLE: bool = False
    EXTERNAL_PROVIDER: bool = True
    PROVIDER_CONFIG_CLASS = OpenIDConnectAuthenticationProviderConfig

    def __init__(self,
                 config: OpenIDConnectAuthenticationProviderConfig = None,
                 security_manager: SecurityManager = None,
                 users_manager: UsersManager = None,
                 database_manager: MongoDatabaseManager = None):
        """
        Initialize the OIDC provider. No network I/O happens here - the provider is
        instantiated by the login fallback loop and by GET /auth/providers/<class>.
        """
        super().__init__(config,
                         security_manager=security_manager,
                         users_manager=users_manager)
        self.database_manager = database_manager
        self.request_manager = OidcRequestManager(database_manager) if database_manager is not None else None

# ------------------------------------------------ DISCOVERY / JWKS ------------------------------------------------- #

    def _load_discovery_document(self, discovery_url: str, force: bool = False) -> dict:
        """
        Fetch (and cache) the .well-known/openid-configuration document
        """
        cached = _DISCOVERY_CACHE.get(discovery_url)
        if cached and not force and (time() - cached[0]) < DISCOVERY_CACHE_TTL:
            return cached[1]

        try:
            response = requests.get(discovery_url, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            document = response.json()
        except Exception as err:
            raise OIDCDiscoveryError(f"Could not load discovery document: {err}") from err

        _DISCOVERY_CACHE[discovery_url] = (time(), document)
        return document


    def _load_jwks(self, force: bool = False):
        """
        Fetch (and cache) the JWKS key set for id_token signature verification
        """
        jwks_uri = self.config.jwks_uri
        cached = _JWKS_CACHE.get(jwks_uri)
        if cached and not force and (time() - cached[0]) < DISCOVERY_CACHE_TTL:
            return cached[1]

        try:
            response = requests.get(jwks_uri, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            key_set = JsonWebKey.import_key_set(response.json())
        except Exception as err:
            raise OIDCTokenValidationError(f"Could not load JWKS: {err}") from err

        _JWKS_CACHE[jwks_uri] = (time(), key_set)
        return key_set


    def _ensure_endpoints(self) -> None:
        """
        Resolve endpoints. Explicitly configured non-empty values win; discovery only fills
        empty fields. If both the configured and discovered issuer are set but differ, the
        discovery is rejected (RP MUST verify the issuer).

        Raises:
            OIDCDiscoveryError: If discovery fails or the resolved config is incomplete
        """
        if self.config.discovery_url:
            document = self._load_discovery_document(self.config.discovery_url)

            discovered_issuer = (document.get('issuer') or '').strip()
            if self.config.issuer and discovered_issuer and self.config.issuer != discovered_issuer:
                raise OIDCDiscoveryError(
                    'Configured issuer does not match the discovered issuer')

            if not self.config.issuer:
                self.config.issuer = discovered_issuer
            if not self.config.authorization_endpoint:
                self.config.authorization_endpoint = (document.get('authorization_endpoint') or '').strip()
            if not self.config.token_endpoint:
                self.config.token_endpoint = (document.get('token_endpoint') or '').strip()
            if not self.config.userinfo_endpoint:
                self.config.userinfo_endpoint = (document.get('userinfo_endpoint') or '').strip()
            if not self.config.jwks_uri:
                self.config.jwks_uri = (document.get('jwks_uri') or '').strip()

        missing = [name for name in (
            'issuer', 'authorization_endpoint', 'token_endpoint', 'jwks_uri', 'client_id'
        ) if not getattr(self.config, name)]

        if missing:
            raise OIDCDiscoveryError(f"Incomplete OIDC configuration, missing: {', '.join(missing)}")

# --------------------------------------------------- AUTH FLOW ----------------------------------------------------- #

    def get_authorization_url(self, redirect_uri: str, spa_origin: str) -> str:
        """
        Build the IdP authorization URL and persist the request state/nonce/spa_origin

        Args:
            redirect_uri (str): The backend callback URL registered at the IdP
            spa_origin (str): The validated SPA origin to return the browser to

        Returns:
            str: The authorization endpoint URL with query parameters
        """
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)

        self.request_manager.store(state, nonce, spa_origin)

        params = {
            'response_type': 'code',
            'client_id': self.config.client_id,
            'redirect_uri': redirect_uri,
            'scope': ' '.join(self.config.scopes),
            'state': state,
            'nonce': nonce,
        }

        return f"{self.config.authorization_endpoint}?{urlencode(params)}"


    def handle_callback(self, request_args: dict, redirect_uri: str) -> tuple[CmdbUser, str]:
        """
        Handle the IdP redirect back to the backend callback

        Args:
            request_args (dict): The callback query parameters
            redirect_uri (str): The backend callback URL (must match the auth request)

        Returns:
            tuple[CmdbUser, str]: The provisioned/updated user and the stored SPA origin
        """
        if request_args.get('error'):
            description = request_args.get('error_description', '')
            raise AuthenticationError(f"IdP error: {request_args['error']} {description}".strip())

        code = request_args.get('code')
        state = request_args.get('state')

        if not code or not state:
            raise AuthenticationError('Missing code or state in OIDC callback')

        stored = self.request_manager.consume(state)
        if not stored:
            raise OIDCStateMismatchError('Unknown or already consumed OIDC state')

        tokens = self._exchange_code_for_tokens(code, redirect_uri)
        id_claims = self._validate_id_token(tokens['id_token'], stored['nonce'])
        userinfo = self._fetch_userinfo(tokens.get('access_token'))

        data = self._extract_claims(id_claims, userinfo)
        group_id = self._map_oidc_groups(data['raw_groups'])

        user = self.login_or_provision(data, group_id)
        return user, stored['spa_origin']


    def _exchange_code_for_tokens(self, code: str, redirect_uri: str) -> dict:
        """
        Exchange the authorization code for tokens at the token endpoint (backend-only secret)
        """
        payload = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
        }
        request_kwargs = {'data': payload, 'timeout': HTTP_TIMEOUT}

        if self.config.token_endpoint_auth_method == 'client_secret_post':
            payload['client_id'] = self.config.client_id
            payload['client_secret'] = self.config.client_secret
        else:  # client_secret_basic (spec default)
            request_kwargs['auth'] = (self.config.client_id, self.config.client_secret)

        try:
            response = requests.post(self.config.token_endpoint, **request_kwargs)
            tokens = response.json()
        except Exception as err:
            raise AuthenticationError(f"Token exchange request failed: {err}") from err

        if response.status_code != 200 or tokens.get('error'):
            raise AuthenticationError(
                f"Token exchange failed: {tokens.get('error', response.status_code)}")

        if not tokens.get('id_token'):
            raise AuthenticationError('Token endpoint response did not contain an id_token')

        return tokens


    def _validate_id_token(self, id_token: str, nonce: str) -> dict:
        """
        Validate the ID token: JWKS signature, issuer, audience/azp, expiry (leeway 120s), nonce

        Raises:
            OIDCTokenValidationError: If any validation step fails
        """
        claims_options = {
            'iss': {'essential': True, 'value': self.config.issuer},
            'exp': {'essential': True},
            'aud': {'essential': True},
        }

        try:
            claims = jwt.decode(id_token, self._load_jwks(), claims_options=claims_options)
            claims.validate(leeway=120)
        except JoseError:
            # Possible key rotation / kid miss: force one JWKS refetch then retry
            try:
                claims = jwt.decode(id_token, self._load_jwks(force=True), claims_options=claims_options)
                claims.validate(leeway=120)
            except JoseError as err:
                raise OIDCTokenValidationError(f"ID token validation failed: {err}") from err

        aud = claims.get('aud')
        aud_list = aud if isinstance(aud, list) else [aud]

        if self.config.client_id not in aud_list:
            raise OIDCTokenValidationError('ID token audience does not contain the client_id')

        if len(aud_list) > 1 and claims.get('azp') != self.config.client_id:
            raise OIDCTokenValidationError('Multi-audience ID token azp does not match the client_id')

        if claims.get('nonce') != nonce:
            raise OIDCTokenValidationError('ID token nonce mismatch')

        return dict(claims)


    def _fetch_userinfo(self, access_token: str) -> dict | None:
        """
        Fetch the userinfo endpoint if configured. Returns None on failure (logged).
        """
        if not self.config.userinfo_endpoint or not access_token:
            return None

        try:
            response = requests.get(
                self.config.userinfo_endpoint,
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except Exception as err:
            LOGGER.warning("[OIDC] Could not fetch userinfo: %s", err)
            return None

# ---------------------------------------------- CLAIMS / PROVISIONING ---------------------------------------------- #

    @staticmethod
    def _get_nested_claim(claims: dict, path: str):
        """
        Traverse a dotted claim path (e.g. resource_access.myclient.roles). None if missing.
        """
        current = claims
        for part in path.split('.'):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]

        return current


    def _extract_claims(self, id_token_claims: dict, userinfo_claims: dict) -> dict:
        """
        Resolve the 5 configured claim paths from the merged claim set (userinfo wins)
        """
        merged = {**id_token_claims, **(userinfo_claims or {})}
        mapping = self.config.claims_mapping

        user_name = self._get_nested_claim(merged, mapping['user_name'])
        if not user_name:
            user_name = merged.get('sub')

        if not user_name:
            raise AuthenticationError('Could not resolve a username from OIDC claims')

        user_name = str(user_name).strip().lower()
        if not user_name:
            raise AuthenticationError('Resolved OIDC username is empty')

        raw_groups = self._get_nested_claim(merged, mapping['groups'])
        if raw_groups is None:
            raw_groups = []
        elif isinstance(raw_groups, str):
            raw_groups = [raw_groups]
        else:
            raw_groups = list(raw_groups)

        return {
            'user_name': user_name,
            'email': self._get_nested_claim(merged, mapping['email']),
            'first_name': self._get_nested_claim(merged, mapping['first_name']),
            'last_name': self._get_nested_claim(merged, mapping['last_name']),
            'raw_groups': raw_groups,
        }


    def _map_oidc_groups(self, raw_groups: list) -> int:
        """
        Map OIDC group/role claim values to an internal group ID.

        Mirrors LdapAuthenticationProvider.__map_group: mapping inactive/empty -> default_group;
        first matching entry wins; unmapped values are skipped; fallback default_group.
        """
        default_group = self.config.default_group
        mapping = self.config.groups_mapping

        if not mapping.get('active') or not mapping.get('mapping') or not raw_groups:
            return default_group

        for group_value in raw_groups:
            try:
                return self.config.mapping(group_value)
            except GroupMappingError:
                continue

        return default_group


    def login_or_provision(self, user_data: dict, group_id: int) -> CmdbUser:
        """
        Find the OIDC user and update mapped attributes, or JIT-provision a new one

        Args:
            user_data (dict): Resolved claim values (user_name/email/first_name/last_name)
            group_id (int): The mapped internal group ID

        Raises:
            AuthenticationError: If provisioning is disabled and the user does not exist

        Returns:
            CmdbUser: The persisted user
        """
        group_mapping_active = self.config.groups_mapping.get('active', False)
        user_instance: CmdbUser = self.users_manager.get_user_by({'user_name': user_data['user_name']})

        if user_instance:
            if user_instance.authenticator != self.get_name():
                LOGGER.warning(
                    "[OIDC] User '%s' exists with authenticator '%s'; returning existing user",
                    user_data['user_name'], user_instance.authenticator)
                return user_instance

            changed = False

            if group_mapping_active and user_instance.group_id != group_id:
                user_instance.group_id = int(group_id)
                changed = True

            for attribute in ('email', 'first_name', 'last_name'):
                value = user_data.get(attribute)
                if value and getattr(user_instance, attribute) != value:
                    setattr(user_instance, attribute, value)
                    changed = True

            if changed:
                self.users_manager.update_user(user_instance.public_id, user_instance)
                user_instance = self.users_manager.get_user_by({'user_name': user_data['user_name']})

            return user_instance

        if not self.config.jit_provisioning:
            raise AuthenticationError(
                f"JIT provisioning disabled and user '{user_data['user_name']}' does not exist")

        new_user_data = {
            'user_name': user_data['user_name'],
            'email': user_data.get('email'),
            'first_name': user_data.get('first_name'),
            'last_name': user_data.get('last_name'),
            'active': True,
            'group_id': int(group_id),
            'registration_time': datetime.now(timezone.utc),
            'authenticator': self.get_name(),
        }

        user_id = self.users_manager.insert_user(new_user_data)
        user_instance = self.users_manager.get_user(user_id)

        if not user_instance:
            raise AuthenticationError('Could not provision OIDC user')

        return user_instance


    def authenticate(self, user_name: str, password: str) -> CmdbUser:
        """
        OIDC does not support password authentication. Always raises so the AuthModule login
        fallback loop can never be tricked into a password-less login (no auth bypass).
        """
        raise AuthenticationError('OIDC does not support password authentication')


    def is_active(self) -> bool:
        """
        Check if the OIDC provider is active
        """
        return self.config.active
