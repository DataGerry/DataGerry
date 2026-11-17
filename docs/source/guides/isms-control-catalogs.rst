.. _isms-catalogs-anchor:

###################################
Control catalogs and the OSCAL view
###################################

|since-332| |licensed| — on self-hosted installations this needs a license that includes ISMS; in
the cloud it is part of the subscription. See :doc:`../start/editions`.

.. contents::
   :local:

DataGerry ships a set of security control catalogs — ISO/IEC 27001 Annex A, NIST, BSI and NIS2.
You can read each one in a built-in OSCAL viewer and import its requirements as ISMS controls,
so you do not have to type a standard in by hand. This page assumes you know the ISMS building
blocks from :doc:`../concepts/isms`. Controls themselves are described in
:ref:`isms-controls-anchor`.

.. admonition:: Cloud and self-hosted
   :class: edition

   Catalogs and the OSCAL viewer are in the cloud from 3.3.2. Self-hosted installations get them
   with 3.4. Until then, a self-hosted 3.3 installation has no **Catalogs** card, and its controls
   page opens the plain list of all controls. Add controls by hand or with the
   :doc:`../reference/isms-csv-import` there.

What a catalog is
=================

A **catalog** is a published list of security requirements, such as the ISO/IEC 27001:2022
Annex A controls or NIST SP 800-53. Each catalog is an **OSCAL** document, the open format for
control catalogs described in :doc:`../concepts/isms`. A catalog contains:

* **groups** (the viewer calls them *control families*), such as *A.5 Organizational controls*
  or *Access Control*. Groups can contain sub-groups.
* **controls**, each with an ID, a title and a label such as ``A.5.1`` or ``AC-1``. A control
  can have **control enhancements**, which are nested controls.
* **parts**: the text of a control, split into a *statement* (what is required), *guidance*,
  *examples* and an *assessment method*.
* **parameters**: placeholders in the statement that you fill in for your organisation, for
  example "organization-defined personnel or roles".

The catalogs are bundled with DataGerry and are read-only. You cannot upload your own catalog
or edit a bundled one. A new or updated catalog version arrives with a DataGerry update. The
catalogs and the viewer are served by your DataGerry instance itself, so viewing a catalog does
not send data anywhere else.

Bundled catalogs
================

.. list-table::
   :header-rows: 1
   :widths: 38 12 18 10 10 12

   * - Title
     - Publisher
     - Version
     - Language
     - Controls
     - License
   * - Anwenderkatalog Grundschutz++
     - BSI
     - 2026-09-24
     - de
     - 1,000
     - CC-BY-SA-4.0
   * - Supply Chain Security (Lieferkettensicherheit)
     - BSI
     - 2026-09-24
     - de
     - 146
     - CC-BY-SA-4.0
   * - Stand der Technik WLAN
     - BSI
     - 2026-09-24
     - de
     - 48
     - CC-BY-SA-4.0
   * - NIST SP 800-53 Rev. 5.2.0 Controls and SP 800-53A Assessment Procedures
     - NIST
     - 5.2.0
     - en
     - 1,196
     - Public Domain (CC0-1.0)
   * - NIST Cybersecurity Framework 2.0
     - NIST
     - 2.0 (OSCAL 1.2.0)
     - en
     - 219
     - Public Domain (CC0-1.0)
   * - NIS2 (Richtlinie (EU) 2022/2555 und DVO (EU) 2024/2690)
     - EU
     - 2022/2555 + 2024/2690
     - de
     - 180
     - EU legal text (reuse permitted)
   * - ISO/IEC 27001:2022 Anhang A (Control-Titel)
     - ISO/IEC
     - 2022
     - en
     - 93
     - Titles only (text © ISO)

The ISO/IEC 27001 catalog contains only the control numbers and titles. The control text is
copyrighted by ISO. Each control in the viewer says so, and controls imported from this catalog
have no description. Copy the text from your licensed copy of the standard if you need it.

The catalog list
================

Open **Toolbox → ISMS** and click the **Catalogs** card. You need ``base.isms.controlMeasure.view``.
The list has search, paging and these columns:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Column
     - Content
   * - **Title**
     - The catalog name. Click it to open the catalog in the viewer.
   * - **Publisher**, **Version**, **Language**
     - Taken from the catalog.
   * - **Controls**
     - How many controls the catalog has.
   * - **Imported**
     - If no controls have been imported from this catalog yet, this column shows **Import**. Once
       they are, it shows how many controls were imported (a link to them), plus **Update** and a
       delete icon.
   * - **Size**
     - The size of the catalog file.
   * - **License**
     - The catalog's license. Click it to read the license text.
   * - **Actions**
     - **View catalog**, **Open in new tab**, **Download OSCAL JSON** and **Show imported
       controls**.

Below the table, a line credits the viewer and the copyright holders of the catalog content.

Browse a catalog in the OSCAL view
==================================

Click a catalog title or the **View catalog** icon. The page shows the catalog title with
**Back**, **Download** and **New Tab** buttons. Below that is a line with the publisher, version,
number of controls and license. The viewer fills the rest of the page. **New Tab** opens the same
viewer full-screen in a separate browser tab.

The viewer has a navigation pane on the left, with a **Search controls** box. It lists:

* **Overview** — the catalog's version, OSCAL version, publication and last-modified dates, plus
  counters for **Control Families**, **Total Controls**, **Active Controls**, **Withdrawn** and
  **Back Matter Resources**.
