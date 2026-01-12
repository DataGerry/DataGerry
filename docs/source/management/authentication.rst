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
3. **EntraIdAuthenticationProvider** - Authenticates users via Microsoft Entra ID (Azure AD) using OAuth2 
authorization code flow. Supports automatic user creation and group mapping.

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

Microsoft Entra ID Authentication
---------------------------------

DataGerry supports authentication via Microsoft Entra ID (formerly Azure Active Directory) using the OAuth2 
authorization code flow. This allows users to sign in with their Microsoft corporate accounts.

**Prerequisites**

Before configuring Entra ID authentication in DataGerry, you need to create an App Registration in the 
Azure Portal:

1. Go to Azure Portal → Microsoft Entra ID → App registrations
2. Click "New registration"
3. Enter a name (e.g., "DataGerry")
4. Select supported account types
5. Add a Redirect URI: ``https://your-datagerry-server/rest/auth/entraid/callback``
6. After creation, note the **Application (client) ID** and **Directory (tenant) ID**
7. Go to Certificates & secrets → New client secret → Copy the **Value** (shown only once)

**Configuration**

In DataGerry, navigate to Settings → Authentication → Config. Enable the EntraIdAuthenticationProvider and 
configure the following fields:

- **Tenant ID**: Your Azure AD tenant ID (Directory ID)
- **Client ID**: Application (client) ID from the App Registration
- **Client Secret**: The secret value you created in Azure
- **Redirect URI**: Must match exactly what you configured in Azure (e.g., ``https://your-datagerry-server/rest/auth/entraid/callback``)

.. note::
    The Redirect URI must match exactly between Azure and DataGerry configuration, including the protocol (https).

**Just-In-Time User Provisioning**

When a user signs in via Microsoft for the first time, DataGerry automatically creates a local user account. 
The user is assigned to the configured default group. On subsequent logins, the user's group membership can be 
automatically updated based on group mapping rules.

**Group Mapping**

Similar to LDAP, you can map Azure AD groups to DataGerry groups. Enable group mapping and define which 
Azure AD group names should map to which DataGerry groups. Users are assigned to the first matching group, 
or the default group if no mapping matches.

.. note::
    To receive group claims from Azure AD, you must configure the App Registration to include group claims 
    in the ID token (Azure Portal → App Registration → Token configuration → Add groups claim).

