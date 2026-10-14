################################
Service Portal and subscriptions
################################

.. contents::
   :local:

|cloud| Everything about your cloud contract — subscriptions, users, invoices, API keys and
support — is managed in the **Service Portal** at
`service.datagerry.com <https://service.datagerry.com>`_. DataGerry itself is at
`cloud.datagerry.com <https://cloud.datagerry.com>`_. For how the cloud differs from a
self-hosted installation, see :doc:`../start/editions`.

Only users with the *Service Portal* role can sign in to the portal; see :doc:`users`.

The portal at a glance
======================

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Menu
     - What it is for
   * - **Dashboard**
     - Your subscriptions, open invoices, recent activity and service status.
   * - **Reports**
     - Usage of your subscriptions, per subscription or combined.
   * - **Subscriptions**
     - Your subscriptions, their plan, status and renewal; cancel a subscription.
   * - **Users**
     - Who may sign in to DataGerry and to the portal. See :doc:`users`.
   * - **Invoices**
     - All invoices, downloadable as PDF.
   * - **Cloud settings**
     - Instance details, API tokens and automation master passwords. See
       :doc:`api-and-automations`.
   * - **Support**
     - Open and follow support tickets.
   * - **User profile**
     - Your name, password, language and two-factor authentication.
   * - **Documentation**
     - Opens this documentation.

The **Open Cloud** link takes you to DataGerry.

What a subscription is
======================

A subscription is **one DataGerry instance with its own database**. Data is never shared between
subscriptions, so one account can run several separate CMDBs — a test and a production instance,
or one per business unit. When you sign in to DataGerry with an account that has access to more
than one subscription, you choose the subscription on the login page.

Each subscription has a **plan**. The plan sets:

* the **number of objects** (CIs) the instance can hold,
* the **number of active users**,
* the number of **professional support** cases per year,
* whether **API tokens** can be created for it.

All DataGerry features — including IPAM, racks and cabling, ISMS, the Document Generator and
Automations — are available in every cloud plan. Current plans and prices are listed on
`datagerry.com <https://www.datagerry.com>`_.

The object limit
----------------

DataGerry shows the current count and the limit in its top bar, for example
*Objects 9,412 / 10,000*. When the limit is reached, creating an object — by hand, by copying or
by import — is refused with the message *The maximum amout of ConfigItems is reached!*. Existing
objects can still be edited and deleted. Delete objects you no longer need or move to a larger
plan.

Trial
=====

A trial started at `service.datagerry.com/demo <https://service.datagerry.com/demo>`_ is a full
subscription with every feature, free of charge, for 14 days. It does not renew automatically. To keep working with your data,
order a subscription in the portal before the trial runs out, or contact the DataGerry team via
**Support**.

Cancel a subscription
=====================

In **Subscriptions**, choose **Cancel** on the subscription. The cancellation is sent to becon as a
request; the subscription stays active until becon confirms it, and shows *Cancellation
requested* in the meantime.

.. warning::
   Once the subscription has ended you can no longer sign in to its instance. Export the types
   and objects you want to keep beforehand — see :doc:`../guides/export-data`.

Invoices
========

**Invoices** lists every invoice with number, date and amount. Download any of them as PDF.

Support
=======

**Support** opens tickets with the DataGerry team and lists your own and — for company admins —
all tickets of your company. Choose the request type:

* **Professional Support** — help with your instance; counts against the support cases in your
  plan.
* **Feature Request**
* **Fix a bug**

Your profile
============

Open your profile from your name at the bottom of the portal sidebar. Here you change your
personal details, your password (it is also your DataGerry password), the portal language, and
set up **two-factor authentication** with an authenticator app.

Forgot your password? Use **Forgot Password?** on the DataGerry or portal sign-in page.
