##########
Installing
##########

.. contents::
   :local:

|selfhosted| How to install DataGerry on your own server, and put it behind nginx with TLS. For a
first look, :doc:`../start/self-hosted-quickstart` is quicker. Check :doc:`requirements` first.

All commands need root rights (``sudo``).

Choose a method
===============

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Method
     - Use it when
   * - **Docker Compose**
     - You run containers anyway, or want the shortest path. Brings MongoDB and nginx along.
   * - :ref:`RPM package <install-rpm>`
     - RHEL 9 and compatible distributions.
   * - :ref:`ZIP with setup script <install-zip>`
     - Any other Linux distribution with systemd.
   * - :ref:`DEB package <install-deb>`
     - Debian or Ubuntu.

Download links for all packages and images are in :doc:`../reference/downloads`. Licensed
customers also find the releases under **Packages & Downloads** in the Service Portal.

Docker Compose
==============

The `DataGerry-docker <https://github.com/DataGerry/DataGerry-docker>`_ repository starts three
containers — ``dg-backend``, ``dg-mongodb`` and ``dg-frontend`` (nginx) — and keeps all data in
Docker volumes. Images are on `Docker Hub <https://hub.docker.com/u/becongmbh>`_; use the latest
version tag.

.. code-block:: console

   # git clone https://github.com/DataGerry/DataGerry-docker.git /opt/DataGerry-docker
   # cd /opt/DataGerry-docker
   # cp conf/cmdb_default.conf conf/cmdb.conf
   # cp conf/app-config_default.json conf/app-config.json
   # cp conf/nginx_default.conf conf/nginx.conf
   # docker compose up -d

The configuration files live in ``/opt/DataGerry-docker/conf`` — ``cmdb.conf`` for the backend,
``app-config.json`` for the web interface and ``nginx.conf`` for the frontend container. See
:doc:`configuration`.

Open DataGerry in the browser
-----------------------------

As soon as the containers are running, DataGerry can be opened in the browser at
``http://<host>/`` (on the Docker host itself: ``http://localhost``). Sign in with:

.. list-table::
   :widths: 30 70

   * - User name
     - ``admin``
   * - Password
     - ``admin``

.. warning::
   Change the ``admin`` password straight away under **Settings → Users**, even on a test system.

If the page does not load, check that all three containers are running:

.. code-block:: console

   # docker compose ps

Logs
----

Each container writes its own log. Follow them with:

.. code-block:: console

   # docker logs -f dg-backend
   # docker logs -f dg-frontend
   # docker logs -f dg-mongodb

``dg-backend`` is the one to look at first: it shows the start-up, database migrations after an
update, and errors of the application.

TLS with Docker
---------------

1. Put your certificate and key into ``conf/ssl/certs/`` and ``conf/ssl/private/``.
2. Copy ``conf/nginx-ssl_default.conf`` to ``conf/nginx-ssl.conf`` and set the file names:

   .. code-block:: nginx

      ssl_certificate     /etc/ssl/certs/cmdb.pem;
      ssl_certificate_key /etc/ssl/private/cmdb.key;

3. In ``conf/cmdb.conf``, section ``[WebServer]``, set ``ssl = true`` and the same ``certfile`` and
   ``keyfile``.
4. In ``docker-compose.yml``, switch the frontend volume from ``nginx.conf`` to ``nginx-ssl.conf``
   and mount the certificate folders into both containers:

   .. code-block:: yaml

      dg-frontend:
        volumes:
          - ./conf/nginx-ssl.conf:/etc/nginx/conf.d/default.conf
          - ./conf/ssl/certs/:/etc/ssl/certs/
          - ./conf/ssl/private/:/etc/ssl/private/
      dg-backend:
        volumes:
          - ./conf/ssl/certs/:/etc/ssl/certs/
          - ./conf/ssl/private/:/etc/ssl/private/

5. ``docker compose up -d``.

.. _install-rpm:

RPM package
===========

For **Red Hat Enterprise Linux (RHEL)** and compatible systems like **CentOS** or **Oracle Linux**,
DataGerry can be installed using an RPM package. Download it from :doc:`../reference/downloads`.

Supported platforms:

* RHEL/CentOS 9 (tested and verified)

MongoDB setup
-------------

To install MongoDB, follow the official
`MongoDB installation guide <https://www.mongodb.com/docs/v8.0/administration/install-on-linux/>`_
for your platform.

DataGerry installation
----------------------

Once MongoDB is installed, install the RPM package:

.. code-block:: console

   # rpm -ivh DATAGERRY-<version>.x86_64.rpm

.. note::
   If you like to use SSL, set ``ssl`` to ``true`` in ``/etc/datagerry/cmdb.conf`` and replace the
   certificates with your own:

   .. code-block:: ini

      ssl = true
      certfile = /etc/ssl/certs/cmdb.pem
      keyfile = /etc/ssl/private/cmdb.key

   Make sure the ``datagerry`` user has sufficient permissions to read your certificate files.
   Additionally, the ``private`` folder needs read and execute permission for the ``datagerry``
   user. Restart the service:

   .. code-block:: console

      # systemctl restart datagerry

Accessing the web interface
---------------------------

Now you can connect to DataGerry by navigating to ``http://localhost`` in your web browser (for
SSL use ``https://localhost``). The default login credentials are:

