##################
Users in the cloud
##################

.. contents::
   :local:

|cloud| In the cloud, user accounts live in the **Service Portal**: that is where people are
created, invited, assigned to subscriptions and removed, and where their passwords are checked.
What a user may *do* inside DataGerry is still decided in DataGerry, by groups, rights and ACLs —
see :doc:`../concepts/permissions`.

On a self-hosted installation users are managed in DataGerry instead; see
:doc:`../guides/users-and-groups`.

Roles in the Service Portal
===========================

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Role
     - Can
   * - **Cloud**
     - Sign in to DataGerry Cloud, to the subscriptions selected for them. Cannot sign in to the
       portal.
   * - **Service Portal**
     - Everything a Cloud user can, plus sign in to the Service Portal and manage company settings
       — subscriptions, users, invoices, API tokens.
   * - **Company admin**
     - One Service Portal user per company is the company admin. The role can be transferred to
       another user; the company admin cannot be deleted before transferring it.

Add a user
==========

1. In the Service Portal, open **Users** and click **Create user**.
2. Enter first name, last name and e-mail address.
3. Under **Access**, choose:

   * **Invite by email** — the user receives a link to set their own password, or
   * **Set password** — you set an initial password and pass it on; the user can change it later.

4. Choose at least one **role**.
5. Under **Subscription access**, select the subscriptions the user may sign in to, or **All
   subscriptions**.
6. Click **Create**.

Each plan allows a certain number of active users per subscription; when it is reached, the portal
shows *User limit for this subscription reached*.

Change roles and access, resend the invitation, or delete the user from the actions in the user
list. A deleted user loses access to all subscriptions immediately.

What happens in DataGerry
=========================

The first time a user signs in to a subscription, DataGerry creates a matching user record in that
instance. From then on:

* The user signs in with their **e-mail address** and portal password.
* Their name, e-mail address and password are maintained in the portal. In DataGerry's user list
  the record is read-only: there is no **Add** button and no password change.
* **Groups, rights and ACLs are managed in DataGerry**, under **Settings → Groups**, **Rights** and
  **ACL**, as on a self-hosted installation.

.. warning::
   In 3.3, every cloud user is placed in DataGerry's **Administrator** group on their first
   sign-in, and the user form — including the group — is read-only in the cloud. Every cloud user
   therefore has full rights in the subscriptions they can access. Use **Subscription access** in
   the portal to control *which* instances someone can open, and give the *Cloud* role only to
   people who may administer those instances.

Sign-in methods such as LDAP are not available in the cloud; the portal is the only identity
source. Two-factor authentication for the Service Portal is set up in each user's portal profile.
