################
Use ISMS reports
################

|licensed| — on self-hosted installations this needs a license that includes ISMS; in the cloud it is
part of the subscription. See :doc:`../start/editions`.

.. contents::
   :local:

The ISMS has four reports that give an overview of the risk landscape and the state of treatment, for
oversight, audits and compliance. They read from the risk assessments and control assignments described
in :doc:`isms-risk-assessments`.

Open the reports
================

Go to **Toolbox → ISMS → Reports** (needs ``base.isms.report.view``). Four cards open the reports:

* **Risk Matrix Report**
* **Statement of Applicability**
* **Risk treatment plan**
* **Risk Assessments**

The three table reports — Statement of Applicability, risk treatment plan and risk assessments — are
paged *(3.3)*: the server returns one page at a time, and you choose the page and page size below the
table.

**Export** above a table report offers **Export CSV**, **Export XLSX** and **Export PDF**. The button is
shown only if you have export rights (``base.export.type.*``). The risk matrix report has its own
**Export PDF** button.

Risk matrix
===========

The risk matrix report shows how the risk assessments are distributed over likelihood and impact. It has
three matrices:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Matrix
     - What it counts
   * - **Risk matrix – BEFORE treatment**
     - Every risk assessment by its calculated risk before treatment, i.e. its maximum impact and
       likelihood before any mitigation.
   * - **Risk matrix – CURRENT state**
     - Every risk assessment by where it stands now: assessments whose implementation state is
       *Implemented* count with their risk after treatment, all others with their risk before treatment.
   * - **Risk matrix – AFTER treatment**
     - Every risk assessment by its calculated risk after treatment — the residual risk, showing how
       effective the mitigation is.

Click a number in a cell to open the list of risk assessments behind it.

**Export PDF** exports all three matrices with their colours and layout, for audits, compliance reviews
and presentations.

Risk treatment plan
===================

The risk treatment plan lists all risk assessments with their treatment strategy and controls. It joins
data from the risk, the risk assessment, the assigned object or object group and the assigned controls.
Rows are ordered and grouped by the assessed **object or object group**, so you see per asset what has
to be done. Use it for planning, tracking implementation and preparing audits.

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Column
     - Content
   * - Risk → Name, Identifier, Category, Affected Protection Goals
     - From the risk.
   * - Risk Assessment → Object
     - The object's summary, or the object group's name.
   * - Risk Assessment → Object Type
     - The type label of the object, or *Object Group*.
   * - Risk Assessment → Risk Before Treatment
     - Coloured by risk class.
   * - Risk Assessment → Risk Treatment Option
     - *Avoid*, *Accept*, *Reduce* or *Transfer/Share*.
   * - Risk Assessment → Responsible Person
     - The person or person group responsible for the treatment.
   * - Risk Assessment → Planned Implementation Date
     -
   * - Risk Assessment → Risk After Treatment
     - Coloured by risk class.
   * - Risk Assessment → Implementation Status
     -
   * - Control/Measure → Title
     - All assigned controls, as a bulleted list in one cell.

Statement of Applicability (SoA)
================================

The Statement of Applicability lists all controls and states for each whether it applies and how far it
is implemented. It documents your control selection for ISO/IEC 27001:2022 audits and is a core part of
any ISMS documentation.

The order is fixed:

#. Controls whose source is **ISO 27001:2022** come first (if you have imported that catalogue).
#. Within that, controls are sorted by **identifier**, in natural order (``A.5.2`` before ``A.5.10``),
   so the catalogue structure is kept.
#. All other controls — from other sources or created manually — follow. Controls without an
   identifier come last.

Because the order is fixed, the SoA has no column sorting, filter or search; it is paged *(3.3)*.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Column
     - Content
   * - Title
     - The name of the control.
   * - Identifier
     - The catalogue identifier, e.g. *A.5.1*.
   * - Chapter
     - The chapter or grouping reference.
   * - Is Applicable
     - Whether the control applies in your organisation's context.
   * - Reason
     - The justification, typically when a control is not applicable.
   * - Implementation State
     - The control's overall implementation status, e.g. *Planned*, *In Progress*, *Implemented*.

The SoA shows the implementation state of the control itself, not the states of its individual control
assignments.

Risk assessments
================

The risk assessments report lists every risk assessment with all its attributes, enriched with data from
the risk and the assessed object or object group. Use it to analyse and audit the risk landscape across
all assets.

Columns
-------

* **Risk Title**, **Affected Protection Goals** (comma-separated), **Risk Category**
* **Assigned object summary** or **object group title**, and the **object type** or *Object Group*
* **Before treatment**: one column per impact category and one for the likelihood, each shown as
  ``<calculation basis> - <level>`` (e.g. ``4 - critical``, ``3 - possible``), and the **calculated
  risk**, coloured by risk class
* **Risk Assessor**, **Risk Owner**, **Interviewed Persons** (comma-separated), **Date of Risk
  Assessment**, **Additional Information**
* **Risk Treatment Option**, **Responsible Person**, **Risk Treatment Description**, **Planned
  Implementation Date**, **Implementation Status**, **Implementation Finished On**, **Required
  Resources**, **Implementation Costs**, **Priority**
* **After treatment**: the same impact, likelihood and calculated-risk columns as before treatment
* **Audit Done On**, **Auditor**, **Audit Result**

Filter and search
-----------------

*(3.3)* Filtering and search run on the server, so they cover all risk assessments, not just the
current page.

To filter, click **Add filter**, choose a criterion under **Filter by**, select one or more values and
click **Add filter**. Active filters appear as chips in the filter bar; remove one with its ×, or all
with **Clear all**. Criteria:

* Affected protection goals
* Risk category
* Risk class before treatment
* Risk class after treatment
* Risk assessor
* Risk owner
* Risk treatment option
* Responsible person
* Implementation status
* Priority

The search box above the table searches the displayed values of the report (case-insensitive).