.. list-table::
   :widths: 30 70

   * - User name
     - ``admin``
   * - Password
     - ``admin``

If the frontend is not accessible, verify that port 4000 is open in your server's firewall.

To look into the DataGerry logs, use:

.. code-block:: console

   # journalctl -xe -u datagerry -f

.. _install-zip:

ZIP package
===========

For Linux distributions that are not RPM-based or DEB-based, we provide a ``zip`` archive containing
a setup script for simplified installation. Download it from :doc:`../reference/downloads`. This
method requires **systemd** and has been tested on the following distributions:

* Ubuntu 22.04
* Ubuntu 24.04

This approach should also work on other distributions that support systemd.

MongoDB setup
-------------

To install MongoDB, follow the official
`MongoDB installation guide <https://www.mongodb.com/docs/v8.0/administration/install-on-linux/>`_
for your platform.

DataGerry installation
----------------------

.. code-block:: console

   # unzip datagerry-<version>.zip
   # cd datagerry
   # sudo ./setup.sh

.. note::
   If you like to use SSL, set ``ssl`` to ``true`` in ``/etc/datagerry/cmdb.conf`` and replace the
   certificates with your own:

   .. code-block:: ini

      ssl = true
      certfile = /etc/ssl/certs/cmdb.pem
      keyfile = /etc/ssl/private/cmdb.key

   Make sure the ``datagerry`` user has sufficient permissions to read your certificate files.
   Additionally, the ``private`` folder needs read and execute permission for the ``datagerry``
   user. Restart the service:

   .. code-block:: console

      # systemctl restart datagerry

Accessing the web interface
---------------------------

Now you can connect to DataGerry by navigating to ``http://localhost`` in your web browser (for
SSL use ``https://localhost``). The default login credentials are:

.. list-table::
   :widths: 30 70

   * - User name
     - ``admin``
   * - Password
     - ``admin``

If the frontend is not accessible, verify that port 4000 is open in your server's firewall.

To look into the DataGerry logs, use:

.. code-block:: console

   # journalctl -xe -u datagerry -f

.. _install-deb:

DEB package
===========

For Debian-based systems, DataGerry provides a ``.deb`` package for easy installation. Download it
from :doc:`../reference/downloads`.

.. note::
   You only need to install **MongoDB** separately. Other required services are included with the
   package.

MongoDB setup
-------------

To install MongoDB, follow the official
`MongoDB installation guide <https://www.mongodb.com/docs/v8.0/administration/install-on-linux/>`_
for your platform.

DataGerry installation
----------------------

Navigate to the directory containing the package and run:

.. code-block:: console

   # apt install ./<datagerry-version>.deb

.. note::
   If you like to use SSL, set ``ssl`` to ``true`` in ``/etc/datagerry/cmdb.conf`` and replace the
   certificates with your own:

   .. code-block:: ini

      ssl = true
      certfile = /etc/ssl/certs/cmdb.pem
      keyfile = /etc/ssl/private/cmdb.key

   Make sure the ``datagerry`` user has sufficient permissions to read your certificate files.
   Additionally, the ``private`` folder needs read and execute permission for the ``datagerry``
   user. Restart the service:

   .. code-block:: console

      # systemctl restart datagerry

Accessing the web interface
---------------------------

Now you can connect to DataGerry by navigating to ``http://localhost`` in your web browser (for
SSL use ``https://localhost``). The default login credentials are:

.. list-table::
   :widths: 30 70

   * - User name
     - ``admin``
   * - Password
     - ``admin``

If the frontend is not accessible, verify that port 4000 is open in your server's firewall.

To look into the DataGerry logs, use:

.. code-block:: console

   # journalctl -xe -u datagerry -f

nginx as reverse proxy
======================

We recommend using **nginx** as a reverse proxy in front of a package installation, to improve
performance, enable SSL and use your own domain name. DataGerry then listens on ``127.0.0.1:4000``
and nginx serves port 80/443.

.. note::
   The nginx configuration is **not** part of the packages. Install nginx for your platform, then
   copy one of the configurations below into your nginx configuration (for example
   ``/etc/nginx/conf.d/datagerry.conf``) and adapt it to your environment.

HTTP only — listens on port 80 and forwards requests from ``http://<host>/`` to the DataGerry
backend at ``http://127.0.0.1:4000``:

.. literalinclude:: ../../../contrib/nginx/nginx.conf
   :language: nginx

With TLS — listens on ports 80 and 443, redirects HTTP to HTTPS, and forwards requests from
``https://<host>/`` to the DataGerry backend at ``http://127.0.0.1:4000``:

.. literalinclude:: ../../../contrib/nginx/nginx-ssl.conf
   :language: nginx

A reverse proxy also makes it easy to use Let's Encrypt certificates and custom domains. When the
browser reaches DataGerry through nginx, set ``app-config.json`` to the address of nginx — see
:doc:`configuration`.

First sign-in
=============

Sign in with user name ``admin`` and password ``admin``, and change the password immediately. Then:

* :doc:`configuration` — review ``cmdb.conf``.
* :doc:`backup-and-restore` — set up backups before you enter real data.
* :doc:`../guides/license-management` — activate a license for the premium features.
