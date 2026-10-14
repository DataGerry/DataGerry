#################
Ports and cabling
#################

|licensed| — on self-hosted installations this needs a license that includes
IPAM; in the cloud it is part of the subscription. See :doc:`../start/editions`.

.. contents::
   :local:

*(3.3)* Objects can have **ports** — as a standard network device or as a
**patch panel** — and you record which port is cabled to which. Cables can be
described on the connection or kept as objects of their own. The **Cabling
View** draws the result. This page assumes you know how to build types
(:doc:`../guides/model-types`).

.. admonition:: Cloud and self-hosted
   :class: edition

   In the cloud, port connectivity comes with the IPAM part of your
   subscription. On a self-hosted installation it needs a license that includes
   the IPAM feature. Without it, the **Ports** section template is not offered in
   the type builder, the Ports section of an object shows "Port Connectivity is a
   Pro feature" with **Upgrade to unlock**, and there is no **Cabling View**. With
   an expired license, existing ports can still be viewed and edited, but no new
   ones added.

Give a type ports
=================

Ports come from the predefined section template **Ports**. It is a *virtual*
template: its fields are fixed and not stored on the type.

#. Open the type in the type builder.
#. From **Global Section Templates**, drag **Ports** onto the canvas, at the
   position where the section should appear among the type's sections.
#. Save the type.

A type may consist of the Ports section alone. You cannot remove the section
while objects of the type still have ports ("Ports are still in use"); delete the
ports first.

Whether an object is a standard device or a patch panel is not set on the type —
you choose it per object when you add its first ports.

Port fields and option lists
----------------------------

A port has **Name** (required), **Port Number**, **Status**, **Port Type**,
**Speed** and **Description**. Port names must be unique on each side of an
object.

**Status**, **Port Type** and **Speed** are selection lists shared by all types.
They come with predefined values, which cannot be changed or deleted:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - List
     - Predefined values
   * - Status
     - Up, Down, Disabled
   * - Port Type
     - RJ45, SFP, SFP+, SFP28, QSFP+, QSFP28, QSFP56, QSFP-DD, OSFP, LC, SC, ST,
       MPO/MTP
   * - Speed
     - 10M, 100M, 1G, 2.5G, 5G, 10G, 25G, 40G, 50G, 100G, 200G, 400G, 800G
   * - Cable type
     - Cat5e, Cat6, Cat6a, Cat7, Cat7a, Cat8, OM1, OM2, OM3, OM4, OM5, OS1, OS2,
       DAC, AOC

To add your own values, select the field in the Ports section in the type
builder and click **Manage Statuses**, **Manage Port Types** or **Manage
Speeds**. Enter a name and click **Add**; your own entries can be edited and
deleted, predefined ones are marked **Predefined**. Cable types cannot be
managed from the interface.

Add ports to an object
======================

Ports are managed on the object's **Edit** page; the object view shows them
read-only. A new object must be saved before ports can be added. Port changes
are saved right away, even if you do not save the object.

In the **Ports** section, click **Add**. The **Add ports** assistant has four
steps.

#. **Device type** — **Patch panel** (front and rear ports, paired
   automatically) or **Standard network device** (single ports, no internal
   pairing). An object is one or the other; to switch, delete all its ports
   first.
#. **Count & numbering** — **How many ports** and **Start counting at**. For a
   patch panel the count is per side: 24 means 24 front and 24 rear ports. Set
   **Port type**, **Speed**, **Status** and **Description** for all new ports;
   a panel's rear ports take type and status from the front unless you set them
   under **Rear ports**.
#. **Naming** — a name pattern, numbered for you (see below), plus **Prefix
   (optional)** and **Slot (optional)**. A patch panel needs different patterns
   for front and rear.
#. **Preview & create** — the generated names. Nothing is created until you
   click **Create ports**. The preview flags names that would be generated twice
   or already exist on the object.

At most 5000 ports (per side) can be created in one batch. On a patch panel each
front port is paired with the rear port of the same position.

Name patterns
-------------

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Token
     - Replaced by
   * - ``{n}``
     - The running number. ``Gi0/{n}`` gives Gi0/1, Gi0/2 … The number also
       becomes the port number.
   * - ``{n:02}``
     - The number padded with zeros to that many digits (up to 10): 01, 02 …
   * - ``{prefix}``
     - The **Prefix** value.
   * - ``{slot}``
     - The **Slot** value.

Other tokens are rejected. Default patch-panel patterns are
``{prefix}-F{n:02}`` (front) and ``{prefix}-R{n:02}`` (rear).

Work with ports
===============

Port tables
-----------

A standard device shows a table with **Port Name**, **Port No.**, **Port Type**,
**Speed**, **Status**, **Connection**, **Interfaces** and **Actions**. A patch
panel shows **No.**, **Front Port**, **Front Connection**, **Pairing**, **Rear
Port**, **Rear Connection** and **Actions**.

