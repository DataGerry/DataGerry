#####
Racks
#####

|licensed| — on self-hosted installations this needs a license that includes
IPAM; in the cloud it is part of the subscription. See :doc:`../start/editions`.

.. contents::
   :local:

*(3.3)* A rack is an object of the special type **Rack**. Its object view shows a
**Rack View**: an elevation of the rack in which you mount objects into height
units (U), book space with reservations and take space out of use with blockers.
Racks build on :doc:`locations`; read that page first.

.. admonition:: Cloud and self-hosted
   :class: edition

   In the cloud, the Rack View comes with the IPAM part of your subscription. On a
   self-hosted installation it is unlocked by a license that includes the IPAM
   feature. Without it, the Rack View is not shown, the special type **RACK** is
   locked in the type builder, the Start Assistant does not offer the **Rack
   View** profile, and objects of a Rack type cannot be changed. Existing rack
   objects stay readable as normal objects.

Create a rack type
==================

Either way gives you a type of special type **RACK**:

* **Start Assistant** — the **Rack View** profile creates a type **Rack** in the
  category **Hardware**. It is offered in the Telecommunications, Helpdesk,
  Service-provider and Healthcare branches. (The Location profile no longer
  creates a rack type; its hierarchy stops at the room.)
* **Type builder** — when you create a type, choose **RACK - Rack View - Rack
  class** under **Special type**. The special type can only be set when the type
  is created.

.. warning::
   Choosing **RACK** replaces the type's sections and fields with the rack
   schema. The type is also made **Selectable as location**, because mounted
   objects hang under the rack in the location tree.

A rack type has one section, **Information**:

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Required
     - Meaning
   * - **Rackname**
     - yes
     - The rack's name. Must not be blank.
   * - **Racknumber**
     - no
     - An inventory or position number.
   * - **Height**
     - yes
     - Number of height units, a whole number from 1 to 200. There is no default.
   * - **Notes**
     - no
     - Free text, also edited from the **Notes** card of the Rack View.
   * - **Location**
     - no
     - Where the rack stands (see :doc:`locations`).

Without a Rackname the rack is shown as *Rack #<Racknumber>* or *Rack #<ID>*.

Only objects whose type has the **Location** special control can be mounted. A
rack cannot be mounted into itself or into another rack.

Open the Rack View
==================

Open a rack object. The **Rack View** is part of the **Attributes** tab, below the
rack's fields. Its header holds:

* **View** — **Split** (front and rear side by side, the default), **Front** or
  **Rear**,
* **Zoom out** / **Zoom in** (80–150 %); click the percentage to reset,
* **Fullscreen**,
* **Expired** — only when reservations have run out (see below),
* **Legend** — one entry per type with its count, plus reservations and blockers
  with the units they hold,
* **Add to rack**.

Each face is headed **Front** or **Rear** with the units in use, e.g. ``12/42U``.
Slots are numbered from the bottom: slot 1 is the lowest unit. A mount is
anchored at its *top* slot and reaches down by its height, shown as e.g.
``U5–U3``. Front and rear are independent; a **Full depth** mount takes the same
units on both faces and is tagged *FULL DEPTH* in the single-face views.

Next to the faces are the **Left side** and **Right side** rails for side-mounted
objects, ordered by position.

To the right are three cards:

* the **inspector** — details of the selected entry: **Face**, **Anchor**,
  **Height**, **Occupies**, **Label**, **Booked**, **Status**, **Mount ID**, and the
  actions **Move**, **Unplace**, **Open object** and **Remove from rack**;
* **In the rack, not placed** — entries that belong to the rack but have no slot;
* **Notes** — the rack's Notes field. **Add notes** / **Edit notes**, save with
  **Save** or ``Ctrl + Enter``. Editing notes needs the right to edit objects,
  not a rack right.

Add an entry
============

Click **Add to rack**, click a free unit (it shows **+ U**\ *n* on hover; the slot
is pre-filled), or use **Add to side** on a rail. The dialog has three parts.

**Entry**

* **What holds the space** — **Mounted object**, **Reservation (space booked for
  later)** or **Blocker (space taken out of use)**. The kind cannot be changed
  later.
