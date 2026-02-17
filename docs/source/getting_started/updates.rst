******************
Updating DataGerry
******************

DataGerry offers two deployment models - **Cloud (SaaS)** and **On-Premise** — each with its own approach to software updates.
This guide explains how updates are handled in both environments to help you keep your system up-to-date and running smoothly.

| 

=======================================================================================================================

| 

Cloud Updates
=============

In the Cloud (SaaS) version of DataGerry, all updates are handled automatically by the service provider.

Key points:
    * No manual action is required from the user
    * Updates are applied seamlessly in the background
    * Users always have access to the latest features, improvements, and security patches
    * Minimal or no downtime during the update process

This makes the Cloud version ideal for teams that want to avoid the overhead of maintaining infrastructure
or manually managing software upgrades.

| 

=======================================================================================================================

| 

On Premise Updates
==================

For self-hosted (on-premise) installations, updating DataGerry requires a manual process but is designed to be
straightforward and safe.

| 

Update process:
    1. Download and install the new DataGerry release from the official package source:  
       `BuildKite <https://buildkite.com/organizations/becon-gmbh/packages>`_ or from  
       Docker: `Docker <https://hub.docker.com/r/becongmbh/datagerry>`_
    2. Restart the DataGerry service or application

During startup, DataGerry will:
    - Automatically detect the new version
    - Run any required database or internal migrations
    - Complete the update process before starting the application

Important notes:
    - The update duration typically takes a few seconds to a few minutes depending on your system and data volume
    - Always back up your database and configuration files before starting an update
    - Review the changelog or release notes for any version-specific instructions

| 

By following this process, your on-premise deployment remains secure, current, and compatible with the latest features.

| 

Updating Docker Compose
----------------------------------------

.. code-block:: console

    cd DataGerry-docker
	docker compose down -v
	git pull
    docker compose up -d
	
| 
|

Updating zip Package
----------------------------------------

To update the zip package follow these steps:

.. code-block:: console

    systemctl stop datagerry
    systemctl stop rabbitmq-server (only required for updates from 2.2.0 to 3.x)
    systemctl disable rabbitmq-server (only required for updates from 2.2.0 to 3.x)
    unzip datagerry-<version>.zip (to the directory of the old installation)
    cd datagerry
    ./setup.sh
    systemctl daemon-reload
    systemctl start datagerry

| 

Updating deb Package
--------------------

Execute the following command with the new version package:

.. code-block:: console

    sudo apt install ./<datagerry-version>.deb

| 

Updating rpm Package
--------------------

Execute the following command with the new version package:

.. code-block:: console

    sudo rpm -Uvh DATAGERRY-<version>.x86_64.rpm