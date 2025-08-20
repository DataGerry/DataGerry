************************
On-Premises Installation
************************

This page provides a detailed overview of how to install DataGerry on various operating systems and platforms.

| 

=======================================================================================================================

| 

Overview
========

DataGerry can be installed in different environments depending on your use case and infrastructure preferences.
The following installation methods are supported:

- **Docker Image** (simplified deployment via containers)
- **RPM Package** (for RHEL/CentOS-based systems)
- **tar.gz Archive with Setup Script** (for Debian/Ubuntu and other distributions)
- **Deb Package** (for Debian-based systems)

For the fastest setup, we recommend using Docker along with the provided docker-compose configuration.

=======================================================================================================================

Requirements
============

DataGerry has the following system requirements:

- **Linux Operating System**
- **MongoDB 6.0** (MongoDB 4.4+ is generally compatible but not officially supported)

Although DataGerry ships with a built-in web server, it is recommended to place it behind **Nginx** for improved
performance and security.

| 

=======================================================================================================================

| 

Configuration
=============


Most of DataGerry's configuration is stored in MongoDB. However, a few parameters—such as the MongoDB connection
itself must be defined outside the database. These settings are provided in an INI-style configuration file
named ``cmdb.conf``.

Example:

.. include:: ../../../etc/cmdb.conf
    :literal:

You can also override configuration options using environment variables:

.. code-block:: bash

   DATAGERRY_<section_name>_<option_name>
   DATAGERRY_Database_port=27018

This approach is especially useful when running DataGerry in Docker environments.

| 

=======================================================================================================================

| 

=======================================================================================================================

| 

Setup via Docker Image
======================

The quickest way to get started with DataGerry is using Docker.

Docker is a container-based software framework for automating deployment of 
applications. Compose is a tool for defining and running multi-container Docker 
applications.

The DataGerry-docker repo is meant to be the starting point for somebody, who likes to use 
dockerized multi-container DataGerry in production. The DataGerry Docker image uses 
the stable branch of DataGerry's Git repo.

The Docker images are hosted on `Dockerhub <https://hub.docker.com/u/becongmbh>`_.

We provide a docker-compose file that sets up the
following containers:

    - **DataGerry**
    - **MongoDB**
    - **Nginx**

All data is persisted using Docker volumes on the host machine.

**Install Docker Environment:**

1. Install Docker:

Use default Docker installation guide.

   * `Docker Engine <https://docs.docker.com/engine/installation/>`_
   * `Docker Compose <https://docs.docker.com/compose/install/>`_ (opt. Docker Engine installation already includes Docker Compose Plugin)

2. Getting started with DataGerry-docker:

.. code-block:: sh
	:linenos:

	git clone https://github.com/DataGerry/DataGerry-docker.git  
	cd DataGerry-docker

.. note::
	We recommend always to use the latest tag version.

3. Start DataGerry using DockerHub images:

.. code-block:: sh
	:linenos:

	docker compose up -d

.. note::
	| Now you can access the DataGerry frontend:	
	| 'http://localhost'
	
	| Default User: admin
	| Default Password: admin

| 

=======================================================================================================================

| 

=======================================================================================================================

| 

Setup via RPM 
=============

For **Red Hat Enterprise Linux (RHEL)** and compatible systems like **CentOS** or **Oracle Linux**, DataGerry can
be installed using an RPM package.

Download the RPM :ref:`here <package-rpm-anchor>`.

Supported Platforms:

    - RHEL/CentOS 9 (tested and verified)

| 

=======================================================================================================================

MongoDB Setup
-------------

DataGerry requires MongoDB 6.0. MongoDB 4.4+ may work but is not guaranteed.

Installation instructions are available here:  
`MongoDB Installation for RHEL <https://www.mongodb.com/docs/v6.0/tutorial/install-mongodb-on-red-hat/>`_

| 

=======================================================================================================================

DataGerry Installation
----------------------

Once MongoDB is installed, install the RPM package:

.. code-block:: console

    $ sudo rpm -ivh DATAGERRY-<version>.x86_64.rpm


You can now access the frontend:

.. code-block:: console

    http://<host>:4000
    user: admin
    password: admin

.. note::
   If the frontend is not accessible, verify that port 4000 is open in your server's firewall.

| 

=======================================================================================================================

| 

=======================================================================================================================

| 

Setup via zip Archive
==============================

For Linux distributions that are not RPM-based, we provide a ``zip`` archive containing a setup script
for simplified installation. This method requires **systemd** and has been tested on the following distributions:

    - Ubuntu 20.04
    - Ubuntu 22.04

This approach should also work on other distributions that support systemd.

| 

=======================================================================================================================

MongoDB Setup
-------------

DataGerry requires **MongoDB 6.0** as its database backend. MongoDB 4.4+ is generally compatible, though not officially supported.

To install MongoDB, follow the official MongoDB guide for your platform:  
`MongoDB Installation Guide <https://www.mongodb.com/docs/v6.0/administration/install-on-linux/>`_

=======================================================================================================================

DataGerry Installation
----------------------

Download the ZIP :ref:`here <package-zip-anchor>`.

.. code-block:: console

    $ unzip datagerry-<version>.zip
    $ cd datagerry
    $ sudo ./setup.sh

| 

Configuration
-------------

After the setup, configure the MongoDB connection in the configuration file:

.. code-block:: console

    /etc/datagerry/cmdb.conf

You can also override configuration values using environment variables (see the configuration section for details).

| 

Service Activation
------------------

Enable and start the DataGerry service using systemd:

.. code-block:: console

    $ sudo systemctl enable datagerry.service
    $ sudo systemctl start datagerry.service

| 

Accessing the Web Interface
---------------------------

Once started, you can access the DataGerry web interface at:

.. code-block:: console

    http://<host>:4000
    user: admin
    password: admin

.. note::
   If you are unable to access the frontend, ensure that port **4000** is open and not blocked by your system firewall.

| 

=======================================================================================================================

| 

=======================================================================================================================

| 

Setup via DEB Package
=====================

For Debian-based systems, DataGerry provides a `.deb` package for easy installation.

.. note::
   You only need to install **MongoDB** separately. Other required services are included with the package.

| 

MongoDB Setup
-------------

Follow the official MongoDB guide to install MongoDB 6.0 on Debian:

`Install MongoDB on Debian <https://www.mongodb.com/docs/v6.0/tutorial/install-mongodb-on-debian/>`_

| 

DataGerry Installation
----------------------

Download the DEB :ref:`here <package-deb-anchor>`.

Navigate to the directory containing the package and run:

.. code-block:: console

    $ sudo apt install ./<datagerry-version>.deb

| 

Web Interface Access
--------------------

Once installed, you can access the DataGerry web frontend at:

.. code-block:: console

    http://<host>:4000
    user: admin
    password: admin

.. note::
   If the interface is not reachable, ensure that port **4000** is open in your firewall settings.

| 

=======================================================================================================================

| 

=======================================================================================================================

| 

Nginx
-----

| 

We recommend using **Nginx** as a reverse proxy to enhance performance, enable SSL, and improve accessibility.

After installing Nginx for your platform, adapt the following configuration for your environment:

.. include:: ../../../contrib/nginx/nginx.conf
    :literal:

This setup will:

    - Listen on ports **80 (HTTP)** and **443 (HTTPS)**
    - Automatically redirect HTTP to HTTPS
    - Forward HTTPS requests from `https://<host>/` to the DataGerry backend at `http://127.0.0.1:4000`

.. tip::
   Using a reverse proxy is especially useful for integrating with Let's Encrypt, securing the UI, and supporting
   custom domains.

| 
