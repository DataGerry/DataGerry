########
Updating
########

.. contents::
   :local:

|selfhosted| How to install a new DataGerry release on your own server. |cloud| Cloud subscriptions
are updated by becon; you always work with the current release and do not need to do anything.

How an update works
===================

You replace the software and restart DataGerry. On start, DataGerry detects that its database
belongs to an older version, runs the necessary migrations, and only then starts serving requests.
Depending on the amount of data this takes a few seconds to a few minutes.

Before you start:

* **Back up** the database and the configuration — see :doc:`backup-and-restore`. Migrations
  cannot be undone; the backup is your way back.
* Read the :doc:`changelog <../reference/changelog>` and :doc:`../start/whats-new-3-3` for the
  versions you skip. Updating to 3.3, review your groups: more areas are now controlled by rights.

Docker Compose
==============

.. code-block:: console

   # cd /opt/DataGerry-docker
   # docker compose down
   # git pull
   # docker compose pull
   # docker compose up -d

Compare your files in ``conf/`` with the new ``*_default`` files after ``git pull`` and carry over
new settings.

.. note::
   A license is bound to the machine fingerprint. If a recreated container reports a different
   fingerprint, DataGerry falls back to Community and the license has to be re-issued — see
   :doc:`../guides/license-management`.

DEB package
===========

.. code-block:: console

   # apt install ./DataGerry_<version>_all.deb

RPM package
===========

.. code-block:: console

   # rpm -Uvh DATAGERRY-<version>.x86_64.rpm

ZIP package
===========

Unpack the new release over the directory of the existing installation and run the setup script
again:

.. code-block:: console

   # systemctl stop datagerry
   # unzip datagerry-<version>.zip
   # cd datagerry
   # ./setup.sh

The script reloads systemd and starts the service.

.. note::
   Coming from 2.2.0: DataGerry 3.x no longer uses RabbitMQ. Stop and disable it before the update:
   ``systemctl disable --now rabbitmq-server``.

After the update
================

* Follow the log until the start-up is complete: ``journalctl -u datagerry -f`` (packages) or
  ``docker logs -f dg-backend``.
* Sign in and check **Settings → System Information** for the new version.
* Reload the browser page — every user — so the new interface is loaded.
