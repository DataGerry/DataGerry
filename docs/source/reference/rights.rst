######
Rights
######

.. contents::
   :local:

All system rights of DataGerry 3.3, grouped by area. You assign rights to a user
group (:doc:`../guides/users-and-groups`); how rights, groups and ACLs work together
is explained in :doc:`../concepts/permissions`. The same list, together with the
groups that hold each right, is shown under **Settings → Rights**.

How to read the tables
======================

* A right ending in ``.*`` holds every right below it. ``base.framework.object.*``
  grants ``view``, ``add``, ``edit``, ``delete`` and ``activation`` for objects;
  ``base.*`` grants everything.
* **Level** is the sensitivity of the right as shown on the **Rights** page
  (from low to high: Permission, Protected, Secure, Danger). It is informational;
  it does not change what the right grants.
* Rights for a premium feature (marked |licensed|) only take effect where the feature
  is available: in the cloud, or on a self-hosted installation whose license includes
  it. A right never unlocks a feature the license does not include. See
  :doc:`../guides/license-management`.
* Rights new or newly enforced in 3.3 include racks, ports and port connections,
  locations, CI Explorer, reports, webhooks, ISMS reports and imports, logs and the
  split import/export rights *(3.3)*.

Master right
============

The Administrator group holds ``base.*``. It cannot be removed from that group *(3.3)*.

.. list-table::
   :header-rows: 1
   :widths: 45 40 15

   * - Right
     - Description
     - Level
   * - ``base.*``
     - Every right (master right, held by the Administrator group)
     - —

System
======

.. list-table::
   :header-rows: 1
   :widths: 45 40 15

   * - Right
     - Description
     - Level
   * - ``base.system.*``
     - Manage system configuration and settings
     - Secure
   * - ``base.system.view``
     - View system configurations and settings
     - Secure
   * - ``base.system.edit``
     - Edit system configurations and settings
     - Secure
   * - ``base.system.reload``
     - Reload system configurations
     - Secure
   * - ``base.system.export``
     - Export the configuration: types, categories, section templates, relations
     - Secure

Framework
=========

.. list-table::
   :header-rows: 1
   :widths: 45 40 15

   * - Right
     - Description
     - Level
   * - ``base.framework.*``
     - Manage the core framework
     - Permission
   * - ``base.framework.object.*``
     - Manage objects
     - Permission
   * - ``base.framework.object.view``
     - View objects
     - Permission
   * - ``base.framework.object.add``
     - Add objects
     - Permission
   * - ``base.framework.object.edit``
     - Edit objects
     - Protected
   * - ``base.framework.object.delete``
     - Delete objects
     - Secure
   * - ``base.framework.object.activation``
     - Activate/Deactivate objects
     - Secure
   * - ``base.framework.type.*``
     - Manage types
     - Secure
   * - ``base.framework.type.view``
     - View types
     - Protected
   * - ``base.framework.type.add``
     - Add types
     - Protected
   * - ``base.framework.type.edit``
     - Edit types
     - Secure
   * - ``base.framework.type.delete``
     - Delete types
     - Secure
   * - ``base.framework.type.activation``
     - Activate/Deactivate types
     - Secure
   * - ``base.framework.category.*``
     - Manage categories
     - Protected
   * - ``base.framework.category.view``
     - View categories
     - Protected
   * - ``base.framework.category.add``
     - Add categories
     - Protected
   * - ``base.framework.category.edit``
     - Edit categories
     - Protected
   * - ``base.framework.category.delete``
     - Delete categories
     - Secure
   * - ``base.framework.sectionTemplate.*``
     - Manage section templates
     - Permission
   * - ``base.framework.sectionTemplate.view``
     - View section templates
     - Permission
   * - ``base.framework.sectionTemplate.add``
     - Add section templates
     - Permission
   * - ``base.framework.sectionTemplate.edit``
     - Edit section templates
     - Protected
   * - ``base.framework.sectionTemplate.delete``
     - Delete section templates
     - Secure
   * - ``base.framework.relation.*``
     - Manage relations
     - Protected
   * - ``base.framework.relation.view``
     - View relations
     - Protected
   * - ``base.framework.relation.add``
     - Add relations
     - Protected
   * - ``base.framework.relation.edit``
     - Edit relations
     - Protected
   * - ``base.framework.relation.delete``
     - Delete relations
     - Danger
   * - ``base.framework.objectRelation.*``
     - Manage object relations
     - Protected
   * - ``base.framework.objectRelation.view``
     - View object relations
     - Protected
   * - ``base.framework.objectRelation.add``
     - Add object relations
     - Protected
   * - ``base.framework.objectRelation.edit``
     - Edit object relations
     - Protected
   * - ``base.framework.objectRelation.delete``
     - Delete object relations
     - Danger
   * - ``base.framework.objectRelationLog.*``
     - Manage object relation logs
     - Protected
   * - ``base.framework.objectRelationLog.view``
     - View object relation logs
     - Protected
   * - ``base.framework.objectRelationLog.delete``
     - Delete object relation logs
     - Danger
   * - ``base.framework.extendableOption.*``
     - Manage extendable options
     - Protected
   * - ``base.framework.extendableOption.view``
     - View extendable options
     - Protected
   * - ``base.framework.extendableOption.add``
     - Add extendable options
     - Protected
   * - ``base.framework.extendableOption.edit``
     - Edit extendable options
     - Protected
   * - ``base.framework.extendableOption.delete``
     - Delete extendable options
     - Secure
   * - ``base.framework.objectGroup.*``
     - Manage object groups
     - Protected
   * - ``base.framework.objectGroup.view``
     - View object groups
     - Protected
   * - ``base.framework.objectGroup.add``
     - Add object groups
     - Protected
   * - ``base.framework.objectGroup.edit``
     - Edit object groups
     - Protected
   * - ``base.framework.objectGroup.delete``
     - Delete object groups
     - Secure
   * - ``base.framework.log.*``
     - Manage framework logs
     - Protected
   * - ``base.framework.log.view``
     - View logs
     - Protected
   * - ``base.framework.log.reload``
     - Reload logs
     - Secure
   * - ``base.framework.log.delete``
     - Delete logs
     - Danger

