############
Requirements
############

|selfhosted| What a self-hosted DataGerry installation needs. In the cloud, none of this applies —
see :doc:`../start/editions`.

Software
========

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Component
     - Requirement
   * - **Operating system**
     - Linux with systemd. Packages are provided for Debian/Ubuntu (DEB) and RHEL 9 and compatible
       (RPM); the ZIP package with its setup script is tested on Ubuntu 22.04 and 24.04. Docker
       images run on any Docker host.
   * - **MongoDB**
     - 7.0 or 8.0. DataGerry stores everything — including uploaded files — in one MongoDB
       database.
   * - **Reverse proxy**
     - Recommended: nginx in front of DataGerry for TLS and a standard port. Sample configurations
       are shipped; see :doc:`install`.
   * - **Browser**
     - A current version of Chrome, Edge, Firefox or Safari.

The Docker setup brings its own MongoDB and nginx containers.

Network
=======

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Port
     - Used for
   * - **80 / 443**
     - The web interface and REST API through the reverse proxy.
   * - **4000**
     - The DataGerry backend itself (``[WebServer] port`` in ``cmdb.conf``). Only needs to be
       reachable from the reverse proxy.
   * - **27017**
     - MongoDB. Only needs to be reachable from DataGerry.

For the Automations feature, DataGerry also needs to reach your OpenCelium server (default port
9090); see :doc:`configuration`.

Licensing
=========

A new installation runs as the free **Community** edition. Premium features need a license, which
is bound to the machine it is activated on — see :doc:`../guides/license-management`. Plan for
this when you move DataGerry to a different host or rebuild its container: a different machine
fingerprint means the license has to be re-issued.
