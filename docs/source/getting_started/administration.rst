**************
Administration
**************

| 

=======================================================================================================================

| 

Autostart
=========

.. note::
    This section is still under construction !

| 

=======================================================================================================================

| 

=======================================================================================================================

| 

Logging
=======

| 

Logging is done by the Python logging module. Each process of the application initializes the logging
with a configuration. This configuration is defined in the ``cmdb.utils.logger`` module.

By default, each process will write the logs to one file as it is not safe, to write to a single
logfile from multiple processes.

To add logs within the applications backend, use the following code snippet::

    import logging
    LOGGER = logging.getLogger(__name__)
    LOGGER.error("error message")


To get a logger, use the logging.getLogger() function with the name of the current module as
parameter. In the logging configuration, the output for the specific module or for parent packages
can be defined.


Log Levels
----------
The loglevel is configured in cmdb/__init__.py with the variable __MODE__. It can be overwritten by
startup parameters. For the main process (handling the startup), *INFO* is the minimum loglevel. All
other processes uses the defined loglevel in __MODE__.


Log Output
----------
At the moment, there is a console output and an output to logfiles (one logfile per process). The
files were placed in the *logs* directory and were rotated after 10MB of log content. 4 backup files
are stored for each logfile.


Changing the Log Configuration
------------------------------
The log configuration is done in the module cmdb.utils.logger. Change this module to change the log
configuration.

| 

=======================================================================================================================

| 

=======================================================================================================================

| 

Set Backend Port
=========

DataGerry backend is available on port 4000 by default.
To change the backend port do the following steps:

	
	Modify "port" in /etc/datagerry/cmdb.conf: 
	
	.. code-block:: sh

		[WebServer]
		host = 0.0.0.0
		port = 4000

		
	Modify "apiPort" in /etc/datagerry/app-config.json: 
	
	.. code-block:: sh

		{
		"protocol": "http",
		"apiUrl": "localhost",
		"apiPort": "4000"
		}


	Restart DataGerry:

	.. code-block:: console
	
		systemctl restart datagerry


.. note::
    | Ensure that the port configured in cmdb.conf and app-config.json is identical. 
    | A mismatch will prevent the frontend from communicating with the backend.

|
| For Docker installations you will find the config files in the folder /datagerry/conf.
| Please also modify the port in your docker-compose.yml and in the nginx.conf
| and restart your docker compose.

=======================================================================================================================

| 

=======================================================================================================================

| 

Backup
======

.. note::
    This section is still under construction !

| 

=======================================================================================================================

| 

Restore
=======

.. note::
    This section is still under construction !

| 
