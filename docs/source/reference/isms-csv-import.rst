###############
ISMS CSV import
###############

|licensed| — on self-hosted installations this needs a license that includes ISMS; in the cloud it is
part of the subscription. See :doc:`../start/editions`.

.. contents::
   :local:

CSV formats for bulk-loading the ISMS catalogues — threats, vulnerabilities, controls and risks — for
example to start from an external standard such as the ISO/IEC 27001:2022 controls. The catalogues
themselves are described in :doc:`../guides/isms-catalogues`; the general importer in
:doc:`../guides/import-data`.

Start an ISMS import
====================

#. Go to **Toolbox → Importer**.
#. Click **Import Threats**, **Import Vulnerabilities**, **Import Controls** or **Import Risks**.
   **Show Import Instructions** on the import page repeats the format rules below.
#. Under **Select CSV File**, choose your ``.csv`` file.
#. Click the import button (e.g. **Import Threats**).

The four ISMS import buttons are shown only with the right ``base.isms.import.add`` *(3.3)*. See
:doc:`rights`.

When the import has finished, a summary shows:

* **Total Imported** — rows that are now in the database (newly created plus already existing),
* **Newly Created**,
* **Already Existing** — rows skipped as duplicates (see `Duplicates`_),
* **Invalid Entries** — rows that were rejected, with their values.

Rejected rows create nothing — not even the sources, threats or other entries they mention.

Rules for all ISMS imports
==========================

File format
-----------

* Encoding: UTF-8. A byte-order mark (as written by Excel) is fine.
* Delimiter: ``,`` (comma) or ``;`` (semicolon); it is detected automatically.
* The first row holds the column headers.
* **Every header of the format must be present**, even for optional fields — leave the cells empty
  instead. If a header is missing, the whole import is refused with
  *The following required headers are missing in the CSV: …*.
* Leading and trailing spaces in cells are ignored; a cell with only spaces counts as empty.

In the tables below, *Required* refers to the **cell value**: a row with an empty required cell is
rejected as invalid.

Mapping by name
---------------

Cells that refer to other entries — sources, implementation states, protection goals, threats,
vulnerabilities — are matched against existing entries **by name**. The match is **case-sensitive**:
``SourceA`` and ``sourcea`` are different. If no entry matches, a new one is **created** automatically.

Duplicates
----------

Before creating an entry, the import compares the row with the existing entries across **all imported
fields**, case-sensitively. An entry is created only if no identical one exists; otherwise the row is
counted as *Already Existing*. Re-importing the same CSV file therefore does not create duplicates. A row
that differs in a single field is a new entry.

Threats
=======

.. list-table::
   :header-rows: 1
   :widths: 20 12 68

   * - Header
     - Required
     - Description
   * - ``name``
     - Yes
     - The name of the threat.
   * - ``source``
     - No
     - The source of the threat, matched by name; created if it does not exist.
   * - ``identifier``
     - No
     - An identifier for the threat.
   * - ``description``
     - No
     - A description of the threat.

.. code-block:: text

   name;source;identifier;description
   Threat1;Source1;Identifier1;Description1
   Threat2;Source2;Identifier2;Description2

Vulnerabilities
===============

Same format and rules as threats.

.. list-table::
   :header-rows: 1
   :widths: 20 12 68

   * - Header
     - Required
     - Description
   * - ``name``
     - Yes
     - The name of the vulnerability.
   * - ``source``
     - No
     - The source of the vulnerability, matched by name; created if it does not exist.
   * - ``identifier``
     - No
     - An identifier for the vulnerability.
   * - ``description``
     - No
     - A description of the vulnerability.

.. code-block:: text

   name;source;identifier;description
   Vulnerability1;Source1;Identifier1;Description1
   Vulnerability2;Source2;Identifier2;Description2

Threats and vulnerabilities share one list of sources.

Controls
========