**Connection** shows *Free* or the cable, marked **Metadata** (described on the
connection) or **CI #**\ *id* (a cable object), and the far end.

You can show and hide columns. On the object view the column choice is saved per
user, separately for the two tables, and applies to all objects.

Row actions
-----------

The row menu offers **Connect**, **Edit cable**, **Disconnect**, **Manage
interfaces**, **Edit port** and **Delete port**. Deleting a port also removes its
connection and interface links.

Bulk actions
------------

Select ports with the check boxes; the buttons are enabled once a port is
selected.

* **Bulk Change** — write **Status**, **Port type**, **Speed** and
  **Description** to all selected ports. Only the fields you switch on are
  written; a field switched on but left empty is cleared.
* **Disconnect Selected** — cut the cables of the selected ports. The ports stay;
  a patch panel's internal pairing is never cut.
* **Delete Selected** — delete the selected ports, with their connections and
  interface links. This cannot be undone.

Link ports to interfaces
------------------------

If the object also has the IPAM **Interfaces** section (see :doc:`ipam`), a port
can carry interfaces. **Manage interfaces** opens a dialog: choose the
**Interface** (search by IP, MAC, host name or subnet) and a **Relation type** —
Physical, Bond, VLAN, Virtual or Other — and click **Link interface**. Several
ports may share an interface. **Unlink interface** removes only the link, not
the port or the interface. Linked interfaces appear in the **Interfaces**
column.

Connect ports
=============

Choose **Connect** on a port. The wizard has these steps:

#. **Endpoints** — **Device at the far end** and **Port at the far end**. Only
   devices with ports are listed, and ports that already have a cable are not
   offered.
#. **Cable management** — **Metadata only** (the cable is described on the
   connection) or **Link a cable CI** (the cable is its own object, see below).
#. **Cable** (metadata only) — **Cable name**, **Cable type**, **Length**,
   **Color** and **Description**.
#. **Review** — click **Connect ports**.

Rules:

* A port cannot be connected to itself, and a cable joins two different objects.
* Each port holds one cable (and, on a patch panel, its internal pairing).
* A connection has either cable metadata or a cable CI, never both.
* The ends of a connection cannot be changed. To re-cable, disconnect and
  connect again. **Edit cable** changes only the cable data.

A patch panel's front-to-rear pairing is created automatically, carries no cable
and cannot be edited.

Cable objects
-------------

To keep cables as CIs with serial numbers, cost and history, create a type with
the special type **CABLE - Port Connectivity - Cable class**. Only one such type
can exist. Its section **Information** holds **Cable name** (required), **Cable
type**, **Length**, **Color** and **Description**.

When connecting with **Link a cable CI**, the cable picker offers only cables
that are not used by another connection. The connection then takes type, length
and colour from the cable object. A cable that is still used by a connection
cannot be deleted ("Cable is still in use"); disconnect it first.

Copy an object with its ports
-----------------------------

When copying an object, tick **Also copy the ports of this object**. A patch
panel's internal pairings are copied; cables and interface links are not.

Cabling View
============

Objects whose type has the Ports section get a **Cabling View** button in the
view switch at the top right of the object view, next to **Table View** and
**Graph View** (the CI Explorer, :doc:`ci-explorer`). The chosen view is kept in
the URL.

The view draws the object (marked with a crown) and the objects cabled to it as
cards, with cables in their real colour. Hover a cable for its name, type, ends
and description.

* **Show free ports** — off by default, so only connected ports are shown.
* Each card shows a few ports; **more ports** unfolds the rest.
* **Show far end** on a port loads the next object along that cable.
* **Open the cabling of** *<name>* switches to that object's cabling view.

Navigate with the toolbar or the keyboard: drag to pan or move cards, ``+`` /
``-`` or ``Ctrl`` + mouse wheel to zoom, ``0`` (**Fit to screen**) to fit,
arrow keys to pan, **Full screen** to use the whole screen.

**Spotlight**: press ``S`` or the spotlight button, then click a port. The port,
its cable and the path back to this object stay highlighted, everything else
fades. Press ``S`` again to turn it off.

Rights
======

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Right
     - Allows
   * - ``base.framework.port.view`` / ``add`` / ``edit`` / ``delete``
     - Seeing, creating, changing and deleting ports. ``view`` is needed for the
       Cabling View; ``add`` for copying ports with an object; ``edit`` and
       ``delete`` also for linking and unlinking interfaces.
   * - ``base.framework.connection.view`` / ``add`` / ``edit`` / ``delete``
     - The same for port connections.

Changes also need the right to update the owning object. See
:doc:`../reference/rights`.
