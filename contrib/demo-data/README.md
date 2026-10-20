# DATAGERRY demo landscape

`datagerry-demo.php` fills a DATAGERRY 3.3 tenant through the REST API with a complete demo CMDB for the
fictional company **Nordlicht Logistik GmbH** (Berlin headquarters, Hamburg branch office).

| Area | Content |
|---|---|
| Locations | Germany → Berlin / Hamburg → building → rooms → racks |
| IPAM | 4 supernets, 10 subnets (one IPv6), 9 VLANs, interfaces with IP/MAC/hostname on every device |
| Racks | 3 racks fully populated (devices in U slots, UPS + battery packs, side-mounted A/B PDUs, reservations, blanking panels) |
| Cabling | network cabling via copper/fibre patch panels and trunks (incl. inventoried cable objects), power cabling PSU → PDU A/B, UPS → PDU, battery packs, port ↔ IPAM interface links |
| Workplaces | 17 employees with client (user assignment, OS), monitors, workplace and default-printer relations |
| Applications | 11 applications with "runs on" / "depends on" / backup / storage / service contract relations |
| ISMS | self-defined 5×5 risk matrix, 5 impact categories, BSI threats, vulnerabilities, 17 risks, 22 ISO/IEC 27001:2022 controls, persons/groups, object groups, 19 risk assessments |
| Reports | 4 report categories, 10 reports (inventory, network/IPAM, workplaces, critical applications) |
| Document Generator | 4 templates rendered to PDF: server data sheet, workplace handover protocol (with signature lines), application profile (relations), rack inventory (embedded reports) |
| CI lists | default columns per type (type summary fields) plus a tidy personal table view for the user running the script |

The script owns its types and does not depend on how a tenant's types were built: every demo type (user,
company, client, server, switch, application, pdu, ups, ...) is **created when missing and otherwise updated to the
script's definition** (fields with stable names, sections, ports, global templates `dg-modelspec` /
`dg-ipam-interface`). Special types (supernet, subnet, vlan, rack, cable) are found by their special type and created
from the official schema when missing. Missing categories are created as well.

## Usage

```bash
php datagerry-demo.php --api=https://test-api.datagerry.com/rest \
    --user=me@example.com --password='secret' --subscription=Medium --wipe
```

- `--subscription` – cloud only: subscription name or short id (`SUB-CL-...`)
- `--wipe` – **deletes all objects, relations, ISMS data, persons and object groups of the tenant** before
  rebuilding. Without it the script refuses to run on a tenant that already contains objects.
- Options may also be passed as `DG_API`, `DG_USER`, `DG_PASSWORD`, `DG_SUBSCRIPTION`.

Requires PHP ≥ 8.1 with the `curl` and `json` extensions. A full run takes about 8–10 minutes.
