########
REST API
########

.. contents::
   :local:

Everything the web interface does goes through DataGerry's REST API, and the same API is open to
your scripts and integrations. |licensed| On a self-hosted installation, external access needs a
license with the REST API feature; in the cloud it needs an API token from the Service Portal.

Endpoint documentation
======================

The full, generated description of every endpoint, in four viewers — pick the one you prefer:

* `Swagger UI <../swagger.html>`_
* `ReDoc <../redoc.html>`_
* `Stoplight Elements <../spotlight.html>`_
* `RapiDoc <../rapidoc.html>`_

Base URL
========

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Edition
     - Base URL
   * - |selfhosted|
     - ``https://<your-host>/rest/`` — for example ``https://cmdb.example.com/rest/objects/``.
   * - |cloud|
     - The **API endpoint** shown under **Cloud settings → API tokens** in the Service Portal.

Authentication
==============

Integrations authenticate every request with **HTTP Basic** authentication.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Edition
     - Credentials
   * - |selfhosted|
     - User name and password of a DataGerry user. The request has that user's rights and ACLs.
       Without the REST API license feature, the request is refused with HTTP 403.
   * - |cloud|
     - E-mail address and password of a portal user with access to the subscription, **plus** the
       header ``x-api-key: <token>`` with an API token of that subscription. See
       :doc:`../cloud/api-and-automations`.

Self-hosted:

.. code-block:: console

   $ curl -u 'api-user:<password>' https://cmdb.example.com/rest/objects/

Cloud:

.. code-block:: console

   $ curl -u 'jane.doe@example.com:<password>' \
          -H 'x-api-key: <token>' \
          https://<api-endpoint>/objects/

Create a dedicated user for each integration and give it a group with only the rights it needs —
see :doc:`rights`.

Common conventions
==================

* Requests and responses are JSON.
* Objects, types, categories and most other entities are addressed by their numeric ``public_id``,
  for example ``GET /rest/objects/42``.
* List endpoints are paginated.
* Required fields of a type are enforced on create and update; a missing value is answered with
  HTTP 400 *(3.3)*.
* Rights apply exactly as in the web interface: a request for something the user may not see is
  answered with HTTP 403.