.. list-table::
   :header-rows: 1
   :widths: 25 12 63

   * - Header
     - Required
     - Description
   * - ``title``
     - Yes
     - The title of the control.
   * - ``control_measure_type``
     - Yes
     - ``CONTROL``, ``REQUIREMENT`` or ``MEASURE`` (not case-sensitive). Any other value rejects the
       row.
   * - ``source``
     - No
     - The source of the control, e.g. ``ISO 27001:2022``. Matched by name; created if it does not
       exist.
   * - ``implementation_state``
     - No
     - The implementation status, e.g. ``Planned``, ``In Progress``, ``Implemented``. Matched by name;
       created if it does not exist.
   * - ``identifier``
     - No
     - An identifier for the control.
   * - ``chapter``
     - No
     - A chapter or grouping reference.
   * - ``description``
     - No
     - A detailed explanation of the control.
   * - ``is_applicable``
     - No
     - Whether the control is applicable. True: ``true``, ``yes``, ``1``; false: ``false``, ``no``,
       ``0`` (not case-sensitive, so ``True`` and ``Yes`` work too). An empty cell means false. Any
       other value rejects the row.
   * - ``reason``
     - No
     - Why the control is or is not applicable.

.. code-block:: text

   title,control_measure_type,source,implementation_state,identifier,chapter,description,is_applicable,reason
   MC1,CONTROL,MC_SOURCE,In Progress,Identifier1,Chapter1Text,Description1,true,Reason1Text
   MC2,REQUIREMENT,MC_SOURCE2,In Progress,Identifier2,Chapter2Text,Description2,no,Reason2Text

Controls with the source ``ISO 27001:2022`` lead the Statement of Applicability
(:doc:`../guides/isms-reports`).

Risks
=====

.. list-table::
   :header-rows: 1
   :widths: 22 12 66

   * - Header
     - Required
     - Description
   * - ``name``
     - Yes
     - The name of the risk.
   * - ``risk_type``
     - Yes
     - ``THREAT_X_VULNERABILITY``, ``THREAT`` or ``EVENT`` (not case-sensitive). An empty or unknown
       value rejects the row. Decides which other cells are required — see below.
   * - ``protection_goals``
     - No
     - The affected protection goals by name, comma-separated, e.g. ``Confidentiality,Integrity``.
   * - ``threats``
     - Depends on type
     - The threats by name, comma-separated.
   * - ``vulnerabilities``
     - Depends on type
     - The vulnerabilities by name, comma-separated.
   * - ``identifier``
     - No
     - An identifier for the risk.
   * - ``consequences``
     - Depends on type
     - What happens if the risk materialises.
   * - ``description``
     - Depends on type
     - A detailed explanation of the risk.

Protection goals, threats and vulnerabilities are mapped by name (`Mapping by name`_); names that do not
exist yet are created as new protection goals, threats or vulnerabilities.

The ``risk_type`` decides which cells must be filled and which must stay empty. A row that breaks these
rules is rejected:

.. list-table::
   :header-rows: 1
   :widths: 28 18 18 18 18

   * - ``risk_type``
     - ``threats``
     - ``vulnerabilities``
     - ``consequences``
     - ``description``
   * - ``THREAT_X_VULNERABILITY``
     - required
     - required
     - must be empty
     - optional
   * - ``THREAT``
     - required
     - must be empty
     - must be empty
     - optional
   * - ``EVENT``
     - must be empty
     - must be empty
     - required
     - required

The CSV has no column for the risk **category**. Imported risks have no category; set it in the risk
form afterwards (the form requires one when you save).

.. code-block:: text

   name;risk_type;protection_goals;threats;vulnerabilities;identifier;consequences;description
   Risk1;THREAT;Confidentiality,Integrity;Fire,Water;;Identifier1;;Description1
   Risk2;EVENT;Integrity;;;Identifier2;Consequences2;Description2

.. note::
   The lists in ``protection_goals``, ``threats`` and ``vulnerabilities`` are separated by commas. Use
   ``;`` as the delimiter, as in the example, or put such cells in double quotes when the file is
   comma-delimited.