* **Label (optional)** — text shown on the row.
* **Object** (mounted objects only) — search for the object. **Only show objects
  that are not mounted yet** narrows the list. An object that is already in
  another rack is marked "mounted in *<rack>*"; mounting it here removes it from
  that rack (the button then reads **Replace**). An object can be in a rack only
  once — change its placement instead of adding it again.

**Placement**

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Field
     - Meaning
   * - **Area**
     - **Front**, **Rear**, **Full depth (front and rear)**, **Left side**,
       **Right side** or **Not placed yet**. Each slot area shows how many units
       are free, or *full*.
   * - **Height (U)**
     - Units the entry takes. Required for Front, Rear and Full depth; an optional
       hint for Not placed yet; not used on the sides.
   * - **Start slot**
     - The top unit of the entry. The list proposes every possible range from the
       top down (e.g. ``U22–U21``); ranges that are in use or too short are shown
       disabled ("in use", "only *n*\ U free"). This is how DataGerry suggests
       free slots.
   * - **Position (optional)**
     - Order on a side rail or in the unplaced list. Leave it empty to append.

The hint under the slot says which units the entry will occupy, and warns if the
height does not fit or the range is taken.

**Reservation window** (reservations only) — **Reserved from (optional)**,
**Reserved until (optional)** and **Colour (optional)** as a hex value such as
``#4CAF50``.

Click **Add**. DataGerry first checks the placement on the server; if it is
refused, the dialog shows **This placement was rejected** with the reasons, for
example that the slots are already occupied, the mount would reach below slot 1,
or the slot is above the rack's height.

Reservations and blockers
-------------------------

A **reservation** books units for something that is not there yet; a **blocker**
takes units out of use (a shelf, a cable tray, a broken rail). Neither names an
object, and neither may go on the side rails.

A reservation is **expired** once its *Reserved until* date has passed (the last
day still counts; no end date means it never expires). An expired reservation
keeps holding its units. It is drawn in red with "Expired *n* days ago", and the
**Expired** button in the header lists all of them with a **Release** button to
remove each.

Rearrange the rack
==================

With the edit right you can:

* **Drag** a row to another slot, face or side rail, or onto **In the rack, not
  placed**. While you drag, the target shows the range it would take or why it
  is refused ("Slots taken", "Taller than the rack", "Already here", "This area
  holds objects only" …). A full-depth row stays full depth.
* **Move** — open the edit dialog to change area, slot, height or position.
* **Unplace** — free the slots but keep the entry in the rack. It moves to **In
  the rack, not placed** and keeps its height as a hint.
* **Place** — give an unplaced entry a slot.
* **Remove from rack** — after a confirmation, remove the entry. For a mounted
  object only its membership in the rack is deleted; the object itself remains.

Racks and the location tree
---------------------------

The location tree follows *membership*, not placement:

* A mounted object gets the rack as its location, so it appears under the rack in
  the tree — also while it is unplaced. Moving it within the rack or unplacing it
  does not change the tree.
* Moving it to another rack moves its node, together with its children.
* Removing it from the rack, deleting the rack, or removing the rack's location
  removes the members from the tree.
* Setting an object's location field to a rack adds it to that rack.
* An object that has a slot cannot be moved to another location in its form:
  unplace it in the Rack View first. Racks cannot be placed inside racks.
* Deleting a mounted object removes its membership.

When the rack gets smaller
--------------------------

If you lower a rack's **Height**, entries that no longer fit are moved to **In the
rack, not placed** instead of being deleted. Entries outside the rack height are
listed in a warning ("no longer fit inside *n*\ U and cannot be drawn") with a
**Re-place** button each.

Rights
======

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Right
     - Allows
   * - ``base.framework.rack.view``
     - Seeing the Rack View and checking placements. Part of the default user
       group.
   * - ``base.framework.rack.edit``
     - Everything that changes the layout: adding, moving, unplacing, removing,
       releasing and dragging entries.

Creating and deleting rack objects uses the normal object rights. Mounted
objects you may not read are drawn as an empty slot. See
:doc:`../reference/rights`.
