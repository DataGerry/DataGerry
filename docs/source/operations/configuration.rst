#############
Configuration
#############

.. contents::
   :local:

|selfhosted| Most of DataGerry's settings are stored in its database and changed in the web
interface. A few things have to be known before the database can be reached — the database
connection itself, the port, TLS, and connections to external services. They live in two files.
In the cloud, none of this is accessible; becon operates it.

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - File
     - Packages
     - Docker
   * - ``cmdb.conf`` — backend
     - ``/etc/datagerry/cmdb.conf``
     - ``/opt/DataGerry-docker/conf/cmdb.conf``
   * - ``app-config.json`` — frontend
     - ``/etc/datagerry/app-config.json``
     - ``/opt/DataGerry-docker/conf/app-config.json``

Restart DataGerry after every change: ``systemctl restart datagerry``, or
``docker compose restart`` for Docker.

cmdb.conf
=========

An INI file. The shipped default:

.. literalinclude:: ../../../etc/cmdb.conf
   :language: ini

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Section
     - Key
     - Meaning
   * - ``[Database]``
     - ``host``, ``port``
     - Where MongoDB runs. Default ``127.0.0.1:27017``.
   * -
     - ``database_name``
     - The MongoDB database DataGerry uses. Default ``cmdb``.
   * - ``[WebServer]``
     - ``host``, ``port``
     - The address and port DataGerry listens on. Default ``0.0.0.0:4000``. Behind a reverse proxy
       on the same host, ``127.0.0.1`` is enough.
   * -
     - ``ssl``, ``certfile``, ``keyfile``
     - Serve HTTPS directly. The ``datagerry`` user needs read access to both files. See
       :doc:`install`.
   * - ``[OpenCelium]``
     - ``host``, ``port``, ``protocol``, ``email``, ``user``, ``password``
     - The OpenCelium server that runs :doc:`../guides/automations`. Leave the section commented out
       if you do not use Automations.
   * - ``[ChatGPT]``
     - ``api_key``
     - OpenAI API key for the AI Assistant in the Document Generator (see
       :doc:`../guides/generate-documents`). Without a key the assistant shows as unavailable.
       The shipped file contains the placeholder ``<the api key>``, which counts as a key — comment
       the line out if you do not use the assistant, or generation fails with an error from OpenAI.

Environment variables
---------------------

Every value can also be set — and overridden — with an environment variable named
``DATAGERRY_<Section>_<key>``, with the section name spelled as in the file:

.. code-block:: bash

   DATAGERRY_Database_host=mongo.internal
   DATAGERRY_Database_port=27018
   DATAGERRY_WebServer_port=8080

The environment always wins over the file, and a section can exist only in the environment — a
container can run without a ``cmdb.conf`` at all.

To connect to MongoDB with a full connection string — a replica set, authentication, or MongoDB
Atlas — set ``CONNECTION_STRING`` instead of host and port:

.. code-block:: bash

   CONNECTION_STRING='mongodb://datagerry:<password>@mongo1,mongo2,mongo3/?replicaSet=rs0'

A ``mongodb+srv://`` connection string enables TLS to the database.

app-config.json
===============

Tells the web interface where the backend is:

.. literalinclude:: ../../../etc/app-config.json
   :language: json

``protocol``, ``apiUrl`` and ``apiPort`` must match how a browser reaches the backend. When you
change ``[WebServer] port`` in ``cmdb.conf``, change ``apiPort`` here to the same value. With
Docker, also update the port in ``docker-compose.yml`` and in the nginx configuration.

Settings in the web interface
=============================

Everything else is configured in DataGerry itself, under **Settings**:

* **Regional Settings** — date format and time zone.
* **Authentication** — login providers, LDAP and token lifetime; see
  :doc:`../guides/authentication`.
* **License Management** — see :doc:`../guides/license-management`.
* **System Information** and **Database Properties** — version, runtime and database details, for
  support requests.
* **Object Logs** — browse the change history of objects and delete log entries you no longer
  need.
