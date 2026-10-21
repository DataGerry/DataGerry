####################
Quick install
####################

.. contents::
   :local:

|selfhosted| Run DataGerry on your own machine in a few minutes with Docker Compose. This is the
quickest path for evaluation and a sound basis for production. For packages (DEB, RPM, ZIP), TLS
and production hardening, see :doc:`../operations/install`. To use DataGerry without installing
anything, see :doc:`cloud-quickstart`.

What you need
=============

* A Linux host with `Docker Engine <https://docs.docker.com/engine/install/>`_ and the Compose
  plugin.
* Port 80 free on the host.
* Git.

Start DataGerry
===============

The `DataGerry-docker <https://github.com/DataGerry/DataGerry-docker>`_ repository contains a
Compose file with three containers — the DataGerry backend, MongoDB and an nginx frontend — and
keeps all data in Docker volumes.

.. code-block:: console

   $ git clone https://github.com/DataGerry/DataGerry-docker.git /opt/DataGerry-docker
   $ cd /opt/DataGerry-docker
   $ cp conf/cmdb_default.conf conf/cmdb.conf
   $ cp conf/app-config_default.json conf/app-config.json
   $ cp conf/nginx_default.conf conf/nginx.conf
   $ docker compose up -d

Open ``http://<host>/`` in a browser and sign in:

.. list-table::
   :widths: 30 70

   * - User name
     - ``admin``
   * - Password
     - ``admin``

.. warning::
   Change the ``admin`` password straight away under **Settings → Users** (or the user menu), even
   on a test system.

If the page does not load, check the containers:

.. code-block:: console

   $ docker compose ps
   $ docker logs dg-backend

First steps
===========

* On the first sign-in the **Start Assistant** (*Welcome to DATAGERRY*) offers to create a
  ready-made set of types for your industry. Cancel it to start from scratch. See
  :doc:`../guides/assistant`.
* Build your first type yourself: :doc:`first-cmdb`.
* The installation runs as **Community Edition** — the label next to the logo says so. To unlock
  IPAM, ISMS, the Document Generator, Automations or the REST API, activate a license:
  :doc:`../guides/license-management`.
* Before you rely on it: set up :doc:`backups <../operations/backup-and-restore>` and
  :doc:`TLS <../operations/install>`.
