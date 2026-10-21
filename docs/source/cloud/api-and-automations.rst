##########################
API keys and automations
##########################

.. contents::
   :local:

|cloud| Two things that work slightly differently in the cloud because several customers share the
infrastructure: access to the REST API needs an **API token** from the Service Portal, and
**Automations** need a **master password** per subscription. Both are managed under **Cloud
settings** in the Service Portal.

API tokens
==========

Scripts and other systems talk to DataGerry through its REST API (see
:doc:`../reference/rest-api`). In the cloud, a request authenticates with **two** things:

* HTTP Basic authentication with the **e-mail address and password** of a portal user who has access
  to the subscription, and
* an ``x-api-key`` header with an **API token** of that subscription. The token tells DataGerry which
  subscription — which database — the request is for.

A request with Basic credentials but without the header is refused with HTTP 401.

Create a token
--------------

1. In the Service Portal, open **Cloud settings → API tokens**.
2. Choose the subscription, give the token a name (for example the integration that uses it) and a
   scope — **Read & write** or **Read only**.
3. Copy the token right away. *This token is shown only once.*

The same page shows the **API endpoint** of your instance. Tokens can be revoked at any time;
a revoked token stops working immediately.

API tokens are not available on every plan, and not for an expired subscription. The portal says
so when you try to create one.

Example
-------

.. code-block:: console

   $ curl -u 'jane.doe@example.com:<password>' \
          -H 'x-api-key: <token>' \
          https://<api-endpoint>/objects/

Use a dedicated portal user for integrations rather than a person's account, so that the
integration keeps working when people leave.

Master passwords for automations
================================

:doc:`../guides/automations` connect DataGerry to other systems through OpenCelium. The
credentials of those systems — API keys, passwords — are stored with the connectors. In the cloud
they are protected by a **master password** that you set per subscription; without it, connector
passwords can be neither viewed nor changed.

1. In the Service Portal, open **Cloud settings → Master passwords**.
2. Click **Set** next to the subscription.
3. Enter a password of at least 12 characters (or **Generate password**), confirm it, and confirm the
   change with your own account password.

DataGerry asks for this master password when you work with connector credentials in the
Automations area. **Reset** removes it; it then has to be set again before connector passwords can
be managed.

.. admonition:: Cloud and self-hosted
   :class: edition

   On a self-hosted installation, DataGerry talks to your own OpenCelium instance, configured in
   the ``[OpenCelium]`` section of ``cmdb.conf`` (see :doc:`../operations/configuration`). The
   master password is then the one of that OpenCelium instance, not set in the Service Portal, and
   the OpenCelium license overview is shown in the Automations area.