* **Metadata** — the document information (**Title**, **Version**, **Published**, **Last
  Modified**, **OSCAL Version**), with **Roles**, **Parties** and **Responsible Parties** where
  the catalog has them.
* The **control families** (groups), which you can expand to their sub-groups and controls. A
  family page shows its **Family ID** and how many **Controls** and **Sub-Groups** it has, plus
  **Total (incl. enhancements)**.
* **Back Matter** — the documents and resources the catalog cites.

A control page shows the control's label and title, then one block for each part the control has:
**Overview**, **Statement**, **Guidance**, **Examples** and **Assessment Method**. Parameters are
filled into the text as ``[Assignment: …]`` or ``[Selection: …]``. The page also lists the
control's **Properties**, its links to related controls and resources, and its **Control
Enhancements**. A withdrawn control is marked **Withdrawn** ("This control has been withdrawn.").

**Download** (or **Download OSCAL JSON** in the list) saves the catalog as an OSCAL JSON file.
You can use that file in other OSCAL tools.

Import a catalog as controls
============================

Importing turns the requirements of a catalog into ISMS controls. You can then assess,
implement and report on them like any other control.

#. In the catalog list, click **Import** in the catalog's **Imported** column. This needs
   ``base.isms.controlMeasure.add``.
#. Confirm **Import requirements as controls**.

DataGerry creates one control for every control in the catalog, control enhancements included.
Withdrawn controls are left out. Each new control gets these values:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Control field
     - Value from the import
   * - **Name**
     - The control's title. If the catalog has no separate title, DataGerry uses the first line of
       the statement, cut to 120 characters.
   * - **Type**
     - *Requirement*
   * - **Identifier**
     - The control's label, e.g. ``A.5.1`` or ``AC-1``. If the label contains spaces, DataGerry
       uses the control ID from the catalog.
   * - **Source**
     - The catalog title, e.g. *NIST Cybersecurity Framework 2.0*. DataGerry creates this source if
       it does not exist yet.
   * - **Chapter**
     - The group path, joined with ``/``, e.g. *Access Control*. For a control enhancement the
       parent control's identifier is added to the path.
   * - **Description**
     - The statement text, with parameters filled in as ``[…]``. Guidance is not imported. Empty
       for the ISO/IEC 27001 catalog.
   * - **Is Applicable?**
     - No
   * - **Reason for inclusion/exclusion**
     - Empty
   * - **Implementation State**
     - *None*. DataGerry creates this state if it does not exist yet.

When the import is finished, a notification says how many controls were added. The **Imported**
column then shows that number.

Each imported control remembers its catalog. DataGerry sets this link only when it imports a
catalog. You cannot add it to a control you create yourself.

After the import, edit each control to set **Is Applicable?**, the reason and the implementation
state. Then link the controls to risk assessments like any other control (see
:doc:`isms-risk-assessments`).

Find imported controls
======================

The **Controls** page *(3.3.2)* starts with a card for each catalog and a **Custom controls**
card ("Controls created by hand or via CSV import"). Each card shows how many controls it has, or
**No controls yet**. Click a card to list its controls. **Change catalog** takes you back to the
cards. **Show imported controls** in the catalog list, and the number in the **Imported** column,
open the same list directly.

Update imported controls
========================

A DataGerry update can bring a newer version of a catalog. To bring your imported controls up to
date, click **Update** in the catalog's **Imported** column. This needs
``base.isms.controlMeasure.add``. The update matches controls by catalog and identifier:

* Requirements that are new in the catalog are added as new controls.
* For existing controls, only **Name**, **Chapter** and **Description** are updated, and only
  where the catalog text changed. **Is Applicable?**, the reason, the implementation state and the
  source stay as you set them.
* Controls that are no longer in the catalog are **kept**. A notification lists their
  identifiers, so you can review or delete them yourself.

The notification says how many controls were added, updated and left unchanged.

.. note::
   The catalog owns **Name**, **Chapter** and **Description**. If you change these fields on an
   imported control, the next **Update** overwrites your change whenever it differs from the
   catalog.

If an import or update fails partway, run it again. It continues where it stopped and does not
create duplicates.

Delete imported controls
========================

Click the delete icon in the catalog's **Imported** column and confirm **Delete imported
controls**. You need ``base.isms.controlMeasure.delete``. Controls that are used in a control
assignment of a risk assessment are kept, and a notification says how many. The applicability,
reason and implementation state of the deleted controls are lost. If you import the catalog
again later, they start with the default values again.

Catalogs and the Statement of Applicability
===========================================

The Statement of Applicability lists **every** control, so imported controls appear in it too
(see :doc:`isms-reports`). A freshly imported control shows **Is Applicable** *No* and the
implementation state *None* until you edit it. Large catalogs such as NIST SP 800-53 add more than
a thousand rows. Import only the catalogs whose requirements you want to answer.

Rights
======

Catalogs have no rights of their own. They use the control rights:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Right
     - Allows
   * - ``base.isms.controlMeasure.view``
     - The **Catalogs** card, the catalog list, the viewer and the download
   * - ``base.isms.controlMeasure.add``
     - **Import** and **Update**
   * - ``base.isms.controlMeasure.delete``
     - Deleting the imported controls of a catalog

See :doc:`../reference/rights`.
