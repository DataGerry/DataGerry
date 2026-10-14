###########
Field types
###########

.. contents::
   :local:

The controls of the type builder and their options. How to use them is in
:doc:`../guides/model-types`; the concepts are in :doc:`../concepts/data-model`.

Where each control is available
===============================

.. list-table::
   :header-rows: 1
   :widths: 28 18 18 18 18

   * - Control
     - Type
     - Multi data section
     - Section template
     - Relation type
   * - Section
     - yes
     - —
     - (the template itself)
     - yes
   * - Multi Data Section
     - yes
     - —
     - (template option)
     - no
   * - Reference (section)
     - yes
     - —
     - no
     - no
   * - Basic controls
     - yes
     - yes
     - yes
     - yes
   * - Reference (field)
     - yes
     - yes
     - yes
     - no
   * - Location
     - once per type
     - no
     - no
     - no

Structure controls
==================

Fields can only be placed inside a structure control.

.. list-table::
   :header-rows: 1
   :widths: 22 44 34

   * - Control
     - What it is
     - Options
   * - **Section**
     - A group of fields, one value each. Shown as one block in the object view.
     - **Identifier**, **Label**.
   * - **Multi Data Section**
     - A group of fields that stores a table of entries. See :doc:`../guides/multi-data-sections`.
     - **Identifier**, **Label**.
   * - **Reference**
     - A *reference section*: shows a section of a referenced object, read-only. Its values are
       searchable like normal fields.
     - **Identifier**, **Label**, **Reference type** (the type to point to), **Section** (which
       of its sections to show), **Limit section output** (show only these fields; empty means
       all).

Field controls
==============

Common options
--------------

Most field controls share these options:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Option
     - Meaning
   * - **Required**
     - The checkbox in front of the identifier. The field must be filled in before an object can be
       saved. Since 3.3 this is also checked by the server on create and update *(3.3)*.
   * - **Identifier**
     - Required. The technical name of the field, unique within the type. Proposed automatically;
       used in the API, in imports and exports, and in document templates. The copy button puts it
       on the clipboard.
   * - **Label**
     - Required. The name shown in forms and tables.
   * - **Description**
     - A short description shown with the field.
   * - **Helper text**
     - Text of a small help popup next to the field.
   * - **Default value**
     - The value a new object starts with. Also the value existing objects get when you add the
       field to a type that already has objects.
   * - **Hide this field as column in object view/edit mode**
     - Only for fields inside a multi data section: the field is left out of the entry table but
       stays in the entry form.

Basic controls
--------------

.. list-table::
   :header-rows: 1
   :widths: 16 44 40

   * - Control
     - Stores
     - Options besides the common ones
   * - **Text**
     - A single line of text.
     - **Regex** (the value must match this regular expression), **Placeholder**.
   * - **Number**
     - A number. Other input is rejected.
     - **Regex**, **Placeholder**.
   * - **Password**
     - A secret. The value is masked; buttons reveal it, copy it to the clipboard and generate a new
       random password.
     - **Regex**, **Placeholder**.
   * - **Textarea**
     - Text over several lines.
     - **Placeholder**, **Rows** (display height).
   * - **Checkbox**
     - True or false.
     - —
   * - **Radio**
     - One of a fixed list of options, shown as radio buttons.
     - **Options** (the list of choices).
   * - **Select**
     - One of a fixed list of options, shown as a drop-down.
     - **Options**.
   * - **Date**
     - A date, chosen in a date picker.
     - Default values are typed as ``YYYY-MM-DD``. No placeholder.

Special controls
----------------

.. list-table::
   :header-rows: 1
   :widths: 16 44 40

   * - Control
     - Stores
     - Options besides the common ones
   * - **Reference**
     - A link to one object of the allowed types. The object view shows a summary of the target;
       the target lists the link under **Referenced by**. See
       :doc:`../concepts/relationships`.
     - **Reference type selections** — the types the target may have (several possible).
       **Summaries** — per allowed type, a label, a summary line and the fields to show, overriding
       the type's summary fields; use ``{}`` in the line for each field value. **Default value** —
       a preselected object.
   * - **Location**
     - The object's parent in the location tree. Only once per type; not in multi data sections
       or section templates. Its identifier is always ``dg_location``. See
       :doc:`../guides/locations`.
     - **Label**, **Selectable as location** (whether objects of this type can be the parent of
       other objects). No required, description or default value.

Locked fields
=============

Fields that come with a special type (Rack, Cable, Supernet, Subnet, VLAN) are **locked**: the type
builder shows their options read-only and they cannot be removed *(3.3)*. The fields of the
virtual **Ports** template behave the same way; for its select fields (**Status**, **Port Type**,
**Speed**) the builder offers a button to manage the list of options instead *(3.3)*. See
:doc:`../guides/ports-and-cabling`.
