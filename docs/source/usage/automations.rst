****
Automations
****

.. _isms-anchor:

.. contents:: Table of Contents
    :local:

=======================================================================================================================

The **Automations** feature in DataGerry allows you to create and manage interfaces directly through the user interface. In the background, **OpenCelium** is used to handle the connections to external systems, making it easy to automate tasks and manage integrations.

.. figure:: img/isms/isms_overview.png
    :width: 600

    Picture: ISMS overview

| 

=======================================================================================================================

Generell
====================

| 

Self-Hosted vs. Cloud
----------------------

- **Self-Hosted**: In the Self-Hosted version of DataGerry, you can access the OpenCelium license overview. This allows you to manage and monitor the licenses being used.
  
- **Cloud**: In the Cloud version of DataGerry, licenses are automatically assigned to users when they use DataGerry in the cloud. Therefore, the license overview is not relevant in this version.

| 

=======================================================================================================================
| 

Automation Overview
====================


Accessing Automations
----------------------

To access **Automations**, navigate to the **Toolbox** menu in the DataGerry dashboard, and select the **Automations** sub-menu. You will be presented with a table displaying all created automations, which includes the following key information:

- **Direction (Data Flow Direction)**: Defines the direction of the interface—either **Incoming**, **Outgoing**, or **Internal**.
- **Cron Expression**: The time-based configuration that defines how frequently the automation will run.
- **Last Success**: The last successful execution time of the automation.
- **Last Failure**: The last time the automation failed.
- **Last Duration**: The duration of the last automation run.
- **Logs**: Logs that can be toggled on or off for monitoring the automation’s activity.
- **Status**: The current status of the automation (active, inactive, etc.).
- **Action List**: Here, you can start, edit, adjust the cron expression, or delete the automation.

| 

=======================================================================================================================
| 

Automation Refresh
-------------------

You can enable **auto-refresh** for the Automations page, which ensures that you are always seeing the most up-to-date status and data related to your automations.

|

Managing Connectors
-------------------
|

In the **Automations** section, you can manage and configure **connectors**. You can modify existing connections or create new ones to send or receive data from various sources.

|

Creating a New Automation
--------------------------

### Steps to create a new automation:

1. Click on **Create New Automation**.
2. A form will open asking for the following details:
   - **Name** of the automation.
   - **Description** (optional).
   - **Direction of Data Flow**: Choose the desired data flow direction (**incoming**, **outgoing**, or **internal**).
   - **Connector**: Select the connector through which you want to send or receive data.

Documentation and Further Help
------------------------------

For more detailed information on the **Automations** feature in DataGerry and the OpenCelium integration, please refer to the `OpenCelium Documentation <https://docs.opencelium.io>`_ or the `DataGerry User Manual <https://docs.datagerry.org>`_.

Notes:
------

- If you have any questions or need assistance, you can visit the `DataGerry Community <https://forum.datagerry.org>`_ or contact support.