#############
DataGerry 3.3
#############

DataGerry is a configuration management database (CMDB): you define the kinds of things you want
to track and their fields, and DataGerry keeps the records, their relationships and their history
— from servers and licenses to racks, cables and ISMS risks.

This documentation is organised by what you are trying to do.

**New here?** :doc:`start/introduction` explains the ideas, and :doc:`start/first-cmdb` builds a
small inventory end to end.

**Cloud or your own server?** DataGerry runs as a cloud service or on your own infrastructure.
:doc:`start/editions` explains what is different — sign-in, licensing, who operates it — and pages
throughout mark those differences with |cloud|, |selfhosted| and |licensed|. Then start with
:doc:`start/cloud-quickstart` or :doc:`start/self-hosted-quickstart`.

**Coming from 3.2?** :doc:`start/whats-new-3-3` covers racks, ports and cabling, the new import and
export options — and the rights that now guard more of the interface.

**Looking for how to do one specific thing?** The guides in the sidebar are grouped by area;
:doc:`guides/model-types` is the usual starting point.

**Need exact values?** The *Reference* section lists field types, rights, the REST API and CSV
formats.

**Running DataGerry yourself?** See :doc:`operations/requirements` and
:doc:`operations/install`. **Cloud customer?** The *Cloud* section covers the Service Portal.

.. toctree::
   :caption: Get started
   :maxdepth: 2

   start/introduction
   start/editions
   start/cloud-quickstart
   start/self-hosted-quickstart
   start/first-cmdb
   start/whats-new-3-3

.. toctree::
   :caption: Concepts
   :maxdepth: 2

   concepts/data-model
   concepts/relationships
   concepts/permissions
   concepts/isms

.. toctree::
   :caption: Model your data
   :maxdepth: 2

   guides/model-types
   guides/work-with-objects
   guides/section-templates
   guides/multi-data-sections
   guides/relations
   guides/object-groups-and-persons
   guides/assistant

.. toctree::
   :caption: Infrastructure
   :maxdepth: 2

   guides/locations
   guides/ipam
   guides/racks
   guides/ports-and-cabling
   guides/ci-explorer

.. toctree::
   :caption: ISMS
   :maxdepth: 2

   guides/isms-configure
   guides/isms-catalogues
   guides/isms-risk-assessments
   guides/isms-reports

.. toctree::
   :caption: Data in and out
   :maxdepth: 2

   guides/import-data
   guides/export-data
   guides/reports
   guides/generate-documents
   guides/file-explorer
   guides/webhooks
   guides/automations

.. toctree::
   :caption: Users and access
   :maxdepth: 2

   guides/users-and-groups
   guides/access-control
   guides/authentication
   guides/license-management

.. toctree::
   :caption: Cloud
   :maxdepth: 2

   cloud/subscriptions
   cloud/users
   cloud/api-and-automations

.. toctree::
   :caption: Self-hosted operations
   :maxdepth: 2

   operations/requirements
   operations/install
   operations/configuration
   operations/updating
   operations/backup-and-restore
   operations/troubleshooting

.. toctree::
   :caption: Reference
   :maxdepth: 2

   reference/field-types
   reference/rights
   reference/rest-api
   reference/webhook-payload
   reference/isms-csv-import
   reference/downloads
   reference/changelog

.. toctree::
   :caption: About
   :maxdepth: 1

   about/contact
   about/license

.. toctree::
   :caption: Elsewhere
   :maxdepth: 1

   Website <https://www.datagerry.com>
   Service Portal <https://service.datagerry.com>
   DataGerry Cloud <https://cloud.datagerry.com>
   Source <https://github.com/DATAGerry/DATAGerry>
   Community forum <https://community.datagerry.com>
