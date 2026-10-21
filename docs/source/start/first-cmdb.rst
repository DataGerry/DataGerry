##################
Your first CMDB
##################

.. contents::
   :local:

This tutorial builds a small inventory of servers end to end: a category, a *Server* type with a
handful of fields, a few objects, and a search over them. It takes about fifteen minutes and works
the same in the cloud and on a self-hosted installation. You need an instance and an account with
administrator rights — see :doc:`cloud-quickstart` or :doc:`self-hosted-quickstart`.

The concepts behind each step are explained in :doc:`../concepts/data-model`.

1. Create a category
====================

Categories are folders for types in the sidebar.

1. Open **Framework → Categories** and click **Add category**.
2. Under **Details**, enter the identifier ``infrastructure`` and the label ``Infrastructure``, and
   pick an icon. Skip **Assign types** for now and save.

The category appears in the sidebar under **Categories**. It is empty until a type is assigned.

2. Define the *Server* type
===========================

1. Open **Framework → Types** and click **Add**. The type builder opens with four steps.
2. **Basic information** — name ``server``, label ``Server``, and an icon. Click **Next Step**.
3. **Content** — drag a **Section** from *Structure Controls* onto the canvas and label it
   ``General``. Then drag these fields from *Basic Controls* into the section:

   .. list-table::
      :header-rows: 1
      :widths: 30 25 45

      * - Label
        - Control
        - Settings
      * - Hostname
        - Text
        - Mark as required.
      * - IP address
        - Text
        -
      * - Operating system
        - Select
        - Options ``Linux``, ``Windows``, ``Other``.
      * - In maintenance
        - Checkbox
        -
      * - Warranty until
        - Date
        -

   .. figure:: ../img/types/first_cmdb_content_step.png
      :width: 800

      The section *General* with its five fields in the Content step.

4. **Meta** — under *Summary*, select **Hostname** and **IP address**. Summary fields are what lists
   and references show for an object.
5. Skip **ACL** for now and click **Save** in the panel on the right.

Finally, assign the type to its category: open **Framework → Categories**, edit
*Infrastructure*, add *Server* under **Assign types**, and save.

.. tip::
   Many kinds of object share the same groups of fields — interfaces, contract data, ports. Define
   such a group once as a :doc:`section template <../guides/section-templates>` and drop it into
   every type that needs it.

3. Record a few servers
=======================

1. In the sidebar, open **Infrastructure → Server**. The object list is empty.
2. Click **Add**, fill in the fields for ``web-01``, and save.
3. Add ``web-02`` and ``db-01`` the same way. For many objects at once, use an import instead —
   see :doc:`../guides/import-data`.

Each object has its own page with the field values, a log of every change, its relations and the
files attached to it.

4. Find and change objects
==========================

* The **search bar** at the top searches across all types — try ``web``.
* In the object list, the column filters narrow the table down, for example to all servers running
  Linux. See :doc:`../guides/work-with-objects`.
* Select several objects in the list and use **bulk change** to set *In maintenance* on all of
  them in one step.

5. Change the type later
========================

Types are not fixed. Edit *Server*, add a field *Serial number*, and save: all existing servers get
the new field straight away, with its default value.

.. warning::
   This works in both directions. Removing a field from a type removes it — and the values stored
   in it — from every object of that type. See :doc:`../guides/model-types`.

Where to go next
================

* :doc:`../concepts/relationships` — connect servers to applications, racks and locations.
* :doc:`../guides/locations` and :doc:`../guides/racks` — record where things are.
* :doc:`../guides/users-and-groups` — give colleagues access with the right permissions.
