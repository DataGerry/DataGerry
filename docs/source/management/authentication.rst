**************
Authentication
**************

.. admonition:: Cloud Version

    See details in Service Portal documentation how authentification is implemented.

DataGerry uses a hybrid authentication method for issuing access tokens. These tokens can be used to
authenticate against the Rest API.

When logging in, the user is searched in the database using his user name. If a user is found, his stored provider is
requested. Depending on the provider implementation, an authentication is now attempted using the submitted password.
If the authentication is successful, the provider returns a user instance which is used to generate a valid access
token. If the authentication fails, the login is aborted.

If no user is found in the database, each provider is called according to the provider order.
If a successful authentication takes place, a new user is created with the submitted login data and
stored in a predefined group. If no provider confirms a successful request, the login is aborted.

| 

=======================================================================================================================

| 

Access Token
============

Authentication uses JSON Web Tokens as specified in RFC 7519 for identity verification.
The `Issuer`, `Issued at`, `Expiration time` and the custom `DataGerry` claims are used.

.. warning::
    (Only OnPremise) The asymmetrical RSA key for signing the tokens is stored in the database under **settings.conf**.

| 

=======================================================================================================================

| 

Providers
=========

Providers are authenticators who can locate a user in the system using a username and password.
They are divided into internal and external providers. In the case of internal providers,
the system searches for the user in the database.
External providers identify the user in an external third party system.

Available providers are:

1. **LocalAuthenticationProvider** - Searches for users in the database by username and compares the password with
the stored SHA256 HMAC.
2. **LdapAuthenticationProvider** - Using the user name, tries to find a user in the directory service and authenticate
with the password.
3. **OpenIDConnectAuthenticationProvider** - Delegates authentication to an external OpenID Connect Identity Provider
(Keycloak, Entra ID, Okta, ...) using the standard Authorization Code Flow.

.. note::
    The order in which the providers are queried is determined by the installation order of the
    providers in the authentication module. A special factor here is that the local provider is always in
    first place.

| 

LDAP group mapping
------------------
The LDAP authentication provider offers the possibility to create a mapping to the
DataGerry groups based on the LDAP groups. Since DataGerry does not allow users to be assigned to multiple groups,
the possibility of multiple LDAP groups must be reduced.

The mapping of groups must first be activated manually. If mapping is disabled, all LDAP users are assigned to the
default group. This is also the case if the mapping is deactivated afterwards.

.. image:: img/authentification/auth_provider_ldap_default.png
    :width: 600

After activating the mapping, a search filter can be created for selecting the groups at login.
In the configuration interface you can now assign a group name of the LDAP to a DataGerry group.
Here an LDAP group can be assigned exactly to one DataGerry group, however different LDAP groups can be assigned to
the same DataGerry group.

.. image:: img/authentification/auth_provider_ldap_mapping.png
    :width: 600

The order of the mappings is important. If a LDAP user appears in several mappings,
the first successful mapping is taken. If the user cannot be found in any mapping, he will be moved to the
default group.

|

=======================================================================================================================

|

OpenID Connect (OIDC)
=====================

The OpenID Connect provider lets users sign in through an external Identity Provider (IdP). DataGerry acts as a
**confidential client** and performs the Authorization Code exchange on the backend, so the ``client_secret`` never
reaches the browser. The provider is only available for **on-premise (local)** installations; the cloud version uses
the Service Portal SSO instead.

.. note::
    Always use ``https`` endpoints for the IdP in production. The token exchange and the DataGerry access token both
    depend on transport security.

Registering DataGerry at the IdP
--------------------------------
Create a confidential client at your IdP and register the backend callback URL as an allowed redirect URI:

    ``https://<your-datagerry-host>/rest/auth/oidc/callback``

For a local development setup (SPA served by ``ng serve`` on port 4200, backend on port 4000) the redirect URI is
``http://localhost:4000/rest/auth/oidc/callback``.

Configuration
-------------
The provider is configured under *Settings → Authentication*. The recommended path is to set the **Discovery URL**
(``.well-known/openid-configuration``) and press **Discover** - the issuer and all endpoints are then resolved
server-side. Explicitly configured endpoint values always take precedence; discovery only fills empty fields.

Required values:

* **Discovery URL** (or the individual endpoints: authorization, token, JWKS) and the **Issuer**
* **Client ID** and **Client Secret**
* **Scopes** (``openid`` is always requested)

Optional values:

* **Token Endpoint Auth Method** - ``client_secret_basic`` (default) or ``client_secret_post``
* **Redirect URI Override** - only needed behind a reverse proxy / TLS offloader
* **Frontend Origins** - allowlist of additional SPA origins (e.g. ``http://localhost:4200`` for dev). The backend's
  own origin is always allowed. This prevents open redirects.
* **Auto Redirect** - skip the login form and send users straight to the IdP. The local login form always stays
  reachable via ``/auth?local=true`` (and after any error), so there is no redirect trap.
* **JIT Provisioning** - automatically create a DataGerry user on first successful login.

Claims mapping
--------------
The user attributes are read from the OIDC claims. All five mappings are editable and support dotted paths
(e.g. ``resource_access.myclient.roles``). Claims from the ``userinfo`` endpoint take precedence over the ID token.
Defaults: ``user_name`` → ``preferred_username`` (falls back to ``sub``), ``email`` → ``email``,
``first_name`` → ``given_name``, ``last_name`` → ``family_name``, ``groups`` → ``groups``.

OIDC group mapping
------------------
Like LDAP, OIDC group values (from the configured groups claim) can be mapped to DataGerry groups. The mapping must be
activated explicitly; while inactive, every OIDC user is assigned to the default group. The first matching mapping
entry wins; unmapped users fall back to the default group.

.. note::
    Group claims are only read from the ID token and the userinfo endpoint - access tokens are treated as opaque per
    the OIDC specification. Configure your IdP to include the groups/roles claim in the ID token or userinfo response.

Security
--------
The ``state`` parameter (256-bit, single-use) protects against CSRF, and the ``nonce`` (stored server-side and verified
against the ID token) protects against replay. ID tokens are validated for JWKS signature, issuer, audience/``azp``
and expiry. The DataGerry access token is handed to the SPA in the URL fragment (never a query string) and stripped
from the browser history immediately.
