##################
Backup and restore
##################

.. contents::
   :local:

|selfhosted| On your own installation, backups are your responsibility. |cloud| In the cloud, becon
operates the infrastructure and its backups; to keep your own copy of the data, export it — see
:doc:`../guides/export-data`.

What to back up
===============

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - What
     - Where
   * - **The MongoDB database**
     - Everything DataGerry knows: types, objects, history, users, groups, rights, settings, reports,
       webhooks, ISMS data — and the files in the file explorer and attachments, which are stored in
       the database too. The database name is ``database_name`` in ``cmdb.conf`` (default ``cmdb``).
   * - **The configuration**
     - ``cmdb.conf`` and ``app-config.json`` — see :doc:`configuration`. For Docker, the whole
       ``conf/`` directory, including TLS certificates.

The database is the part that matters; the configuration is small and rarely changes.

Back up
=======

Use ``mongodump``, which ships with the MongoDB database tools. It can run while DataGerry is
running.

Packages:

.. code-block:: console

   # mongodump --db cmdb --gzip --archive=/var/backups/datagerry-$(date +%F).gz
   # cp -a /etc/datagerry /var/backups/datagerry-conf-$(date +%F)

Docker:

.. code-block:: console

   # docker exec dg-mongodb mongodump --db cmdb --gzip --archive > /var/backups/datagerry-$(date +%F).gz
   # cp -a /opt/DataGerry-docker/conf /var/backups/datagerry-conf-$(date +%F)

Add ``--uri`` with credentials if your MongoDB requires authentication. Run the backup daily, for
example from a systemd timer or cron, keep several generations, and copy them off the host.

Restore
=======

1. Stop DataGerry, so nothing writes to the database during the restore:

   .. code-block:: console

      # systemctl stop datagerry              # or: docker compose stop dg-backend

2. Restore the archive. ``--drop`` replaces the existing collections with the ones from the backup:

   .. code-block:: console

      # mongorestore --drop --gzip --archive=/var/backups/datagerry-2026-10-01.gz

   Docker:

   .. code-block:: console

      # docker exec -i dg-mongodb mongorestore --drop --gzip --archive < /var/backups/datagerry-2026-10-01.gz

3. Put the configuration files back if needed, and start DataGerry again.

Restore with the **same DataGerry version** that made the backup, or an older backup into a newer
version — DataGerry migrates the data on start, as with an update. Restoring a backup from a newer
version into an older DataGerry is not supported.

.. note::
   A license is bound to the machine it was activated on. Restoring onto a different machine keeps
   all data, but the instance falls back to Community until you activate a re-issued license — see
   :doc:`../guides/license-management`.

Test your backups
=================

A backup you have never restored is a hope, not a backup. Restore into a separate test installation
from time to time — set a different ``database_name`` or use a separate MongoDB — and sign in to
check the data.
