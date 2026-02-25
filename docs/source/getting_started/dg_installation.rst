************************
On-Premises Installation
************************

This page provides a detailed overview of how to install DataGerry on various operating systems and platforms.

.. note::	

    | The installation commands must be executed by a user with sudo rights. 
    | Ensure you have administrative privileges to properly perform the installation.

=======================================================================================================================

| 

Overview
========

DataGerry can be installed in different environments depending on your use case and infrastructure preferences.
The following installation methods are supported:

- **Docker Image** (simplified deployment via containers)
- **RPM Package** (for RHEL/CentOS-based systems)
- **zip Package with Setup Script** (for all distributions)
- **Deb Package** (for Debian-based systems)

For the fastest setup, we recommend using Docker along with the provided docker-compose configuration.

=======================================================================================================================

Requirements
============

DataGerry has the following system requirements:

- **Linux Operating System**
- **MongoDB 6.0 or 7.0** 

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

.. code-block:: console
    
    git clone https://github.com/DataGerry/DataGerry-docker.git  
    cp /opt/DataGerry-docker/conf/cmdb_default.conf /opt/DataGerry-docker/conf/cmdb.conf
    cp /opt/DataGerry-docker/conf/nginx_default.conf /opt/DataGerry-docker/conf/nginx.conf

.. note::
	We recommend always to use the latest tag version.

	If you like to use SSL, do the following steps:
	
	Create config folders for SSL: 
	
	.. code-block:: console
	
		mkdir /opt/DataGerry-docker/conf/ssl
		mkdir /opt/DataGerry-docker/conf/ssl/certs
		mkdir /opt/DataGerry-docker/conf/ssl/private

	Copy your own certificates to these folders!
		
	Copy the Nginx SSL-configuration file for DataGerry:

	.. code-block:: console
	
		cp /opt/DataGerry-docker/conf/nginx-ssl_default.conf /opt/DataGerry-docker/conf/nginx-ssl.conf

	Change the certificates within the config (nginx-ssl.conf), with your own:	
			
	.. code-block:: console
	
		ssl_certificate /opt/DataGerry-docker/conf/ssl/certs/cmdb.pem;
		ssl_certificate_key /opt/DataGerry-docker/conf/ssl/private/cmdb.key;

	Set ssl to true and change the certificates within the config (/etc/datagery/cmdb.conf), with your own:	
			
	.. code-block:: console
		
		ssl = true
		certfile = /etc/ssl/certs/cmdb.pem
		keyfile = /etc/ssl/private/cmdb.key


	Activate SSL in docker compose file (/opt/DataGerry-docker/docker-compose.yml):

	.. code-block:: console
	
		dg-frontend:
		# comment for ssl
		# - ./conf/nginx.conf:/etc/nginx/conf.d/default.conf
		# uncomment for ssl
		- ./conf/nginx-ssl.conf:/etc/nginx/conf.d/default.conf
		- ./conf/ssl/certs/:/etc/ssl/certs/
		- ./conf/ssl/private/:/etc/ssl/private/
	
		dg-backend:
		# uncomment for ssl
		- ./conf/ssl/certs/:/etc/ssl/certs/
		- ./conf/ssl/private/:/etc/ssl/private/


3. Start DataGerry using DockerHub images:

.. code-block:: 

	cd DataGerry-docker
	docker compose up -d

.. note::
	| Now you can connect to DataGerry, by navigating to http://localhost (for SSL https://localhost) in your web browser.

	| The default login credentials are:
	|
	| **Username: admin**
	| **Password: admin**
	|

	| If you want to have a look into DataGerry logs please use:
	
	.. code-block:: console
		
		docker logs dg-backend
		docker logs dg-frontend
		docker logs dg-mongodb

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

DataGerry requires **MongoDB 6.0** or **MongoDB 7.0**

| To install MongoDB, follow the official MongoDB guide for your platform:  
| `MongoDB Installation Guide <https://www.mongodb.com/docs/v7.0/administration/install-on-linux/#std-label-install-mdb-community-edition-linux>`_

| 

=======================================================================================================================

DataGerry Installation
----------------------

Once MongoDB is installed, install the RPM package:

.. code-block:: console

    rpm -ivh DATAGERRY-<version>.x86_64.rpm

.. note::

	If you like to use SSL, do the following steps:
	
	Set ssl to true and change the certificates within the config (/etc/datagery/cmdb.conf), with your own:	
			
	.. code-block:: console
		
		ssl = true
		certfile = /etc/ssl/certs/cmdb.pem
		keyfile = /etc/ssl/private/cmdb.key

    | Restart datagerry service:

	.. code-block:: console
		
		systemctl restart datagerry


.. note::
	| Now you can connect to DataGerry, by navigating to http://localhost (for SSL https://localhost) in your web browser.

	| The default login credentials are:
	|
	| **Username: admin**
	| **Password: admin**
	|

	| If you want to have a look into DataGerry logs please use:
	
	.. code-block:: console
		
		journalctl -xe -u datagerry -f


    | If the frontend is not accessible, verify that port 4000 is open in your server's firewall.

| 

=======================================================================================================================

| 

=======================================================================================================================

| 

Setup via zip Package
==============================

For Linux distributions that are not RPM-based or DEB-based, we provide a ``zip`` archive containing a setup script
for simplified installation. This method requires **systemd** and has been tested on the following distributions:

    - Ubuntu 22.04
    - Ubuntu 24.04

This approach should also work on other distributions that support systemd.

| 

=======================================================================================================================

MongoDB Setup
-------------

DataGerry requires **MongoDB 6.0** or **MongoDB 7.0**

| To install MongoDB, follow the official MongoDB guide for your platform:  
| `MongoDB Installation Guide <https://www.mongodb.com/docs/v7.0/administration/install-on-linux/#std-label-install-mdb-community-edition-linux>`_

=======================================================================================================================

DataGerry Installation
----------------------

Download the ZIP :ref:`here <package-zip-anchor>`.

.. code-block:: console

    unzip datagerry-<version>.zip
    cd datagerry
    sudo ./setup.sh

.. note::

	If you like to use SSL, do the following steps:
	
	Set ssl to true and change the certificates within the config (/etc/datagery/cmdb.conf), with your own:	
			
	.. code-block:: console
		
		ssl = true
		certfile = /etc/ssl/certs/cmdb.pem
		keyfile = /etc/ssl/private/cmdb.key

    | Restart datagerry service:

	.. code-block:: console
		
		systemctl restart datagerry


.. note::
	| Now you can connect to DataGerry, by navigating to http://localhost (for SSL https://localhost) in your web browser.

	| The default login credentials are:
	|
	| **Username: admin**
	| **Password: admin**
	|

	| If you want to have a look into DataGerry logs please use:
	
	.. code-block:: console
		
		journalctl -xe -u datagerry -f


    | If the frontend is not accessible, verify that port 4000 is open in your server's firewall.

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

DataGerry requires **MongoDB 6.0** or **MongoDB 7.0**

| To install MongoDB, follow the official MongoDB guide for your platform:  
| `MongoDB Installation Guide <https://www.mongodb.com/docs/v7.0/administration/install-on-linux/#std-label-install-mdb-community-edition-linux/>`_

| 

DataGerry Installation
----------------------

Download the DEB :ref:`here <package-deb-anchor>`.

Navigate to the directory containing the package and run:

.. code-block:: console

    apt install ./<datagerry-version>.deb

.. note::

	If you like to use SSL, activate it within the config (/etc/datagerry/cmdb.conf):
	
	Set ssl to true and change the certificates with your own:	
			
	.. code-block:: console
		
		ssl = true
		certfile = /etc/ssl/certs/cmdb.pem
		keyfile = /etc/ssl/private/cmdb.key

    | Restart datagerry service:

	.. code-block:: console
		
		systemctl restart datagerry


.. note::
	| Now you can connect to DataGerry, by navigating to http://localhost (for SSL https://localhost) in your web browser.

	| The default login credentials are:
	|
	| **Username: admin**
	| **Password: admin**
	|

	| If you want to have a look into DataGerry logs please use:
	
	.. code-block:: console
		
		journalctl -xe -u datagerry -f


    | If the frontend is not accessible, verify that port 4000 is open in your server's firewall.

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