Webhooks, reports, CI Explorer and locations
============================================

.. list-table::
   :header-rows: 1
   :widths: 45 40 15

   * - Right
     - Description
     - Level
   * - ``base.framework.webhook.*``
     - Manage webhooks
     - Protected
   * - ``base.framework.webhook.view``
     - View webhooks
     - Protected
   * - ``base.framework.webhook.add``
     - Add webhooks
     - Protected
   * - ``base.framework.webhook.edit``
     - Edit webhooks
     - Protected
   * - ``base.framework.webhook.delete``
     - Delete webhooks
     - Danger
   * - ``base.framework.report.*``
     - Manage reports
     - Permission
   * - ``base.framework.report.view``
     - View reports
     - Permission
   * - ``base.framework.report.add``
     - Add reports
     - Permission
   * - ``base.framework.report.edit``
     - Edit reports
     - Protected
   * - ``base.framework.report.delete``
     - Delete reports
     - Secure
   * - ``base.framework.ciExplorer.*``
     - Manage the CI Explorer
     - Protected
   * - ``base.framework.ciExplorer.view``
     - View the CI Explorer
     - Protected
   * - ``base.framework.ciExplorer.edit``
     - Edit the CI Explorer
     - Protected
   * - ``base.framework.location.*``
     - Manage locations
     - Permission
   * - ``base.framework.location.view``
     - View locations
     - Permission
   * - ``base.framework.location.add``
     - Add locations
     - Permission
   * - ``base.framework.location.edit``
     - Edit locations
     - Protected
   * - ``base.framework.location.delete``
     - Delete locations
     - Secure

IPAM, racks and ports
=====================

|licensed| — part of the IPAM feature (IPAM, racks, ports and cabling).

