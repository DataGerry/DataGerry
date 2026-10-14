###############
Troubleshooting
###############

.. contents::
   :local:

Problems sorted by what you see. The first section applies to every edition; the rest to
self-hosted installations. Cloud customers who cannot solve a problem here open a ticket under
**Support** in the Service Portal.

In the web interface
====================

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Symptom
     - Cause and fix
   * - *User has not the required right base.…*
     - Your group lacks the named right. Since 3.3 more areas are guarded by rights. An
       administrator adds the right to the group — see :doc:`../reference/rights`.
   * - A menu entry or button is missing.
     - Same cause: menus and actions you have no right for are hidden. Premium features without a
       license are shown with a **Pro** badge instead.
   * - |cloud| *The maximum amout of ConfigItems is reached!*
     - The subscription's object limit is reached. Delete objects you no longer need or move to a
       larger plan — see :doc:`../cloud/subscriptions`.
   * - |cloud| The sign-in page asks for an e-mail address, not a user name.
     - That is how cloud sign-in works; use your Service Portal e-mail address and password.
   * - |cloud| You land in the wrong CMDB after sign-in.
     - Your account has access to several subscriptions. Sign out and choose the right one under
       **Select a subscription**.
   * - A type cannot be deleted.
     - It still has objects, or a report uses it. Delete or move those first.
   * - An import reports invalid rows.
     - See the validation messages in the wizard and :doc:`../guides/import-data`.

REST API
========

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Symptom
     - Cause and fix
   * - |cloud| HTTP 401 *In cloud mode HTTP Basic credentials are accepted only together with an
       x-api-key header!*
     - Send the API token from the Service Portal in an ``x-api-key`` header — see
       :doc:`../cloud/api-and-automations`.
   * - |selfhosted| HTTP 403 naming the REST API feature.
     - The installation has no license with the REST API feature. See
       :doc:`../guides/license-management`.
   * - HTTP 403 *No permission for this action!* or a missing right.
     - The user the request authenticates as lacks the right. Use a dedicated integration user with
       a suitable group.

Self-hosted installations
=========================

Where the logs are
------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Installation
     - Command
   * - Packages
     - ``journalctl -u datagerry -f``
   * - Docker
     - ``docker logs -f dg-backend`` (also ``dg-frontend``, ``dg-mongodb``)

DataGerry additionally writes rotating log files — one per process plus ``webserver.access.log``
and ``webserver.error.log`` — to a ``logs`` directory next to its installation, rotated at 10 MB
with four old files kept. For more detail, start DataGerry with ``--debug`` (``-d``).

Common problems
---------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Symptom
     - Cause and fix
   * - The page does not load at all.
     - DataGerry is not running or not reachable. Check ``systemctl status datagerry``, then that
       port 4000 (or your proxy port) is open in the firewall.
   * - DataGerry stops right after starting; the log mentions the database.
     - MongoDB is not running or not reachable with the values in ``[Database]``. Check
       ``systemctl status mongod`` and :doc:`configuration`.
   * - The interface loads, but every action fails with network errors.
     - ``app-config.json`` points to the wrong backend address or port. ``apiPort`` must match
       ``[WebServer] port``, and ``protocol`` must match TLS. See :doc:`configuration`.
   * - HTTPS does not start.
     - The ``datagerry`` user cannot read the certificate or key, or cannot enter the ``private``
       directory. See :doc:`install`.
   * - After an update or moving the server, premium features are locked again and the license page
       says *License not recognized on this machine*.
     - The machine fingerprint changed (new host, recreated container). Generate a new activation
       request and have the license re-issued — see :doc:`../guides/license-management`.
   * - The Document Generator's AI Assistant fails with an error from OpenAI.
     - ``[ChatGPT] api_key`` is missing, wrong or still the shipped placeholder. See
       :doc:`configuration`.
   * - Automations cannot reach OpenCelium.
     - Check the ``[OpenCelium]`` section in ``cmdb.conf`` and that the OpenCelium server is
       reachable from the DataGerry host.
   * - The first start after an update takes long.
     - DataGerry migrates the database before it accepts requests. Follow the log; do not restart it
       in the middle.
