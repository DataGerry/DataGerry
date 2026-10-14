######################
Users, rights and ACLs
######################

.. contents::
   :local:

DataGerry decides what someone may see and do in two layers: **system rights**,
which a user gets through their group, and **access control lists (ACLs)**, which
narrow access to the objects of individual types. This page explains the model; the
tasks are in :doc:`../guides/users-and-groups` and :doc:`../guides/access-control`,
the complete list of rights in :doc:`../reference/rights`.

Users and groups
================

A **user** is a login account. Every user belongs to exactly one **user group**, and
the group alone carries the rights; you never give a right to a single user. To give
one person more or fewer rights, put them in a different group.

Two groups exist on every installation and cannot be deleted:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Group
     - Rights
   * - **Administrator**
     - The master right ``base.*``, which includes every other right.
   * - **User**
     - Full object rights (``base.framework.object.*``) and read rights for types,
       categories, logs, racks, relations, object relations, users, groups and
       Document Generator templates.

You can add as many further groups as you need, for example a read-only group or a
group for the network team.

.. admonition:: Cloud and self-hosted
   :class: edition

   In the cloud, users are managed in the Service Portal (see :doc:`../cloud/users`).
   They sign in with their email address, and DataGerry creates the user in the
   subscription the first time they sign in, as a member of the **Administrator**
   group. In 3.3 you cannot move a cloud user to another group in DataGerry; you
   can still define groups, their rights and type ACLs.
   On a self-hosted installation, you create users in DataGerry itself or let an LDAP
   directory provision them at their first login (:doc:`../guides/authentication`).
   Users sign in with their user name.

System rights
=============

A system right allows one kind of action in one area, for example
``base.framework.object.edit`` (edit objects) or ``base.framework.rack.view``
(view racks). Rights form a tree, and their names show the path through it:

::

   base.*                               everything
   base.framework.*                     the whole framework
   base.framework.object.*              everything about objects
   base.framework.object.view           only viewing objects

A right ending in ``.*`` includes every right below it. A group that holds
``base.framework.object.*`` can view, add, edit, delete and activate objects
without listing those rights one by one.

Rights decide which menus, pages, buttons and REST API routes a user can reach. In
3.3 this is applied consistently: reports, webhooks, the CI Explorer, the Document
Generator, object groups, ISMS (including ISMS import), logs, locations and search
are hidden or refused without the matching right *(3.3)*.

Access control lists
====================

An ACL belongs to a **type** and restricts the objects of that type to certain
groups. It lists groups, and for each group which of four operations it may perform:
**Create**, **Read**, **Update** and **Delete**. ACLs are off by default; while a
type's ACL is off, every group with the right system rights reaches its objects.

When the ACL of a type is active:

* A group that is not listed has no access to the objects of that type.
* A listed group may only perform the operations it is granted.
* The restriction covers every way to the objects: lists, the object view, search,
  exports and the REST API. A group without **Read** also no longer sees the type
  itself *(3.3: type lists are filtered on the server)*.
* It applies to administrators as well. ``base.*`` does not bypass an ACL.

How rights and ACLs combine
===========================

An ACL never adds access; it only takes it away. An action succeeds only if both
layers allow it:

#. The user's group holds the system right, for example ``base.framework.object.edit``.
#. If the object's type has an active ACL, the group is listed in it with the
   matching operation, here **Update**.

A group without ``base.framework.object.view`` cannot view any objects, even if
an ACL lists it with **Read**. A group with that right still cannot view objects
of a type whose active ACL does not grant it **Read**.

Premium features add a third condition on self-hosted installations: the feature
must be included in the license (:doc:`../guides/license-management`). A right
for racks or ISMS does nothing on an installation whose license does not include
IPAM or ISMS.

Safeguards
==========

DataGerry prevents a few changes that would lock everyone out:

* The **Administrator** group always keeps ``base.*``. Saving the group without it
  is refused *(3.3)*.
* The **Administrator** and **User** groups cannot be deleted.
* The initial ``admin`` user (public ID 1) cannot be deleted.
* A group cannot be deleted while it is the only group an active ACL grants access
  to, or while the LDAP settings use it as their default group or in a group
  mapping.