.. list-table::
   :header-rows: 1
   :widths: 45 40 15

   * - Right
     - Description
     - Level
   * - ``base.framework.ipam.*``
     - Manage IPAM
     - Protected
   * - ``base.framework.ipam.view``
     - View IPAM
     - Protected
   * - ``base.framework.ipam.add``
     - Add IPAM entries
     - Protected
   * - ``base.framework.ipam.edit``
     - Edit IPAM entries
     - Protected
   * - ``base.framework.ipam.delete``
     - Delete IPAM entries
     - Secure
   * - ``base.framework.rack.*``
     - Manage racks
     - Protected
   * - ``base.framework.rack.view``
     - View racks
     - Protected
   * - ``base.framework.rack.add``
     - Add racks
     - Protected
   * - ``base.framework.rack.edit``
     - Edit racks
     - Protected
   * - ``base.framework.rack.delete``
     - Delete racks
     - Danger
   * - ``base.framework.port.*``
     - Manage ports
     - Protected
   * - ``base.framework.port.view``
     - View ports
     - Protected
   * - ``base.framework.port.add``
     - Add ports
     - Protected
   * - ``base.framework.port.edit``
     - Edit ports
     - Protected
   * - ``base.framework.port.delete``
     - Delete ports
     - Danger
   * - ``base.framework.connection.*``
     - Manage port connections
     - Protected
   * - ``base.framework.connection.view``
     - View port connections
     - Protected
   * - ``base.framework.connection.add``
     - Add port connections
     - Protected
   * - ``base.framework.connection.edit``
     - Edit port connections
     - Protected
   * - ``base.framework.connection.delete``
     - Delete port connections
     - Danger

Import and export
=================

Object and type import and export each have their own right *(3.3)*. These rights have no sub-rights; ``base.system.export`` (above) covers the configuration export.

.. list-table::
   :header-rows: 1
   :widths: 45 40 15

   * - Right
     - Description
     - Level
   * - ``base.export.*``
     - Manage exports
     - Secure
   * - ``base.export.object.*``
     - Manage object exports
     - Secure
   * - ``base.export.type.*``
     - Manage type exports
     - Secure
   * - ``base.import.*``
     - Manage imports
     - Secure
   * - ``base.import.object.*``
     - Manage object imports
     - Secure
   * - ``base.import.type.*``
     - Manage type imports
     - Secure

User management
===============

Persons and person groups (contacts, not login accounts) are also covered here.

.. list-table::
   :header-rows: 1
   :widths: 45 40 15

   * - Right
     - Description
     - Level
   * - ``base.user-management.*``
     - Manage users, groups, persons and person groups
     - Secure
   * - ``base.user-management.user.*``
     - Manage users
     - Secure
   * - ``base.user-management.user.view``
     - View users
     - Secure
   * - ``base.user-management.user.add``
     - Add users
     - Secure
   * - ``base.user-management.user.edit``
     - Edit users
     - Secure
   * - ``base.user-management.user.delete``
     - Delete users
     - Secure
   * - ``base.user-management.group.*``
     - Manage groups
     - Secure
   * - ``base.user-management.group.view``
     - View groups
     - Secure
   * - ``base.user-management.group.add``
     - Add groups
     - Danger
   * - ``base.user-management.group.edit``
     - Edit groups
     - Danger
   * - ``base.user-management.group.delete``
     - Delete groups
     - Secure
   * - ``base.user-management.person.*``
     - Manage persons
     - Secure
   * - ``base.user-management.person.view``
     - View persons
     - Secure
   * - ``base.user-management.person.add``
     - Add persons
     - Secure
   * - ``base.user-management.person.edit``
     - Edit persons
     - Secure
   * - ``base.user-management.person.delete``
     - Delete persons
     - Secure
   * - ``base.user-management.personGroup.*``
     - Manage person groups
     - Secure
   * - ``base.user-management.personGroup.view``
     - View person groups
     - Secure
   * - ``base.user-management.personGroup.add``
     - Add person groups
     - Secure
   * - ``base.user-management.personGroup.edit``
     - Edit person groups
     - Secure
   * - ``base.user-management.personGroup.delete``
     - Delete person groups
     - Secure

Document Generator
==================

|licensed| — part of the Document Generator feature.

