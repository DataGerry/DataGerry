.. _imports-anchor:

###########
Import data
###########

.. contents::
   :local:

The importer loads objects and types from files. It lives under **Toolbox → Importer**,
where one tile starts each import wizard. This page covers objects and types; for the
ISMS catalogues (threats, vulnerabilities, controls, risks) see
:doc:`../reference/isms-csv-import`. To produce files in the right shape, start from an
export or a CSV template — see :doc:`export-data`.

Who can import
==============

Each wizard is gated by its own right *(3.3)*: ``base.import.object.*`` for objects and
``base.import.type.*`` for types. Without the right, the tile and the route are hidden.
The ISMS imports need ``base.isms.import.add``. See :doc:`../reference/rights`.

Import objects
==============

Click **Import Objects**. The wizard *(redesigned in 3.3)* has five steps; a summary of
your choices (format, file, type, start position, maximum, overwrite) stays visible
alongside.

Supported formats are **CSV** and **JSON**. A JSON file must be a DataGerry object export
(**Toolbox → Exporter → Export Objects**, format JSON).

1. **Select file** — choose the **File format**, then drop or pick the **File**. File
   selection stays disabled until a format is chosen.
2. **File config** — parser options for the chosen format, prefilled with defaults:

   .. list-table::
      :header-rows: 1
      :widths: 20 80

      * - Option
        - Meaning
      * - **Delimiter** (CSV)
        - The delimiting character.
      * - **Newline** (CSV)
        - Empty by default. Must be ``\r``, ``\n`` or ``\r\n``.
      * - **Quote Char** (CSV)
        - The character used to quote fields.
      * - **Escape Char** (CSV)
        - The character used to escape the quote character within a field.
      * - **Header** (CSV)
        - The first row holds field names. Columns that match the type's fields are
          mapped automatically.
      * - **Encoding** (JSON)
        - Character encoding of the file.

3. **Type mapping** — **Select type** to import into. For CSV, drag the type's fields from
   the left panel onto the rows of the **Mapping** table; each row shows the CSV column
   (name or number) and a preview value. Pick another **Preview row** to check the mapping
   against other data, and use **Reset** to start over.
4. **Import config**

   * **Start import with object at place** — skip leading entries.
   * **Maximum number of objects to import** — ``0`` imports all.
   * **Update objects if Public ID exists** — overwrite an existing object with the same
     public ID instead of creating a new one. On by default; switch it off to always
     create new objects.

5. **Complete** — shows the format, file, the possible number of objects and your limits.
   Start the import. Entries that fail are listed with their submitted values and the
   reason; **View list** opens the objects of the type.

.. warning::
   Reference, location and referenced-section fields cannot be resolved from an import
   yet. The **Type mapping** step warns with **Not supported in this version** and lists
   the affected fields; their values are skipped.

CSV file format
---------------

The easiest way to get a valid file is the CSV template of the type
(**Toolbox → Exporter → Export CSV Templates**, see :ref:`export-csv-template`) or a CSV
export of existing objects. Both use the same layout, so an export can be re-imported
unchanged.

* Columns come in a fixed order: ``Public ID``, ``Active``, the type's own fields, then
  one column per multi data section field, grouped by section.
* A header reads ``Label [MDS-Section] [field_name]`` — the last bracket group is the field
  name, and the import maps the column by it. Plain ``field_name`` headers work as well;
  both notations can be mixed. Don't rename the field name part.
* An empty cell means "no value"; the field's default from the type applies.
* Quote values that contain a comma: ``"Rack 4, Row B"``.
* Booleans accept ``true``/``false``, ``yes``/``no`` and ``1``/``0``, case-insensitive.
* Dates: ``YYYY-MM-DD`` is safest; ``DD.MM.YYYY``, ``YYYY/MM/DD``, ``YYYY.MM.DD`` and the
  variants with ``HH:MM[:SS]`` also parse.
* Save as UTF-8, comma-separated, with ``"`` as quote character.
* A file with only the header row is rejected.

``Public ID`` is a grouping key, not the ID the object gets: new IDs are assigned unless
**Update objects if Public ID exists** is on. Never leave it empty on an object's first
row — a column that is blank everywhere collapses the whole file into one object.

Multi data sections in CSV
--------------------------

*(3.3)* :doc:`Multi data sections <multi-data-sections>` are imported from CSV, too. An
object spans as many rows as its largest multi data section has entries:

* The first row carries the public ID, the regular fields and the first entry of each
  section.
* Following rows leave ``Public ID`` and all regular columns empty and carry only the
  next entries.
* A row whose columns for one section are all empty adds no entry to that section.
  Entries are numbered in file order; there is no column for it.
* Give every section field its own column — don't put a whole section into one cell as
  JSON.

.. code-block:: text

   Public ID [public_id],Hostname [hostname],NIC Name [MDS-Network Interfaces] [nic_name],NIC IP [MDS-Network Interfaces] [nic_ip],Slot [MDS-Disks] [disk_slot]
   1,web-01,eth0,10.0.0.11,1
   ,,eth1,10.0.1.11,2
   ,,mgmt,192.168.50.11,
   2,db-01,,,
   3,app-01,eth0,10.0.0.13,1

JSON imports keep the multi data sections contained in the export.

Import types
============

Types are imported from a JSON file in DataGerry's type export format
(**Toolbox → Exporter → Export Types**). Click **Import Types**; the wizard has three
steps:

1. **Select file** — drop the **Type export file**. The wizard reads it and confirms it is
   ready for review.
2. **Preview** — choose how the types are applied:

   * **Create new types** — every entry is added as a new type with a fresh public ID.
   * **Update existing types** — entries are matched by public ID and replace the stored
     type. The type's objects are re-aligned with the new field set.

   The list shows every type in the file with its ID (or **Auto ID**), field and section
   count. Search it, and remove types you don't want with the trash icon.
3. **Complete** — shows how many types were imported and lists failed entries with the
   reason. **Go to types** opens the type list.

User IDs stored in the file belong to the system the types came from, so they are
ignored *(3.3)*: a created type gets the importing user as its author; an update records
the importing user as editor and keeps the stored author.
