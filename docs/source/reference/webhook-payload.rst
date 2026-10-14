###############
Webhook payload
###############

.. contents::
   :local:

The JSON body DataGerry POSTs to a webhook URL. How webhooks are set up and when they fire
is described in :doc:`../guides/webhooks`.

Request
=======

* Method ``POST``, header ``Content-Type: application/json``, UTF-8.
* Timeout 3 seconds; redirects are not followed.
* Any ``2xx`` response counts as delivered.

Body
====

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Key
     - Content
   * - ``event_time``
     - When the event was created (UTC), as ``{"$date": <epoch milliseconds>}``.
   * - ``operation``
     - ``CREATE``, ``UPDATE`` or ``DELETE``.
   * - ``object_before``
     - The object before the change. ``null`` on ``CREATE``.
   * - ``object_after``
     - The object after the change. ``null`` on ``DELETE``.
   * - ``changes``
     - On ``UPDATE`` of fields: ``{"old": [...], "new": [...]}`` with the field entries
       that differ — a changed field appears in both lists. When only the active state is
       toggled: ``{"state": true|false}``. ``null`` on ``CREATE`` and ``DELETE``.

Object
------

``object_before`` and ``object_after`` contain the stored object:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Key
     - Content
   * - ``public_id``
     - The object's ID.
   * - ``type_id``
     - The ID of its type.
   * - ``active``
     - Active flag.
   * - ``fields``
     - List of ``{"name", "value", "type"}`` entries, one per field. Uses field
       **names**; reference fields hold the referenced object's ID.
   * - ``multi_data_sections``
     - Entries of multi data sections.
   * - ``author_id`` / ``editor_id``
     - IDs of the creating and last editing user.
   * - ``creation_time`` / ``last_edit_time``
     - Timestamps, as ``{"$date": ...}``.
   * - ``version``
     - Object version.

Further keys of the object (for example ``special_type``) may be present.

Examples
========

Create (abbreviated):

.. code-block:: json

   {
     "event_time": {"$date": 1760438400000},
     "operation": "CREATE",
     "object_before": null,
     "object_after": {
       "public_id": 42,
       "type_id": 3,
       "active": true,
       "fields": [
         {"name": "hostname", "value": "web-01", "type": "text"},
         {"name": "ip", "value": "10.0.0.11", "type": "text"}
       ],
       "multi_data_sections": [],
       "author_id": 1,
       "version": "1.0.0"
     },
     "changes": null
   }

Update of one field (abbreviated):

.. code-block:: json

   {
     "event_time": {"$date": 1760438460000},
     "operation": "UPDATE",
     "object_before": {"public_id": 42, "fields": [{"name": "ip", "value": "10.0.0.11", "type": "text"}]},
     "object_after":  {"public_id": 42, "fields": [{"name": "ip", "value": "10.0.0.12", "type": "text"}]},
     "changes": {
       "old": [{"name": "ip", "value": "10.0.0.11", "type": "text"}],
       "new": [{"name": "ip", "value": "10.0.0.12", "type": "text"}]
     }
   }

Delete: ``operation`` is ``DELETE``, ``object_before`` holds the object as it was before
deletion, ``object_after`` and ``changes`` are ``null``.

Webhook log
===========

Each delivery attempt is stored as a log entry: the payload above plus ``webhook_id``,
``response_code`` (``0`` when no response arrived) and ``status`` (``true`` when
delivered). These fields are not part of the request body.