.. list-table::
   :header-rows: 1
   :widths: 45 40 15

   * - Right
     - Description
     - Level
   * - ``base.docapi.*``
     - Manage the Document Generator
     - Secure
   * - ``base.docapi.template.*``
     - Manage Document Generator templates
     - Secure
   * - ``base.docapi.template.view``
     - View Document Generator templates
     - Secure
   * - ``base.docapi.template.add``
     - Add Document Generator templates
     - Secure
   * - ``base.docapi.template.edit``
     - Edit Document Generator templates
     - Secure
   * - ``base.docapi.template.delete``
     - Delete Document Generator templates
     - Secure

ISMS
====

|licensed| — part of the ISMS feature.

.. list-table::
   :header-rows: 1
   :widths: 45 40 15

   * - Right
     - Description
     - Level
   * - ``base.isms.*``
     - Manage the ISMS
     - Permission
   * - ``base.isms.riskClass.*``
     - Manage ISMS risk classes
     - Protected
   * - ``base.isms.riskClass.view``
     - View ISMS risk classes
     - Protected
   * - ``base.isms.riskClass.add``
     - Add ISMS risk classes
     - Protected
   * - ``base.isms.riskClass.edit``
     - Edit ISMS risk classes
     - Protected
   * - ``base.isms.riskClass.delete``
     - Delete ISMS risk classes
     - Secure
   * - ``base.isms.likelihood.*``
     - Manage ISMS likelihoods
     - Protected
   * - ``base.isms.likelihood.view``
     - View ISMS likelihoods
     - Protected
   * - ``base.isms.likelihood.add``
     - Add ISMS likelihoods
     - Protected
   * - ``base.isms.likelihood.edit``
     - Edit ISMS likelihoods
     - Protected
   * - ``base.isms.likelihood.delete``
     - Delete ISMS likelihoods
     - Secure
   * - ``base.isms.impact.*``
     - Manage ISMS impacts
     - Protected
   * - ``base.isms.impact.view``
     - View ISMS impacts
     - Protected
   * - ``base.isms.impact.add``
     - Add ISMS impacts
     - Protected
   * - ``base.isms.impact.edit``
     - Edit ISMS impacts
     - Protected
   * - ``base.isms.impact.delete``
     - Delete ISMS impacts
     - Secure
   * - ``base.isms.impactCategory.*``
     - Manage ISMS impact categories
     - Protected
   * - ``base.isms.impactCategory.view``
     - View ISMS impact categories
     - Protected
   * - ``base.isms.impactCategory.add``
     - Add ISMS impact categories
     - Protected
   * - ``base.isms.impactCategory.edit``
     - Edit ISMS impact categories
     - Protected
   * - ``base.isms.impactCategory.delete``
     - Delete ISMS impact categories
     - Secure
   * - ``base.isms.protectionGoal.*``
     - Manage ISMS protection goals
     - Protected
   * - ``base.isms.protectionGoal.view``
     - View ISMS protection goals
     - Protected
   * - ``base.isms.protectionGoal.add``
     - Add ISMS protection goals
     - Protected
   * - ``base.isms.protectionGoal.edit``
     - Edit ISMS protection goals
     - Protected
   * - ``base.isms.protectionGoal.delete``
     - Delete ISMS protection goals
     - Secure
   * - ``base.isms.riskMatrix.*``
     - Manage the ISMS risk matrix
     - Protected
   * - ``base.isms.riskMatrix.view``
     - View the ISMS risk matrix
     - Protected
   * - ``base.isms.riskMatrix.edit``
     - Edit the ISMS risk matrix
     - Protected
   * - ``base.isms.threat.*``
     - Manage ISMS threats
     - Protected
   * - ``base.isms.threat.view``
     - View ISMS threats
     - Protected
   * - ``base.isms.threat.add``
     - Add ISMS threats
     - Protected
   * - ``base.isms.threat.edit``
     - Edit ISMS threats
     - Protected
   * - ``base.isms.threat.delete``
     - Delete ISMS threats
     - Secure
   * - ``base.isms.vulnerability.*``
     - Manage ISMS vulnerabilities
     - Protected
   * - ``base.isms.vulnerability.view``
     - View ISMS vulnerabilities
     - Protected
   * - ``base.isms.vulnerability.add``
     - Add ISMS vulnerabilities
     - Protected
   * - ``base.isms.vulnerability.edit``
     - Edit ISMS vulnerabilities
     - Protected
   * - ``base.isms.vulnerability.delete``
     - Delete ISMS vulnerabilities
     - Secure
   * - ``base.isms.risk.*``
     - Manage ISMS risks
     - Protected
   * - ``base.isms.risk.view``
     - View ISMS risks
     - Protected
   * - ``base.isms.risk.add``
     - Add ISMS risks
     - Protected
   * - ``base.isms.risk.edit``
     - Edit ISMS risks
     - Protected
   * - ``base.isms.risk.delete``
     - Delete ISMS risks
     - Secure
   * - ``base.isms.controlMeasure.*``
     - Manage ISMS control measures
     - Protected
   * - ``base.isms.controlMeasure.view``
     - View ISMS control measures
     - Protected
   * - ``base.isms.controlMeasure.add``
     - Add ISMS control measures
     - Protected
   * - ``base.isms.controlMeasure.edit``
     - Edit ISMS control measures
     - Protected
   * - ``base.isms.controlMeasure.delete``
     - Delete ISMS control measures
     - Secure
   * - ``base.isms.riskAssessment.*``
     - Manage ISMS risk assessments
     - Protected
   * - ``base.isms.riskAssessment.view``
     - View ISMS risk assessments
     - Protected
   * - ``base.isms.riskAssessment.add``
     - Add ISMS risk assessments
     - Protected
   * - ``base.isms.riskAssessment.edit``
     - Edit ISMS risk assessments
     - Protected
   * - ``base.isms.riskAssessment.delete``
     - Delete ISMS risk assessments
     - Secure
   * - ``base.isms.controlMeasureAssignment.*``
     - Manage ISMS control measure assignments
     - Protected
   * - ``base.isms.controlMeasureAssignment.view``
     - View ISMS control measure assignments
     - Protected
   * - ``base.isms.controlMeasureAssignment.add``
     - Add ISMS control measure assignments
     - Protected
   * - ``base.isms.controlMeasureAssignment.edit``
     - Edit ISMS control measure assignments
     - Protected
   * - ``base.isms.controlMeasureAssignment.delete``
     - Delete ISMS control measure assignments
     - Secure
   * - ``base.isms.report.*``
     - Manage ISMS reports
     - Protected
   * - ``base.isms.report.view``
     - View ISMS reports
     - Protected
   * - ``base.isms.import.*``
     - Manage ISMS imports
     - Protected
   * - ``base.isms.import.add``
     - Import ISMS entities
     - Protected

