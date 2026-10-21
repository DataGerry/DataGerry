#########################
Ways to connect objects
#########################

.. contents::
   :local:

Objects rarely stand alone: a server sits in a rack, runs applications, has a support contract.
DataGerry offers several ways to record such links, and they differ in direction, cardinality and
what they can carry. This page compares them so you can pick the right one before you build your
types. It assumes you know :doc:`data-model`.

At a glance
===========

.. list-table::
   :header-rows: 1
   :widths: 18 22 30 30

   * - Mechanism
     - Shape
     - Defined in
     - Use it when
   * - **Reference field**
     - one object → one object
     - a field of the type
     - An attribute *is* another object: the *Manufacturer* of a device, the *Contract* of a
       server.
   * - **Reference section**
     - one object → one object, showing a whole section of it
     - a structure control of the type
     - You want to see the referenced object's details — say its *Address* section — inside this
       object, read-only.
   * - **Multi data section with reference fields**
     - one object → many objects, one per table entry
     - a multi data section of the type
     - The link is a list owned by this object, with extra columns per entry: the disks of a
       server, each with slot and size.
   * - **N:M relation**
     - many ↔ many, both directions
     - a relation type under **Framework → Relations**
     - Both sides are independent and the link itself has properties: an application *runs on*
       servers, with a deployment date.
   * - **Location**
     - one parent per object, a tree
     - the **Location** control of the type
     - Physical or logical containment: country → site → room → rack → device.
   * - **Object group**
     - one group → many objects or whole types
     - **Framework → Object Groups**
     - You need a named set of objects for ISMS, for example everything that makes up a service.

Reference fields
================

A **Reference** field stores a pointer to one object of the types you allow. In the object view
it shows the target's summary — by default the summary fields of the target's type, or a summary
line you define on the field itself. The target object lists the link under **Referenced by**.

References are the simplest link and the one to start with. They have no properties of their own
and they point one way: you edit them on the referencing object only.

Reference sections
==================

A **Reference** structure control (a *reference section*) also points to one object, but instead
of a summary it embeds one whole section of that object, or a chosen subset of its fields. The
values stay on the referenced object; you see them, you do not edit them here. Search treats them
like normal fields.

Use it to avoid copying data: an office object can show its building's address without storing
the address twice.

Multi data sections
===================

A multi data section holds a table of entries on a single object. Put a **Reference** field into
it and each row points to another object, with the other fields of the row describing that
particular link. The list belongs to the object that holds it — the targets know about it only
through **Referenced by**. See :doc:`../guides/multi-data-sections`.

N:M relations
=============

A **relation type** describes a kind of link between two groups of types: which types may be the
parent, which the child, how each side is labelled (*runs on* / *hosts*), and which extra fields a
link carries. Every individual link is then created between two objects, appears as a tab on
**both** objects and can be edited from either side.

Choose a relation over a reference when the link is many-to-many, when it needs fields of its own,
or when neither side owns it. See :doc:`../guides/relations`.

Locations
=========

The location tree records where an object is. Each object has at most one parent location, which
gives you a hierarchy you can browse in the sidebar. Types take part by carrying the **Location**
control. Racks build on it: mounting a device in a rack also places it under the rack in the tree.
See :doc:`../guides/locations` and :doc:`../guides/racks`.

Object groups
=============

An object group is a named collection, either **static** (objects you pick) or **dynamic** (every
object of the types you pick). Object groups are currently used by ISMS — risk assessments can
target a group instead of single objects. See :doc:`../guides/object-groups-and-persons`.

Which one to choose
===================

* An attribute whose value is another object → **reference field**.
* You want to display another object's data here → **reference section**.
* A list of things this object has, with details per entry → **multi data section**.
* Independent objects linked in both directions, possibly with link properties → **N:M relation**.
* Where something is → **location**.
* A set of objects to assess together in ISMS → **object group**.

The mechanisms combine freely: a server can reference its contract, sit in a rack location, list
its disks in a multi data section and run applications through an N:M relation.
