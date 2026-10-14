##############
The data model
##############

.. contents::
   :local:

DataGerry does not ship a fixed asset schema. You define what a router, a contract or a building
looks like, and DataGerry stores objects in that shape. This page explains the pieces and how they
fit together. To build them, see :doc:`../guides/model-types`.

The pieces
==========

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Piece
     - What it is
   * - **Type**
     - The blueprint for one kind of thing, for example *Router* or *Service Contract*. It defines
       which fields its objects have, how they are grouped and who may access them.
   * - **Section**
     - A group of fields inside a type, shown as one block in the object view — *Network*,
       *Warranty*. Every field lives in a section.
   * - **Field**
     - One attribute with a data type: text, number, date, a reference to another object, and so
       on. See :doc:`../reference/field-types`.
   * - **Object**
     - One real-world item, for example the router ``rtr-fra-01``. Every object belongs to exactly
       one type and holds a value for each of the type's fields.
   * - **Category**
     - A folder for types. Categories only organise the sidebar; they do not change what a type
       stores.
   * - **Section template**
     - A reusable section that you drop into several types instead of building it again. See
       :doc:`../guides/section-templates`.

The shortest possible model: one type with one section holding one field. Create objects of it and
they appear in the sidebar under the type.

Types and objects
=================

A type is a schema; objects are the records that follow it. When you open a type in the sidebar
you see a table of its objects; when you open an object you see its fields, laid out in the type's
sections.

Because objects follow their type, changing the type changes the objects. In 3.3 this happens when
you save the type *(3.3)*: a field you add appears on every object of the type, and a field you
remove disappears from every object — together with its stored values. Earlier versions marked
such a type as *unclean* and left the update of the objects to a separate **Clean** action; that
action no longer exists.

A type itself can be **active** or **inactive**. You cannot create objects of an inactive type.

Sections
--------

Fields are always placed inside a structure control. There are three:

* a **Section** — a plain group of fields, one value per field;
* a **Multi Data Section** — a group of fields that holds a whole table of entries, for example
  the network interfaces of a server. See :doc:`../guides/multi-data-sections`.
* a **Reference** section — shows a section of another, referenced object read-only inside this
  one. See :doc:`relationships`.

Summary fields
--------------

Every type names a few **summary fields** — the fields that identify an object at a glance, for a
router perhaps hostname and management IP. They are the default columns of the object list, and
they are what a reference field shows of the object it points to. You choose them in the **Meta**
step of the type.

Active and inactive objects
---------------------------

Objects can also be active or inactive. New objects are active. An inactive object stays in the
database but is hidden in the web interface until you switch the view to show inactive objects.
Use it for retired equipment you want to keep on record. See :doc:`../guides/work-with-objects`.

Categories
==========

Categories group types in the sidebar and can be nested: *Network → Switches*, *Network →
Routers*. A type belongs to at most one category; types without one are listed under
**Uncategorized**. Deleting a category never deletes types or objects.

Special types
=============

Some features need to know what a type *is*, not only what fields it has. For those, a type can
carry a **special type**, chosen once when the type is created and fixed afterwards:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Special type
     - Used by
   * - **Supernet**, **Subnet**, **VLAN**
     - IPAM — see :doc:`../guides/ipam`.
   * - **Rack** *(3.3)*
     - The rack view, where you mount objects into height units — see :doc:`../guides/racks`.
   * - **Cable** *(3.3)*
     - Port connectivity: a cable object joins two ports — see
       :doc:`../guides/ports-and-cabling`.

A special type adds the sections and fields the feature relies on. Those fields are **locked**:
the type builder shows their configuration read-only, and you cannot remove them. You can add your
own sections and fields next to them. The type list shows the special type as a badge in the type's
colour.

Special types belong to IPAM, so they are only offered when IPAM is available — in the cloud and on
self-hosted installations with a license that includes it (see :doc:`../start/editions`).

Two more capabilities are not special types but sections you add to an ordinary type:

* the **Location** control makes the type's objects placeable in the location tree — see
  :doc:`../guides/locations`;
* the **Ports** section template gives the type's objects network ports — see
  :doc:`../guides/ports-and-cabling`.

Where to go next
================

* :doc:`relationships` — the ways objects point at each other.
* :doc:`../guides/model-types` — build categories and types.
* :doc:`../guides/work-with-objects` — find, filter and change objects.
* :doc:`../reference/field-types` — every field type and its options.