Automations
===========

|licensed| — part of the Automations feature.

.. list-table::
   :header-rows: 1
   :widths: 45 40 15

   * - Right
     - Description
     - Level
   * - ``base.openCelium.*``
     - Manage automations
     - Permission
   * - ``base.openCelium.connector.*``
     - Manage automation connectors
     - Protected
   * - ``base.openCelium.connector.view``
     - View automation connectors
     - Protected
   * - ``base.openCelium.connector.add``
     - Add automation connectors
     - Protected
   * - ``base.openCelium.connector.edit``
     - Edit automation connectors
     - Protected
   * - ``base.openCelium.connector.delete``
     - Delete automation connectors
     - Secure
   * - ``base.openCelium.connection.*``
     - Manage automation connections
     - Protected
   * - ``base.openCelium.connection.view``
     - View automation connections
     - Protected
   * - ``base.openCelium.connection.add``
     - Add automation connections
     - Protected
   * - ``base.openCelium.connection.edit``
     - Edit automation connections
     - Protected
   * - ``base.openCelium.connection.delete``
     - Delete automation connections
     - Secure

License
=======

.. list-table::
   :header-rows: 1
   :widths: 45 40 15

   * - Right
     - Description
     - Level
   * - ``base.license.*``
     - Manage the license
     - Permission
   * - ``base.license.view``
     - View the active license
     - Permission
   * - ``base.license.edit``
     - Activate or upload a license
     - Secure
   * - ``base.license.delete``
     - Remove the active license
     - Secure
   * - ``base.license.activation.*``
     - Manage license activation requests
     - Protected
   * - ``base.license.activation.view``
     - View and generate license activation requests
     - Protected
   * - ``base.license.activation.delete``
     - Delete license activation requests
     - Secure
