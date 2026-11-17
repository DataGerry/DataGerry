####################
What's new in 3.3
####################

.. contents::
   :local:

3.3 adds the physical layer to the CMDB — racks, ports, cables — and makes rights apply
consistently across the interface. This page summarises what changes for you; the complete list,
including every bug fix, is in the :doc:`changelog <../reference/changelog>`.

The 3.3.x releases after 3.3.0 are cloud releases: each finished feature reaches the cloud first
and self-hosted installations with 3.4. See :doc:`editions` for the release schedule.

3.3.2 — ISMS control catalogs
=============================

|since-332| |licensed|

* **Control catalogs.** The ISMS ships with ready-made control catalogs in the OSCAL format —
  among them ISO/IEC 27001:2022 Annex A, NIST SP 800-53, NIST CSF 2.0, the EU NIS2 requirements
  and several BSI catalogs. Import a catalog, and its controls become ISMS controls you can assess,
  assign and report on in the Statement of Applicability.
* **OSCAL view.** Browse a catalog before or after importing it: families, controls with their
  statements and guidance, parameters, enhancements and metadata.
* **Update.** A later import of the same catalog adds new controls and updates existing ones.

See :doc:`../guides/isms-control-catalogs`.

3.3.1 — Choose your data model
==============================

|since-331|

* **New start assistant.** On a fresh instance the assistant now lets you pick **best practice
  data models** — for example *Data Center & Servers*, *Network Infrastructure* or *Software &
  Licenses* — and combine several of them. Shared types such as companies or persons are created
  once.
* **Which models do I need?** A helper suggests models from what you want to achieve.
* **Your plan.** In the cloud the assistant shows your subscription plan and which features it
  includes.
* **Import a data model** from a file instead of choosing a best practice model.
* **Reset workspace.** Administrators can reset an instance to an empty data model and run the
  assistant again.

See :doc:`../guides/assistant`.

3.3.0
=====

Racks, ports and cabling
------------------------

|licensed| These features belong to the IPAM license feature: on a self-hosted installation they
need a license that includes IPAM; in the cloud they are included.

**Rack view.** A new special type *Rack* gets a rack view in its object page. Mount objects by
area, start slot and height, switch between front and rear, drag mounts to move them, and reserve
or block slots. DataGerry checks every placement before it is saved and suggests free slots.
See :doc:`../guides/racks`.

**Ports and patch panels.** Any type can get a *Ports* section from a built-in section template.
Create many ports at once with a naming scheme, link ports to the object's interfaces, and keep
patch panels in the same model. See :doc:`../guides/ports-and-cabling`.

**Cables and the cabling view.** A new special type *Cable* connects two ports. A wizard connects,
edits and disconnects cables, and the object page can switch between a table, a cabling diagram
with cables in their real colours, and a graph. The CI Explorer can follow port connections too.

Data model and builder
----------------------

* Types, relations and section templates are now edited in one common builder. The stepper shows
  which steps are still invalid.
* *Virtual* global section templates — such as *Ports* — are provided by DataGerry rather than
  stored, and can be cloned into your own templates. See :doc:`../guides/section-templates`.
* A type can consist of the Ports section alone.
* The type list shows a badge for special types (Rack, Cable, …).
* Required fields are now also enforced by the server when an object is created or changed.

Locations
---------

The location tree in the sidebar loads lazily, can be searched, and supports drag and drop to
move one or several locations. The location field uses a tree selector. See
:doc:`../guides/locations`.

Imports and exports
-------------------

* Multi data sections are included in object exports and can be imported from CSV.
* CSV and XLSX exports can be **human readable**, and exports use field labels as column headers.
  Human-readable files are meant for people and cannot be imported again.
* Export an empty CSV template for a type to prepare an import.
* The import wizards for objects and types were redesigned, with clearer validation messages.

See :doc:`../guides/import-data` and :doc:`../guides/export-data`.

Rights
------

Reports, webhooks, CI Explorer, Document Generator, object groups, ISMS (including the ISMS
import), logs, locations, search, import and export are now consistently controlled by rights —
menus, pages and actions a user may not use are hidden. New rights cover racks
(``base.framework.rack.*``) and locations.

.. admonition:: Check your groups after the update
   :class: note

   Groups that worked before may now miss a right they need — for example to open reports or the
   CI Explorer. Review your groups against :doc:`../reference/rights` after updating.

ISMS
----

The SoA, Risk Assessments and Risk Treatment Plan reports are paginated, the Risk Assessments
report filters on the server, and risks, threats and controls can be deleted in bulk. A risk
assessment can no longer be saved with required fields missing. See
:doc:`../guides/isms-reports`.

Interface
---------

New dialogs and buttons throughout, Font Awesome 6 icons, a colour picker that works in Firefox, a
sidebar that remembers whether it is collapsed, and server-side search in tables and selects.
License tiers are shown as *Small*, *Medium* and *Large*.

Upgrading
---------

|selfhosted| Install the new release as described in :doc:`../operations/updating`; the database
is migrated on start. Back up first. |cloud| Cloud subscriptions are updated by becon.
