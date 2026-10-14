#########################
Cloud or self-hosted
#########################

.. contents::
   :local:

DataGerry is the same application wherever it runs — the data model, the object views, IPAM, ISMS
and everything else in this documentation work identically. What differs is *who operates it*,
*how people sign in* and *how features are licensed*. This page explains those differences once;
the rest of the documentation marks the places where they matter with |cloud|, |selfhosted| or
|licensed|.

Three ways to run DataGerry
===========================

.. list-table::
   :header-rows: 1
   :widths: 22 26 26 26

   * -
     - DataGerry Cloud
     - Self-hosted Community
     - Self-hosted with license
   * - **What it is**
     - DataGerry as a service, operated by becon.
     - The open-source release on your own server.
     - The same installation, with a license file that unlocks the premium features.
   * - **You get it from**
     - A subscription in the `Service Portal <https://service.datagerry.com>`_ — a 14-day trial
       to start.
     - Packages or Docker images — see :doc:`../reference/downloads`.
     - Community installation + a license from the Service Portal, activated in
       :doc:`../guides/license-management`.
   * - **Who runs servers, updates and backups**
     - becon.
     - You.
     - You.
   * - **Premium features** (REST API, IPAM incl. racks and cabling, ISMS, Document Generator,
       Automations)
     - Included.
     - Not available — marked with a **Pro** badge in the interface.
     - Those included in your license tier.
   * - **Limits**
     - The number of objects (CIs) and active users depend on your plan.
     - None.
     - None.
   * - **Sign-in**
     - E-mail address and password, verified by the Service Portal.
     - User name and password, or LDAP.
     - User name and password, or LDAP.

A self-hosted installation shows its edition next to the logo (for example *Community Edition*).
A cloud instance shows its object quota in the top bar instead (*Objects 1234 / 10000*), and the
settings menu links to the Service Portal.

What is different in practice
=============================

Accounts and sign-in
--------------------

In the cloud, **people are managed in the Service Portal**, not in DataGerry. A portal
administrator invites a user, gives them the role *Admin* or *Cloud User* and assigns them to one
or more subscriptions. They then sign in to DataGerry with their e-mail address; if they belong to
several subscriptions, the login page lets them choose one. DataGerry creates its own user record
on the first sign-in, so the user list inside DataGerry is read-only for the most part — but
**groups, rights and ACLs are still managed in DataGerry**, exactly as on a self-hosted
installation. See :doc:`../cloud/users`.

On a self-hosted installation, users are created in DataGerry itself and sign in with a user name.
External authentication providers such as LDAP are available only here. See
:doc:`../guides/users-and-groups` and :doc:`../guides/authentication`.

Data separation
---------------

Each cloud **subscription is a separate DataGerry instance with its own database**. Nothing is
shared between subscriptions — use several subscriptions to keep, for example, a test and a
production CMDB apart, or to separate business units. One portal account can hold any number of
subscriptions.

A self-hosted installation has one database, named in ``cmdb.conf``. Run several installations
(or several databases) if you need the same separation.

Licensing
---------

In the cloud the subscription covers everything: all premium features are switched on, and
there is no license page. What your plan limits is the number of objects and active users.

On a self-hosted installation, DataGerry starts as the free **Community** edition with the core
CMDB. A license file — bound to the machine it is activated on — unlocks premium features
depending on its tier. If a license expires or cannot be verified, DataGerry falls back to
Community; nobody is locked out and no data is lost, only the premium features close again. See
:doc:`../guides/license-management`.

.. list-table:: Which areas are premium features
   :header-rows: 1
   :widths: 30 70

   * - Feature
     - Covers
   * - REST API
     - Access to the API from scripts and other systems (the web interface always works).
       See :doc:`../reference/rest-api`.
   * - IPAM
     - :doc:`../guides/ipam`, :doc:`../guides/racks` and :doc:`../guides/ports-and-cabling`.
   * - ISMS
     - Everything under :doc:`../concepts/isms`.
   * - Document Generator
     - :doc:`../guides/generate-documents`, including the AI assistant for document templates.
   * - Automations
     - :doc:`../guides/automations` (integrations powered by OpenCelium).

Everything else — types, objects, categories, locations, relations, section templates, CI
Explorer, reports, webhooks, imports and exports, the file explorer, users, rights and ACLs — is
part of every edition.

Operations
----------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Task
     - Cloud
     - Self-hosted
   * - Installation
     - None — create a subscription.
     - :doc:`../operations/install`
   * - Updates
     - Applied by becon; you always run the current release.
     - You install new releases; DataGerry migrates the database on start. See
       :doc:`../operations/updating`.
   * - Backups
     - Operated by becon.
     - Your responsibility — see :doc:`../operations/backup-and-restore`.
   * - Server configuration (``cmdb.conf``, ports, TLS)
     - Not applicable; *Settings → System* is hidden.
     - :doc:`../operations/configuration`
   * - REST API access
     - Basic authentication with your e-mail address **plus** an API key created in the Service
       Portal.
     - Basic authentication or a token with a DataGerry user; needs the REST API license feature.
   * - Automations (OpenCelium)
     - Provided; connectors are protected by a per-subscription master password set in the
       Service Portal.
     - You connect your own OpenCelium instance in ``cmdb.conf``.
   * - Support
     - Tickets in the Service Portal; the number of professional support cases depends on the plan.
     - Community: `GitHub <https://github.com/DATAGerry/DATAGerry>`_. Licensed: tickets in the
       Service Portal.

Which one should I choose?
==========================

Choose **the cloud** if you want to start immediately, do not want to run MongoDB and a web
server, and are comfortable with your CMDB data being hosted by becon.

Choose **self-hosted** if the data must stay inside your network (including air-gapped
environments), if you need LDAP sign-in, or if you want to change the code. Start with Community
and add a license when you need a premium feature.

Plans, prices and the exact limits of each tier are listed on
`datagerry.com <https://www.datagerry.com>`_.

Moving between editions
=======================

Because the data model is the same, you can move a CMDB with DataGerry's own export and import:
export your types first, then the objects of each type, and import them in the same order on the
other side. See :doc:`../guides/export-data` and :doc:`../guides/import-data`. Users, groups and
rights are not part of the export; set them up again on the target.

Where to go next
================

* :doc:`cloud-quickstart` — start a cloud trial.
* :doc:`self-hosted-quickstart` — run DataGerry on your own machine with Docker.
