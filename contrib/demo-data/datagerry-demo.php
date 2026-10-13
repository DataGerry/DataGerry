<?php
/**
 * DATAGERRY 3.3 demo landscape generator - "Nordlicht Logistik GmbH"
 *
 * Builds a complete, realistic CMDB demo via the REST API:
 *   locations (Germany -> Berlin/Hamburg -> building -> room -> rack), IPAM (supernets, subnets, VLANs,
 *   interfaces), fully populated racks incl. side-mounted PDUs and UPS, network + power cabling, workplaces
 *   (user -> client -> monitors), operating systems, applications, object relations and a configured ISMS
 *   (custom 5x5 risk matrix, threats, vulnerabilities, risks, ISO 27001 controls, risk assessments).
 *
 * Usage:
 *   php datagerry-demo.php --api=https://test-api.datagerry.com/rest --user=me@example.com \
 *       --password='secret' [--subscription=Medium] [--wipe]
 *
 *   Options can also be given as environment variables: DG_API, DG_USER, DG_PASSWORD, DG_SUBSCRIPTION.
 *   --subscription  name or short id (SUB-CL-...) of the cloud subscription; not needed on premise
 *   --wipe          DELETES ALL OBJECTS, relations, ISMS data, persons and object groups of the tenant first.
 *                   Without it the script refuses to run on a tenant that already contains objects.
 *
 * Requirements: PHP >= 8.1 with the curl and json extensions.
 */

declare(strict_types=1);

// ============================================================================================ config / http

$opt = getopt('', ['api:', 'user:', 'password:', 'subscription:', 'wipe', 'help']);
if (isset($opt['help'])) {
    fwrite(STDOUT, preg_replace('/^ \* ?/m', '', explode('*/', explode('/**', file_get_contents(__FILE__))[1])[0]));
    exit(0);
}
$API  = rtrim($opt['api'] ?? getenv('DG_API') ?: 'https://test-api.datagerry.com/rest', '/');
$USER = $opt['user'] ?? getenv('DG_USER') ?: '';
$PASS = $opt['password'] ?? getenv('DG_PASSWORD') ?: '';
$SUB  = $opt['subscription'] ?? getenv('DG_SUBSCRIPTION') ?: '';
$WIPE = isset($opt['wipe']);
if ($USER === '' || $PASS === '') {
    fwrite(STDERR, "Missing --user / --password (or DG_USER / DG_PASSWORD). See --help\n");
    exit(1);
}

$TOKEN = null;
$UID = 1;

function http(string $method, string $path, $body = null): array
{
    global $API, $TOKEN;
    for ($attempt = 1; ; $attempt++) {
        $ch = curl_init($API . $path);
        $headers = ['Content-Type: application/json', 'Accept: application/json'];
        if ($TOKEN) {
            $headers[] = 'Authorization: Bearer ' . $TOKEN;
        }
        curl_setopt_array($ch, [
            CURLOPT_CUSTOMREQUEST => $method, CURLOPT_RETURNTRANSFER => true, CURLOPT_HTTPHEADER => $headers,
            CURLOPT_TIMEOUT => 180, CURLOPT_FOLLOWLOCATION => true,
        ]);
        if ($body !== null) {
            curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION));
        }
        $raw = curl_exec($ch);
        $code = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        $err = curl_error($ch);
        curl_close($ch);
        if (($raw === false || $code >= 502) && $attempt < 4) {
            sleep(2 * $attempt);
            continue;
        }
        if ($raw === false) {
            fail("$method $path: $err");
        }
        $data = $raw === '' ? null : json_decode($raw, true);
        return [$code, $data ?? $raw];
    }
}

function fail(string $msg): void
{
    fwrite(STDERR, "\nERROR: $msg\n");
    exit(2);
}

function api(string $method, string $path, $body = null)
{
    [$code, $data] = http($method, $path, $body);
    if ($code < 200 || $code >= 300) {
        fail("HTTP $code $method $path\nbody: " . substr(json_encode($body, JSON_UNESCAPED_UNICODE) ?: '', 0, 800)
            . "\nresponse: " . substr(is_string($data) ? $data : json_encode($data, JSON_UNESCAPED_UNICODE), 0, 1500));
    }
    return $data;
}

function results($r): array
{
    if (is_array($r) && array_is_list($r)) {
        return $r;
    }
    return $r['results'] ?? [];
}

function new_id($r): int
{
    if (is_int($r)) {
        return $r;
    }
    foreach (['result_id', 'public_id'] as $k) {
        if (is_array($r) && isset($r[$k]) && is_int($r[$k])) {
            return $r[$k];
        }
    }
    if (isset($r['raw']['public_id'])) {
        return $r['raw']['public_id'];
    }
    fail('cannot read new id from ' . substr(json_encode($r), 0, 300));
}

function say(string $s): void
{
    fwrite(STDOUT, $s . "\n");
}

function login(): void
{
    global $USER, $PASS, $SUB, $TOKEN, $UID;
    $cred = ['user_name' => $USER, 'password' => $PASS];
    $r = api('POST', '/auth/login', $cred);
    if (is_array($r) && array_is_list($r)) {   // cloud: choose the subscription
        $match = array_values(array_filter($r, fn($s) => $SUB !== '' && ($s['name'] === $SUB || ($s['short_id'] ?? '') === $SUB)));
        if (!$match) {
            fail("Choose a subscription with --subscription. Available: "
                . implode(', ', array_map(fn($s) => "{$s['name']} ({$s['short_id']})", $r)));
        }
        $r = api('POST', '/auth/login', $cred + ['subscription' => $match[0]]);
    }
    $TOKEN = $r['token'] ?? fail('login returned no token');
    $UID = (int)$r['user']['public_id'];
    say("Logged in as {$r['user']['user_name']} (user #$UID, database " . ($r['user']['database'] ?? '-') . ")");
}

// ============================================================================================ state helpers

$TY = [];    // type name => type document
$TID = [];   // type name => public_id
$O = [];     // object key => ['id' => int, 'loc' => int|null]
$OPT = [];   // "OPTION_TYPE|value" => public_id
$PORTS = [];
$CAB = 0;
mt_srand(4711);

function load_types(): void
{
    global $TY, $TID;
    $TY = [];
    foreach (results(api('GET', '/types/?limit=1000')) as $t) {
        $TY[$t['name']] = $t;
    }
    $TID = array_map(fn($t) => $t['public_id'], $TY);
}

function oid(string $key): int
{
    global $O;
    return $O[$key]['id'] ?? fail("unknown object key $key");
}

function rnd_str(int $len, string $chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ0123456789'): string
{
    $s = '';
    for ($i = 0; $i < $len; $i++) {
        $s .= $chars[mt_rand(0, strlen($chars) - 1)];
    }
    return $s;
}

function mac(string $prefix = '00:50:56'): string
{
    return $prefix . sprintf(':%02X:%02X:%02X', mt_rand(0, 255), mt_rand(0, 255), mt_rand(0, 255));
}

function ms(string $date): array
{
    return ['$date' => strtotime($date . ' 00:00:00 UTC') * 1000];
}

function has_location(string $type): bool
{
    global $TY;
    foreach ($TY[$type]['fields'] as $f) {
        if ($f['type'] === 'location') {
            return true;
        }
    }
    return false;
}

/** Creates a CmdbObject. $parent: object key of the location parent, null = root, false = no location */
function obj(string $key, string $type, array $values, $parent = null, ?string $locName = null, ?array $mds = null): int
{
    global $TY, $O, $UID;
    if (isset($O[$key])) {
        return $O[$key]['id'];
    }
    $t = $TY[$type] ?? fail("type $type missing");
    $known = array_column($t['fields'], 'type', 'name');
    foreach (array_keys($values) as $n) {
        isset($known[$n]) || fail("field $n not on type $type ($key)");
    }
    $fields = [];
    foreach ($t['fields'] as $f) {
        if ($f['type'] === 'location') {
            if ($parent === false) {
                continue;
            }
            $fields[] = ['name' => $f['name'], 'type' => 'location', 'value' => $parent ? $O[$parent]['loc'] : 1];
        } elseif (array_key_exists($f['name'], $values)) {
            $fields[] = ['name' => $f['name'], 'type' => $f['type'], 'value' => $values[$f['name']]];
        }
    }
    $body = ['type_id' => $t['public_id'], 'author_id' => $UID, 'active' => true, 'fields' => $fields];
    if (!empty($t['special_type'])) {
        $body['special_type'] = $t['special_type'];   // the API does not derive it from the type
    }
    if ($mds) {
        $body['multi_data_sections'] = $mds;
    }
    $withLoc = $parent !== false && has_location($type);
    if ($withLoc && $locName) {
        $body['location_name'] = $locName;
    }
    $id = new_id(api('POST', '/objects/', $body));
    $O[$key] = ['id' => $id, 'loc' => null];
    if ($withLoc) {
        [$c, $r] = http('GET', "/locations/$id/object");
        $O[$key]['loc'] = $c === 200 ? ($r['public_id'] ?? null) : null;
    }
    return $id;
}

/** IPAM interface rows: [[ip, subnet key, hostname, mac], ...] */
function iface_mds(array $rows): array
{
    $vals = [];
    foreach ($rows as $i => [$ip, $sn, $host, $mac]) {
        $vals[] = ['multi_data_id' => $i + 1, 'data' => [
            ['name' => 'dg-interface-active', 'value' => true],
            ['name' => 'dg-interface-type', 'value' => str_contains($ip, ':') ? 'ipv6' : 'ipv4'],
            ['name' => 'dg-interface-subnet', 'value' => oid($sn)],
            ['name' => 'dg-interface-ip-address', 'value' => $ip],
            ['name' => 'dg-interface-host', 'value' => $host],
            ['name' => 'dg-interface-domain', 'value' => 'nordlicht.local'],
            ['name' => 'dg-interface-mac-address', 'value' => $mac],
        ]];
    }
    return [['section_id' => 'dg-ipam-interface', 'highest_id' => count($vals), 'values' => $vals]];
}

/** Hardware object with model specification and optional interfaces [[ip, subnet key], ...] */
function dev(string $key, string $type, string $name, string $manu, string $model, string $parent, array $extra = [],
             array $ifaces = [], string $macPrefix = '00:50:56'): int
{
    global $TY;
    $names = array_column($TY[$type]['fields'], 'name');
    $vals = [$TY[$type]['fields'][0]['name'] => $name, 'dg-modelspec-manufacturer' => $manu,
             'dg-modelspec-model' => $model, 'dg-modelspec-serial' => rnd_str(10)];
    $vals = array_filter($vals, fn($k) => in_array($k, $names, true), ARRAY_FILTER_USE_KEY) + $extra;
    $mds = $ifaces ? iface_mds(array_map(fn($x) => [$x[0], $x[1], $name, mac($macPrefix)], $ifaces)) : null;
    return obj($key, $type, $vals, $parent, $name, $mds);
}

function option(string $type, string $value): int
{
    global $OPT;
    if (!$OPT) {
        foreach (results(api('GET', '/extendable_options/?limit=5000')) as $o) {
            $OPT[$o['option_type'] . '|' . $o['value']] = $o['public_id'];
        }
    }
    if (!isset($OPT["$type|$value"])) {
        $OPT["$type|$value"] = new_id(api('POST', '/extendable_options/', ['value' => $value, 'option_type' => $type, 'predefined' => false]));
    }
    return $OPT["$type|$value"];
}

// ============================================================================================ demo data

const PEOPLE = [ // key, first, last, department, room, desk
    ['u_mweber', 'Markus', 'Weber', 'Geschäftsführung', 'r_gf', 'GF-01'],
    ['u_skoch', 'Sabine', 'Koch', 'IT-Leitung', 'r_it', 'IT-01'],
    ['u_tschulz', 'Thomas', 'Schulz', 'IT-Administration', 'r_it', 'IT-02'],
    ['u_jneumann', 'Julia', 'Neumann', 'IT-Administration', 'r_it', 'IT-03'],
    ['u_akaya', 'Ali', 'Kaya', 'Informationssicherheit', 'r_it', 'IT-04'],
    ['u_lbecker', 'Laura', 'Becker', 'Vertrieb', 'r_sales', 'VT-01'],
    ['u_fwagner', 'Felix', 'Wagner', 'Vertrieb', 'r_sales', 'VT-02'],
    ['u_nhoffmann', 'Nina', 'Hoffmann', 'Vertrieb', 'r_sales', 'VT-03'],
    ['u_dyilmaz', 'Deniz', 'Yilmaz', 'Vertrieb', 'r_sales', 'VT-04'],
    ['u_cfischer', 'Claudia', 'Fischer', 'Buchhaltung', 'r_fin', 'BH-01'],
    ['u_pmeyer', 'Peter', 'Meyer', 'Buchhaltung', 'r_fin', 'BH-02'],
    ['u_akrueger', 'Anna', 'Krüger', 'Buchhaltung', 'r_fin', 'BH-03'],
    ['u_hpetersen', 'Hauke', 'Petersen', 'Niederlassungsleitung HH', 'r_hh_office', 'HH-01'],
    ['u_mjanssen', 'Merle', 'Janssen', 'Disposition HH', 'r_hh_office', 'HH-02'],
    ['u_bclausen', 'Björn', 'Clausen', 'Disposition HH', 'r_hh_office', 'HH-03'],
    ['u_sbrandt', 'Svenja', 'Brandt', 'Lager HH', 'r_hh_office', 'HH-04'],
    ['u_onowak', 'Oliver', 'Nowak', 'Lager HH', 'r_hh_office', 'HH-05'],
];
const OSES = [
    ['os_win11', 'Windows 11 Enterprise', '23H2', 'x64'], ['os_ws2022', 'Windows Server 2022', '21H2', 'Datacenter'],
    ['os_ubuntu', 'Ubuntu Server', '24.04 LTS', 'x64'], ['os_rhel', 'Red Hat Enterprise Linux', '9.4', 'Server'],
    ['os_debian', 'Debian GNU/Linux', '12 (bookworm)', 'x64'], ['os_esxi', 'VMware ESXi', '8.0 Update 3', 'Enterprise Plus'],
    ['os_iosxe', 'Cisco IOS XE', '17.12.4', 'Cupertino'], ['os_fortios', 'FortiOS', '7.4.5', 'GA'],
    ['os_ontap', 'NetApp ONTAP', '9.15.1', 'P3'], ['os_dsm', 'Synology DSM', '7.2.2', 'RackStation'],
    ['os_ise', 'Cisco ISE', '3.3 Patch 3', 'Appliance'],
];
const SUPERNETS = [
    ['sn_ber', 'Nordlicht Berlin', '10.10.0.0/16', 'ipv4'], ['sn_hh', 'Nordlicht Hamburg', '10.20.0.0/16', 'ipv4'],
    ['sn_dmz', 'Nordlicht DMZ', '172.16.0.0/16', 'ipv4'], ['sn_v6', 'Nordlicht IPv6 (Dokumentation)', '2001:db8:4e00::/48', 'ipv6'],
];
const SUBNETS = [ // key, name, supernet, cidr, family, vlan
    ['net_srv', 'BER Server', 'sn_ber', '10.10.10.0/24', 'ipv4', 10], ['net_cli', 'BER Clients', 'sn_ber', '10.10.20.0/24', 'ipv4', 20],
    ['net_prn', 'BER Drucker', 'sn_ber', '10.10.30.0/24', 'ipv4', 30], ['net_wlan', 'BER WLAN', 'sn_ber', '10.10.40.0/22', 'ipv4', 40],
    ['net_sto', 'BER Storage/vMotion', 'sn_ber', '10.10.50.0/24', 'ipv4', 50], ['net_mgmt', 'BER Management', 'sn_ber', '10.10.99.0/24', 'ipv4', 99],
    ['net_hh_cli', 'HH Clients', 'sn_hh', '10.20.20.0/24', 'ipv4', 120], ['net_hh_mgmt', 'HH Management', 'sn_hh', '10.20.99.0/24', 'ipv4', 199],
    ['net_dmz', 'DMZ Webservices', 'sn_dmz', '172.16.10.0/24', 'ipv4', 310], ['net_srv6', 'BER Server IPv6', 'sn_v6', '2001:db8:4e00:10::/64', 'ipv6', null],
];
const SERVERS = [ // key, name, vendor, model, server ip, oob port
    ['srv_esx1', 'srv-ber-esx01', 'Dell', 'PowerEdge R750', '10.10.10.11', 'iDRAC'],
    ['srv_esx2', 'srv-ber-esx02', 'Dell', 'PowerEdge R750', '10.10.10.12', 'iDRAC'],
    ['srv_esx3', 'srv-ber-esx03', 'Dell', 'PowerEdge R750', '10.10.10.13', 'iDRAC'],
    ['srv_dmz1', 'srv-ber-dmz01', 'Dell', 'PowerEdge R660', '172.16.10.5', 'iDRAC'],
    ['srv_bak1', 'srv-ber-bak01', 'HPE', 'ProLiant DL380 Gen11', '10.10.10.20', 'iLO'],
];
const VMS = [ // key, name, host, os, owner, ip, subnet
    ['vm_dc01', 'ber-dc01', 'srv_esx1', 'os_ws2022', 'u_tschulz', '10.10.10.31', 'net_srv'],
    ['vm_dc02', 'ber-dc02', 'srv_esx2', 'os_ws2022', 'u_tschulz', '10.10.10.32', 'net_srv'],
    ['vm_fs01', 'ber-fs01', 'srv_esx1', 'os_ws2022', 'u_jneumann', '10.10.10.40', 'net_srv'],
    ['vm_sql01', 'ber-sql01', 'srv_esx2', 'os_ws2022', 'u_jneumann', '10.10.10.45', 'net_srv'],
    ['vm_erp01', 'ber-erp01', 'srv_esx3', 'os_rhel', 'u_jneumann', '10.10.10.50', 'net_srv'],
    ['vm_wms01', 'ber-wms01', 'srv_esx3', 'os_ubuntu', 'u_tschulz', '10.10.10.55', 'net_srv'],
    ['vm_prt01', 'ber-print01', 'srv_esx1', 'os_ws2022', 'u_tschulz', '10.10.10.60', 'net_srv'],
    ['vm_mon01', 'ber-mon01', 'srv_esx2', 'os_debian', 'u_akaya', '10.10.99.20', 'net_mgmt'],
    ['vm_veeam01', 'ber-veeam01', 'srv_esx3', 'os_ws2022', 'u_tschulz', '10.10.10.70', 'net_srv'],
    ['vm_web01', 'dmz-web01', 'srv_dmz1', 'os_ubuntu', 'u_akaya', '172.16.10.10', 'net_dmz'],
    ['vm_web02', 'dmz-web02', 'srv_dmz1', 'os_ubuntu', 'u_akaya', '172.16.10.11', 'net_dmz'],
];

// Rack layouts: [object key, top U (the mount extends downwards), height, area]. PDUs hang on the sides (0U).
const LAYOUT = [
    'rack_ber1' => [['pp_r01_fo1', 42, 1, 'FRONT'], ['pp_r01_cu1', 41, 1, 'FRONT'], ['cm_r01a', 40, 1, 'FRONT'],
        ['pp_r01_cu2', 39, 1, 'FRONT'], ['pp_r01_cu3', 38, 1, 'FRONT'], ['cm_r01b', 37, 1, 'FRONT'],
        ['sw_acc1', 36, 1, 'FULL_DEPTH'], ['sw_acc2', 35, 1, 'FULL_DEPTH'], ['sw_acc3', 34, 1, 'FULL_DEPTH'],
        ['sw_core1', 33, 1, 'FULL_DEPTH'], ['sw_core2', 32, 1, 'FULL_DEPTH'], ['cm_r01c', 31, 1, 'FRONT'],
        ['fw_ber1', 30, 1, 'FULL_DEPTH'], ['fw_ber2', 29, 1, 'FULL_DEPTH'], ['wlc_ber1', 28, 1, 'FULL_DEPTH'],
        ['rt_ber', 27, 2, 'FULL_DEPTH'], ['cpe_ber1', 25, 1, 'FULL_DEPTH'], ['con_ber1', 24, 1, 'FULL_DEPTH'],
        ['sw_oob1', 23, 1, 'FULL_DEPTH'], ['ise_ber1', 22, 1, 'FULL_DEPTH'], ['ntp_ber1', 20, 1, 'FULL_DEPTH'],
        ['bat_r01', 6, 2, 'FULL_DEPTH'], ['usv_r01', 4, 4, 'FULL_DEPTH'],
        ['pdu_r01a', null, null, 'LEFT'], ['pdu_r01b', null, null, 'RIGHT']],
    'rack_ber2' => [['pp_r02_fo1', 42, 1, 'FRONT'], ['pp_r02_cu1', 41, 1, 'FRONT'], ['cm_r02a', 40, 1, 'FRONT'],
        ['kvm_ber1', 39, 1, 'FULL_DEPTH'], ['kvmc_ber1', 38, 1, 'FULL_DEPTH'], ['shelf_ber1', 37, 2, 'FULL_DEPTH'],
        ['tl_ber1', 35, 3, 'FULL_DEPTH'], ['srv_esx1', 30, 2, 'FULL_DEPTH'], ['srv_esx2', 28, 2, 'FULL_DEPTH'],
        ['srv_esx3', 26, 2, 'FULL_DEPTH'], ['srv_dmz1', 24, 1, 'FULL_DEPTH'], ['sto_ber1', 22, 2, 'FULL_DEPTH'],
        ['srv_bak1', 18, 2, 'FULL_DEPTH'], ['bat_r02a', 10, 2, 'FULL_DEPTH'], ['bat_r02b', 8, 2, 'FULL_DEPTH'],
        ['usv_r02', 6, 6, 'FULL_DEPTH'], ['pdu_r02a', null, null, 'LEFT'], ['pdu_r02b', null, null, 'RIGHT']],
    'rack_hh1' => [['pp_hh1', 24, 1, 'FRONT'], ['cm_hh1', 23, 1, 'FRONT'], ['sw_hh1', 22, 1, 'FULL_DEPTH'],
        ['fw_hh1', 20, 1, 'FULL_DEPTH'], ['cpe_hh1', 19, 1, 'FULL_DEPTH'], ['rt_hh', 18, 1, 'FULL_DEPTH'],
        ['nas_hh1', 16, 2, 'FULL_DEPTH'], ['usv_hh1', 2, 2, 'FULL_DEPTH'],
        ['pdu_hh1a', null, null, 'LEFT'], ['pdu_hh1b', null, null, 'RIGHT']],
];
const RESERVATIONS = [
    ['rack_ber1', 'Reserviert: Erweiterung Access-Switches 4. OG (2027)', 17, 4],
    ['rack_ber2', 'Reserviert: srv-ber-esx04 (Q1/2027)', 14, 2],
];
// power: [device key, [psu ports], pdu prefix] - dual PSUs go to the A (UPS) and B (utility) feed
const POWER = [
    'r01' => ['sw_acc1' => 2, 'sw_acc2' => 2, 'sw_acc3' => 2, 'sw_core1' => 2, 'sw_core2' => 2, 'fw_ber1' => 2, 'fw_ber2' => 2,
              'wlc_ber1' => 2, 'rt_ber' => 2, 'cpe_ber1' => 1, 'con_ber1' => 1, 'sw_oob1' => 1, 'ise_ber1' => 2, 'ntp_ber1' => 1],
    'r02' => ['kvm_ber1' => 1, 'kvmc_ber1' => 1, 'shelf_ber1' => 2, 'tl_ber1' => 2, 'srv_esx1' => 2, 'srv_esx2' => 2,
              'srv_esx3' => 2, 'srv_dmz1' => 2, 'sto_ber1' => 2, 'srv_bak1' => 2],
    'hh1' => ['sw_hh1' => 1, 'fw_hh1' => 1, 'cpe_hh1' => 1, 'rt_hh' => 1, 'nas_hh1' => 2],
];

// ============================================================================================ wipe

function wipe(): void
{
    global $TY, $TID;
    say('=== wipe');
    // ISMS: risks cascade to their assessments and control measure assignments
    foreach (['risks', 'control_measures', 'threats', 'vulnerabilities'] as $e) {
        $ids = array_column(results(api('GET', "/isms/$e/?limit=5000")), 'public_id');
        foreach (array_chunk($ids, 50) as $chunk) {
            api('DELETE', "/isms/$e/delete/" . implode(',', $chunk));
        }
        say("  isms $e: " . count($ids));
    }
    foreach (['risk_assessments', 'impact_categories', 'likelihoods', 'impacts', 'risk_classes'] as $e) {
        foreach (results(api('GET', "/isms/$e/?limit=5000")) as $x) {
            api('DELETE', "/isms/$e/{$x['public_id']}");
        }
    }
    foreach (results(api('GET', '/isms/protection_goals/?limit=500')) as $x) {
        if (empty($x['predefined'])) {
            api('DELETE', "/isms/protection_goals/{$x['public_id']}");
        }
    }
    foreach (['persons', 'person_groups', 'object_groups'] as $e) {
        foreach (results(api('GET', "/$e/?limit=5000")) as $x) {
            api('DELETE', "/$e/{$x['public_id']}");
        }
    }
    // objects: ordinary objects first (ports, cabling, mounts, locations, relations cascade), then cables, then IPAM
    $stage = function (array $o) use (&$TY) {
        $byId = array_column($TY, null, 'public_id');
        return ['CABLE' => 1, 'VLAN' => 2, 'SUBNET' => 3, 'SUPERNET' => 4][$byId[$o['type_id']]['special_type'] ?? ''] ?? 0;
    };
    $objs = results(api('GET', '/objects/?limit=10000'));
    for ($s = 0; $s <= 4; $s++) {
        $ids = array_column(array_filter($objs, fn($o) => $stage($o) === $s), 'public_id');
        foreach (array_chunk($ids, 50) as $chunk) {
            api('DELETE', '/objects/delete/' . implode(',', $chunk));
        }
    }
    say('  objects: ' . count($objs));
    foreach (results(api('GET', '/relations/?limit=1000')) as $r) {
        api('DELETE', "/relations/{$r['public_id']}");
    }
}

// ============================================================================================ types

function modelspec_and_interface_fields(): array
{
    global $TY;
    $f = array_values(array_filter($TY['client']['fields'], fn($x) => str_starts_with($x['name'], 'dg-modelspec') || str_starts_with($x['name'], 'dg-interface')));
    $sec = array_values(array_filter($TY['client']['render_meta']['sections'], fn($s) => in_array($s['name'], ['dg-modelspec', 'dg-ipam-interface'], true)));
    return [$f, $sec];
}

function create_type(string $name, string $label, string $icon, string $color, array $fields, array $sections, array $summary,
                     bool $ports = false, array $templates = [], ?string $special = null, string $desc = ''): void
{
    global $TY, $UID;
    if (isset($TY[$name])) {
        return;
    }
    $body = ['name' => $name, 'label' => $label, 'author_id' => $UID, 'active' => true, 'description' => $desc,
             'selectable_as_parent' => false, 'global_template_ids' => $templates, 'fields' => $fields,
             'acl' => ['activated' => false, 'groups' => ['includes' => new stdClass()]],
             'ci_explorer_label' => $fields[0]['name'], 'ci_explorer_color' => $color, 'uses_ports' => $ports,
             'port_section_index' => $ports ? 2 : 0,
             'render_meta' => ['icon' => $icon, 'externals' => [], 'summary' => ['fields' => $summary], 'sections' => $sections]];
    if ($special) {
        $body['special_type'] = $special;
        unset($body['ci_explorer_label']);
    }
    say("  type $name -> " . new_id(api('POST', '/types/', $body)));
}

function phase_types(): void
{
    global $TY, $TID;
    say('=== types');
    load_types();
    foreach (['appliance', 'wireless_access_point', 'printer'] as $n) {
        if (empty($TY[$n]['uses_ports'])) {
            $t = $TY[$n];
            $t['uses_ports'] = true;
            $t['port_section_index'] = 3;
            api('PUT', "/types/{$t['public_id']}", array_diff_key($t, array_flip(['public_id', 'creation_time', 'last_edit_time', 'editor_id'])));
            say("  ports enabled on $n");
        }
    }
    $sel = fn(array $o) => array_map(fn($x) => ['name' => $x, 'label' => $x], $o);
    create_type('application', 'Anwendung', 'fas fa-cubes', '#7B1FA2', [
        ['type' => 'text', 'name' => 'app-name', 'label' => 'Name', 'required' => true],
        ['type' => 'text', 'name' => 'app-vendor', 'label' => 'Hersteller'],
        ['type' => 'text', 'name' => 'app-version', 'label' => 'Version'],
        ['type' => 'select', 'name' => 'app-criticality', 'label' => 'Kritikalität', 'options' => $sel(['niedrig', 'mittel', 'hoch', 'kritisch'])],
        ['type' => 'select', 'name' => 'app-lifecycle', 'label' => 'Lifecycle', 'options' => $sel(['Planung', 'Produktiv', 'Auslaufend', 'Abgeschaltet'])],
        ['type' => 'ref', 'name' => 'app-owner', 'label' => 'Application Owner', 'ref_types' => [$TID['user']], 'summaries' => []],
        ['type' => 'text', 'name' => 'app-url', 'label' => 'URL'],
        ['type' => 'textarea', 'name' => 'app-description', 'label' => 'Beschreibung'],
    ], [
        ['type' => 'section', 'name' => 'app-general', 'label' => 'Allgemein', 'fields' => ['app-name', 'app-vendor', 'app-version', 'app-url']],
        ['type' => 'section', 'name' => 'app-operation', 'label' => 'Betrieb', 'fields' => ['app-criticality', 'app-lifecycle', 'app-owner', 'app-description']],
    ], ['app-name', 'app-version'], false, [], null, 'Fachanwendungen und IT-Services');
    $hasCable = (bool)array_filter($TY, fn($t) => ($t['special_type'] ?? null) === 'CABLE');
    if (!$hasCable) {
        $s = api('GET', '/special_types/schema?special_type=CABLE');
        create_type('cable', 'Kabel', 'fas fa-plug', '#795548', $s['fields'], $s['sections'], ['dg-cable-name', 'dg-cable-type'],
            false, [], 'CABLE', 'Inventarisierte Kabel (Port Connectivity)');
    }
    [$mf, $msec] = modelspec_and_interface_fields();
    $loc = ['type' => 'location', 'name' => 'dg_location', 'label' => 'Location'];
    create_type('pdu', 'PDU', 'fas fa-bolt', '#F9A825', array_merge([
        ['type' => 'text', 'name' => 'pdu-name', 'label' => 'Name', 'required' => true],
        ['type' => 'select', 'name' => 'pdu-feed', 'label' => 'Einspeisung', 'options' => $sel(['A-Feed (USV)', 'B-Feed (Netz)'])],
        ['type' => 'select', 'name' => 'pdu-phase', 'label' => 'Anschluss', 'options' => $sel(['1-phasig 230 V', '3-phasig 400 V'])],
        ['type' => 'number', 'name' => 'pdu-current', 'label' => 'Absicherung (A)'],
        ['type' => 'text', 'name' => 'pdu-outlets', 'label' => 'Ausgänge'],
        ['type' => 'text', 'name' => 'pdu-circuit', 'label' => 'Stromkreis / Sicherung'],
    ], $mf, [$loc]), array_merge([
        ['type' => 'section', 'name' => 'pdu-general', 'label' => 'Stromverteilung', 'fields' => ['pdu-name', 'pdu-feed', 'pdu-phase', 'pdu-current', 'pdu-outlets', 'pdu-circuit']],
    ], $msec, [['type' => 'section', 'name' => 'pdu-location', 'label' => 'Location', 'fields' => ['dg_location']]]),
        ['pdu-name', 'pdu-feed'], true, ['dg-modelspec', 'dg-ipam-interface'], null, 'Rack-Stromverteiler (Zero-U, seitlich montiert)');
    create_type('ups', 'USV', 'fas fa-car-battery', '#00897B', array_merge([
        ['type' => 'text', 'name' => 'ups-name', 'label' => 'Name', 'required' => true],
        ['type' => 'select', 'name' => 'ups-kind', 'label' => 'Gerätetyp', 'options' => $sel(['USV', 'Batteriepack'])],
        ['type' => 'text', 'name' => 'ups-power', 'label' => 'Leistung'],
        ['type' => 'number', 'name' => 'ups-runtime', 'label' => 'Autonomiezeit bei Last (min)'],
        ['type' => 'text', 'name' => 'ups-battery', 'label' => 'Nächster Batterietausch'],
    ], $mf, [$loc]), array_merge([
        ['type' => 'section', 'name' => 'ups-general', 'label' => 'USV', 'fields' => ['ups-name', 'ups-kind', 'ups-power', 'ups-runtime', 'ups-battery']],
    ], $msec, [['type' => 'section', 'name' => 'ups-location', 'label' => 'Location', 'fields' => ['dg_location']]]),
        ['ups-name', 'ups-kind'], true, ['dg-modelspec', 'dg-ipam-interface'], null, 'Unterbrechungsfreie Stromversorgung und Batterieerweiterungen');
    load_types();
    $cats = array_column(results(api('GET', '/categories/?limit=100')), null, 'name');
    foreach ([['software', 'application'], ['network', 'cable'], ['hardware', 'pdu'], ['hardware', 'ups']] as [$c, $t]) {
        if (isset($cats[$c]) && !in_array($TID[$t], $cats[$c]['types'], true)) {
            $cats[$c]['types'][] = $TID[$t];
            api('PUT', "/categories/{$cats[$c]['public_id']}", array_diff_key($cats[$c], ['public_id' => 1]));
        }
    }
}

// ============================================================================================ ipam + base

function phase_ipam(): void
{
    say('=== ipam');
    foreach (SUPERNETS as [$k, $n, $cidr, $fam]) {
        obj($k, 'supernet', ['dg-name' => $n, 'dg-network-range' => $cidr, 'dg-supernet-type' => $fam], false);
    }
    foreach (SUBNETS as [$k, $n, $sn, $cidr, $fam, $vlan]) {
        obj($k, 'subnet', ['dg-name' => $n, 'dg-supernet-ref' => oid($sn), 'dg-network-range' => $cidr, 'dg-subnet-type' => $fam], false);
        if ($vlan) {
            obj("vlan_$vlan", 'vlan', ['dg-name' => "VLAN $vlan - $n", 'dg-subnet-ref' => oid($k), 'dg-vlan-type' => 'static'], false);
        }
    }
}

function mail_of(string $first, string $last): string
{
    return strtolower(strtr("$first.$last", ['ä' => 'ae', 'ö' => 'oe', 'ü' => 'ue', 'ß' => 'ss', 'Ä' => 'Ae', 'Ö' => 'Oe', 'Ü' => 'Ue'])) . '@nordlicht-logistik.de';
}

function phase_base(): void
{
    say('=== locations, people, companies, operating systems');
    obj('loc_de', 'country', ['text-84872' => 'Germany'], null, 'Germany');
    obj('loc_ber', 'city', ['text-31555' => 'Berlin'], 'loc_de', 'Berlin');
    obj('loc_hh', 'city', ['text-31555' => 'Hamburg'], 'loc_de', 'Hamburg');
    obj('b_ber', 'building', ['text-56569' => 'BER-HQ Friedrichstraße', 'text-28009' => 'Friedrichstraße', 'text-36479' => '10117', 'text-24247' => '123'], 'loc_ber', 'BER-HQ Friedrichstraße');
    obj('b_hh', 'building', ['text-56569' => 'HH Niederlassung Sandtorkai', 'text-28009' => 'Am Sandtorkai', 'text-36479' => '20457', 'text-24247' => '48'], 'loc_hh', 'HH Niederlassung Sandtorkai');
    foreach ([['r_srv', 'Serverraum', 'UG-01', 'UG', 'b_ber'], ['r_gf', 'Geschäftsführung', '4.01', '4. OG', 'b_ber'],
              ['r_it', 'IT-Abteilung', '3.12', '3. OG', 'b_ber'], ['r_sales', 'Vertrieb', '2.05', '2. OG', 'b_ber'],
              ['r_fin', 'Buchhaltung', '2.10', '2. OG', 'b_ber'], ['r_hh_tech', 'Technikraum', 'EG-02', 'EG', 'b_hh'],
              ['r_hh_office', 'Büro Disposition/Lager', 'EG-01', 'EG', 'b_hh']] as [$k, $n, $nr, $fl, $b]) {
        obj($k, 'room', ['text-72385' => $n, 'text-30789' => $nr, 'text-59951' => $fl], $b, "$n $nr");
    }
    foreach (PEOPLE as $i => [$k, $first, $last, , $room]) {
        obj($k, 'user', ['text-45910' => "$first $last", 'text-80103' => $first, 'text-75307' => $last,
                         'text-93543' => mail_of($first, $last), 'text-16313' => '+49 ' . (str_starts_with($room, 'r_hh') ? '40' : '30') . ' 5550' . (101 + $i)]);
    }
    obj('c_nordlicht', 'company', ['text-595787d0-70f7-49e7-8019-930f370a3c03' => 'Nordlicht Logistik GmbH',
        'number-e777ae67-b6ef-437d-982d-308d43b0669d' => 140, 'ref-40b6d154-7fe6-4707-9306-34aeeb63e506' => oid('u_mweber')], 'b_ber', 'Nordlicht Logistik GmbH');
    obj('c_hanseit', 'company', ['text-595787d0-70f7-49e7-8019-930f370a3c03' => 'Hanse IT-Systemhaus GmbH',
        'select-a56a120d-d8a7-4ba7-a220-29bddc2a0af8' => 'it', 'number-e777ae67-b6ef-437d-982d-308d43b0669d' => 45], 'loc_hh', 'Hanse IT-Systemhaus GmbH');
    foreach ([['cu_rlange', 'Robert', 'Lange', '+49 40 3330120'], ['cu_kvogel', 'Katrin', 'Vogel', '+49 40 3330135']] as [$k, $f, $l, $p]) {
        obj($k, 'customer_user', ['text-39929' => "$f $l (Hanse IT)", 'text-91469' => $f, 'text-84039' => $l,
            'text-27614' => strtolower($f[0] . ".$l") . '@hanse-it.example', 'text-44997' => $p, 'ref-25151' => oid('c_hanseit')]);
    }
    foreach (OSES as [$k, $n, $v, $var]) {
        obj($k, 'operating_system', ['text-42835' => $n, 'text-25407' => $v, 'text-49533' => $var]);
    }
}

// ============================================================================================ hardware

function phase_hw(): void
{
    global $CLIENTS;
    say('=== hardware, virtual servers, workplaces');
    $net = fn($os, $u) => ['ref-71899' => oid($os), 'ref-41420' => oid($u)];
    $app = fn($os, $u) => ['ref-72670' => oid($os), 'ref-98369' => oid($u)];
    // Berlin network rack
    dev('rt_ber', 'router', 'rt-ber-edge01', 'Cisco', 'ISR 4451-X', 'r_srv', ['ref-68233' => oid('os_iosxe'), 'ref-58400' => oid('u_tschulz')], [['10.10.99.1', 'net_mgmt']], '00:1E:BD');
    dev('fw_ber1', 'appliance', 'fw-ber-01', 'Fortinet', 'FortiGate 200F', 'r_srv', $app('os_fortios', 'u_akaya'), [['10.10.99.2', 'net_mgmt']], '00:09:0F');
    dev('fw_ber2', 'appliance', 'fw-ber-02', 'Fortinet', 'FortiGate 200F', 'r_srv', $app('os_fortios', 'u_akaya'), [['10.10.99.3', 'net_mgmt']], '00:09:0F');
    foreach ([['sw_core1', 'sw-ber-core01', 'Catalyst C9500-24Y4C', '10.10.99.11'], ['sw_core2', 'sw-ber-core02', 'Catalyst C9500-24Y4C', '10.10.99.12'],
              ['sw_acc1', 'sw-ber-acc01', 'Catalyst C9300-48P', '10.10.99.21'], ['sw_acc2', 'sw-ber-acc02', 'Catalyst C9300-48P', '10.10.99.22'],
              ['sw_acc3', 'sw-ber-acc03', 'Catalyst C9300-48P', '10.10.99.23'], ['sw_oob1', 'sw-ber-oob01', 'Catalyst C9200L-24T-4G', '10.10.99.24']] as [$k, $n, $m, $ip]) {
        dev($k, 'switch', $n, 'Cisco', $m, 'r_srv', $net('os_iosxe', 'u_tschulz'), [[$ip, 'net_mgmt']], '70:B3:17');
    }
    dev('wlc_ber1', 'appliance', 'wlc-ber-01', 'Cisco', 'Catalyst 9800-L-F Wireless Controller', 'r_srv', $app('os_iosxe', 'u_tschulz'), [['10.10.99.40', 'net_mgmt']], '70:B3:17');
    dev('ise_ber1', 'appliance', 'ise-ber-01', 'Cisco', 'SNS-3715 (Identity Services Engine)', 'r_srv', $app('os_ise', 'u_akaya'), [['10.10.99.41', 'net_mgmt']], '70:B3:17');
    dev('con_ber1', 'appliance', 'con-ber-01', 'Opengear', 'CM8148-10-SAC Konsolenserver', 'r_srv', $app('os_debian', 'u_tschulz'), [['10.10.99.42', 'net_mgmt']], '00:13:C6');
    dev('ntp_ber1', 'appliance', 'ntp-ber-01', 'Meinberg', 'LANTIME M300/GPS', 'r_srv', $app('os_debian', 'u_tschulz'), [['10.10.99.43', 'net_mgmt']], 'EC:46:70');
    dev('cpe_ber1', 'appliance', 'cpe-ber-01', 'ADVA', 'FSP 150-XG108 (Provider-Abschluss)', 'r_srv', [], [], '00:80:EA');
    foreach ([['pp_r01_fo1', 'PP-BER-R01-FO01', 'LWL-Spleißbox 24x LC-Duplex OM4'], ['pp_r01_cu1', 'PP-BER-R01-CU01', 'MPP24-HD Cat.6A 24-Port (3. OG)'],
              ['pp_r01_cu2', 'PP-BER-R01-CU02', 'MPP24-HD Cat.6A 24-Port (Trunk R02)'], ['pp_r01_cu3', 'PP-BER-R01-CU03', 'MPP24-HD Cat.6A 24-Port (2./4. OG)'],
              ['pp_r02_fo1', 'PP-BER-R02-FO01', 'LWL-Spleißbox 24x LC-Duplex OM4'], ['pp_r02_cu1', 'PP-BER-R02-CU01', 'MPP24-HD Cat.6A 24-Port (Trunk R01)']] as [$k, $n, $m]) {
        dev($k, 'patch_panel', $n, str_contains($n, 'FO') ? 'Rittal' : 'Telegärtner', $m, 'r_srv');
    }
    foreach ([['cm_r01a', 'KM-BER-R01-1', 'r_srv'], ['cm_r01b', 'KM-BER-R01-2', 'r_srv'], ['cm_r01c', 'KM-BER-R01-3', 'r_srv'],
              ['cm_r02a', 'KM-BER-R02-1', 'r_srv'], ['cm_hh1', 'KM-HH-R01-1', 'r_hh_tech']] as [$k, $n, $room]) {
        obj($k, 'cable-management', ['text-7b39fc85-1429-4d16-9a6b-743e7c4205c8' => "$n 1HE Rangierpanel"], $room, $n);
    }
    // Berlin server rack
    foreach (SERVERS as [$k, $n, $manu, $model, $ip]) {
        $dmz = str_starts_with($ip, '172.');
        $last = (int)substr($ip, strrpos($ip, '.') + 1);
        $ifs = [[$ip, $dmz ? 'net_dmz' : 'net_srv'], ['10.10.99.' . (100 + $last), 'net_mgmt']];
        if (!$dmz) {
            $ifs[] = ["2001:db8:4e00:10::$last", 'net_srv6'];
        }
        dev($k, 'server', $n, $manu, $model, 'r_srv', ['ref-38286' => oid(str_contains($n, 'bak') ? 'os_ws2022' : 'os_esxi'), 'ref-47089' => oid('u_tschulz')], $ifs, 'B4:96:91');
    }
    dev('sto_ber1', 'appliance', 'sto-ber-01', 'NetApp', 'AFF A250', 'r_srv', $app('os_ontap', 'u_jneumann'), [['10.10.50.10', 'net_sto'], ['10.10.99.30', 'net_mgmt']], '00:A0:98');
    dev('shelf_ber1', 'appliance', 'sto-ber-01-shelf1', 'NetApp', 'DS224C Disk Shelf (24x 3.84 TB NVMe)', 'r_srv', $app('os_ontap', 'u_jneumann'));
    dev('tl_ber1', 'appliance', 'tl-ber-01', 'HPE', 'StoreEver MSL3040 (2x LTO-9 FC)', 'r_srv', $app('os_debian', 'u_tschulz'), [['10.10.99.45', 'net_mgmt']], '00:17:A4');
    dev('kvm_ber1', 'appliance', 'kvm-ber-01', 'Raritan', 'Dominion KX IV-116', 'r_srv', $app('os_debian', 'u_tschulz'), [['10.10.99.44', 'net_mgmt']], '00:0D:5D');
    dev('kvmc_ber1', 'appliance', 'kvm-ber-01-console', 'Raritan', 'T1700-LED Konsolenschublade 17"', 'r_srv');
    // power
    foreach ([['usv_r01', 'usv-ber-r01', 'Smart-UPS SRT 6000 RM (SRT6KRMXLI)', 'USV', '6 kVA / 6 kW', 18, '10.10.99.71'],
              ['bat_r01', 'usv-ber-r01-bat1', 'SRT192RMBP2 Batteriepack', 'Batteriepack', '192 V DC', null, null],
              ['usv_r02', 'usv-ber-r02', 'Smart-UPS SRT 10000 RM (SRT10KRMXLI)', 'USV', '10 kVA / 10 kW', 24, '10.10.99.72'],
              ['bat_r02a', 'usv-ber-r02-bat1', 'SRT192RMBP2 Batteriepack', 'Batteriepack', '192 V DC', null, null],
              ['bat_r02b', 'usv-ber-r02-bat2', 'SRT192RMBP2 Batteriepack', 'Batteriepack', '192 V DC', null, null],
              ['usv_hh1', 'usv-hh-r01', 'Smart-UPS SMT1500RMI2UC', 'USV', '1,5 kVA / 1 kW', 35, '10.20.99.71']] as [$k, $n, $m, $kind, $pw, $rt, $ip]) {
        $vals = ['ups-kind' => $kind, 'ups-power' => $pw, 'ups-battery' => $kind === 'USV' ? '03/2029' : '03/2029'];
        if ($rt) {
            $vals['ups-runtime'] = $rt;
        }
        dev($k, 'ups', $n, 'APC by Schneider Electric', $m, str_contains($k, 'hh') ? 'r_hh_tech' : 'r_srv', $vals,
            $ip ? [[$ip, str_contains($k, 'hh') ? 'net_hh_mgmt' : 'net_mgmt']] : [], '28:29:86');
    }
    foreach ([['pdu_r01a', 'pdu-ber-r01-a', 'A-Feed (USV)', 'USV usv-ber-r01 Ausgang C19-1', '10.10.99.61'],
              ['pdu_r01b', 'pdu-ber-r01-b', 'B-Feed (Netz)', 'UV-UG-01 F11 (16 A)', '10.10.99.62'],
              ['pdu_r02a', 'pdu-ber-r02-a', 'A-Feed (USV)', 'USV usv-ber-r02 Ausgang C19-1', '10.10.99.63'],
              ['pdu_r02b', 'pdu-ber-r02-b', 'B-Feed (Netz)', 'UV-UG-01 F12 (16 A)', '10.10.99.64'],
              ['pdu_hh1a', 'pdu-hh-r01-a', 'A-Feed (USV)', 'USV usv-hh-r01 Ausgang C13-1', '10.20.99.61'],
              ['pdu_hh1b', 'pdu-hh-r01-b', 'B-Feed (Netz)', 'UV-EG-02 F4 (16 A)', '10.20.99.62']] as [$k, $n, $feed, $circ, $ip]) {
        $hh = str_contains($k, 'hh');
        dev($k, 'pdu', $n, 'APC by Schneider Electric', $hh ? 'AP8659EU3 Metered ZeroU (14x C13, 2x C19)' : 'AP8853 Metered-by-Outlet ZeroU (21x C13, 3x C19)',
            $hh ? 'r_hh_tech' : 'r_srv', ['pdu-feed' => $feed, 'pdu-phase' => '1-phasig 230 V', 'pdu-current' => 16,
            'pdu-outlets' => $hh ? '14x C13, 2x C19' : '21x C13, 3x C19', 'pdu-circuit' => $circ], [[$ip, $hh ? 'net_hh_mgmt' : 'net_mgmt']], '28:29:86');
    }
    // virtual servers
    foreach (VMS as [$k, $n, $host, $os, $owner, $ip, $sn]) {
        obj($k, 'virtual_server', ['text-70141' => $n, 'ref-65439' => oid($host), 'ref-43625' => oid($os), 'ref-63703' => oid($owner)],
            false, null, iface_mds([[$ip, $sn, $n, mac()]]));
    }
    // Hamburg
    dev('rt_hh', 'router', 'rt-hh-edge01', 'Cisco', 'ISR 1121-8P', 'r_hh_tech', ['ref-68233' => oid('os_iosxe'), 'ref-58400' => oid('u_tschulz')], [['10.20.99.1', 'net_hh_mgmt']], '00:1E:BD');
    dev('fw_hh1', 'appliance', 'fw-hh-01', 'Fortinet', 'FortiGate 60F', 'r_hh_tech', $app('os_fortios', 'u_akaya'), [['10.20.99.2', 'net_hh_mgmt']], '00:09:0F');
    dev('cpe_hh1', 'appliance', 'cpe-hh-01', 'Genexis', 'Pure ED500 Glasfaser-Modem', 'r_hh_tech');
    dev('sw_hh1', 'switch', 'sw-hh-acc01', 'Cisco', 'Catalyst C9200-24P', 'r_hh_tech', $net('os_iosxe', 'u_tschulz'), [['10.20.99.11', 'net_hh_mgmt']], '70:B3:17');
    dev('nas_hh1', 'appliance', 'nas-hh-01', 'Synology', 'RackStation RS1221RP+', 'r_hh_tech', $app('os_dsm', 'u_hpetersen'), [['10.20.20.10', 'net_hh_cli']], '00:11:32');
    dev('pp_hh1', 'patch_panel', 'PP-HH-R01-CU01', 'Telegärtner', 'MPP24-HD Cat.6A 24-Port', 'r_hh_tech');
    // WLAN + printers
    foreach ([['ap_ber1', 'ap-ber-3og-01', 'r_it', '10.10.99.51', 'net_mgmt', '36'], ['ap_ber2', 'ap-ber-2og-01', 'r_sales', '10.10.99.52', 'net_mgmt', '44'],
              ['ap_ber3', 'ap-ber-2og-02', 'r_fin', '10.10.99.53', 'net_mgmt', '100'], ['ap_ber4', 'ap-ber-4og-01', 'r_gf', '10.10.99.54', 'net_mgmt', '52'],
              ['ap_hh1', 'ap-hh-eg-01', 'r_hh_office', '10.20.99.51', 'net_hh_mgmt', '36']] as [$k, $n, $room, $ip, $sn, $ch]) {
        dev($k, 'wireless_access_point', $n, 'Cisco', 'Catalyst 9120AXI', $room, ['text-97978' => 'NORDLICHT-CORP', 'text-60846' => '802.11ax (Wi-Fi 6)',
            'text-17637' => $ch, 'text-46053' => 'WPA3-Enterprise (802.1X)', 'text-35494' => 'AES-CCMP', 'ref-36834' => oid('u_tschulz')], [[$ip, $sn]], '68:7D:B4');
    }
    foreach ([['prn_ber1', 'prn-ber-2og-01', 'Color LaserJet Enterprise M555dn', 'r_sales', '10.10.30.11', 'net_prn'],
              ['prn_ber2', 'prn-ber-3og-01', 'LaserJet Enterprise M611dn', 'r_it', '10.10.30.12', 'net_prn'],
              ['prn_ber3', 'prn-ber-4og-01', 'Color LaserJet Enterprise MFP M578f', 'r_gf', '10.10.30.13', 'net_prn'],
              ['prn_hh1', 'prn-hh-eg-01', 'LaserJet Enterprise MFP M528f', 'r_hh_office', '10.20.20.200', 'net_hh_cli']] as [$k, $n, $m, $room, $ip, $sn]) {
        dev($k, 'printer', $n, 'HP', $m, $room, [], [[$ip, $sn]], '3C:52:82');
    }
    // workplaces: client (+ user assignment + OS) and monitors per person
    $CLIENTS = [];
    $ipBer = 100;
    $ipHh = 100;
    foreach (PEOPLE as $i => [$uk, $first, $last, $dept, $room]) {
        $hh = str_starts_with($room, 'r_hh');
        $ip = $hh ? '10.20.20.' . (++$ipHh) : '10.10.20.' . (++$ipBer);
        $laptop = in_array($dept, ['Vertrieb', 'Geschäftsführung', 'IT-Leitung', 'Informationssicherheit'], true);
        $n = sprintf('%s-%s-%03d', $laptop ? 'nb' : 'pc', $hh ? 'hh' : 'ber', $i + 1);
        dev("cl_$uk", 'client', $n, 'Dell', $laptop ? 'Latitude 7450' : 'OptiPlex 7010 Tower', $room,
            ['ref-47570' => oid('os_win11'), 'ref-58324' => oid($uk)], [[$ip, $hh ? 'net_hh_cli' : 'net_cli']], $laptop ? 'D0:8E:79' : '74:86:E2');
        $CLIENTS[] = ["cl_$uk", $n, $uk, $room, $laptop];
        $monitors = (str_starts_with($dept, 'IT') || $dept === 'Informationssicherheit') ? 2 : 1;
        for ($m = 1; $m <= $monitors; $m++) {
            obj("mon_{$uk}_$m", 'monitor', ['text-39536' => "$n-MON$m", 'dg-modelspec-manufacturer' => 'Dell', 'dg-modelspec-model' => 'P2725H 27"',
                'dg-modelspec-serial' => 'CN0' . rnd_str(8), 'ref-12314' => oid("cl_$uk")], $room, "$n-MON$m");
        }
    }
}

// ============================================================================================ racks

function phase_racks(): void
{
    say('=== racks');
    foreach ([['rack_ber1', 'BER-R01', 'R01', 42, 'Netzwerk: Edge, Firewall-Cluster, Core/Access, OOB, USV', 'r_srv'],
              ['rack_ber2', 'BER-R02', 'R02', 42, 'Server: VMware-Cluster, Storage, Backup/Tape, USV', 'r_srv'],
              ['rack_hh1', 'HH-R01', 'R01', 24, 'Wandverteiler Niederlassung Hamburg', 'r_hh_tech']] as [$k, $n, $nr, $h, $notes, $room]) {
        obj($k, 'rack', ['dg-rack-name' => $n, 'dg-rack-number' => $nr, 'dg-rack-height' => $h, 'dg-rack-notes' => $notes], $room, $n);
    }
    $heights = ['rack_ber1' => 42, 'rack_ber2' => 42, 'rack_hh1' => 24];
    foreach (LAYOUT as $rk => $items) {
        $used = [];
        foreach ($items as $pos => [$dk, $top, $h, $area]) {
            $body = ['kind' => 'MOUNT', 'object_id' => oid($dk), 'area' => $area];
            if ($top) {
                $body += ['start_slot' => $top, 'height' => $h];
                for ($u = $top; $u > $top - $h; $u--) {
                    $used[$u] = true;
                }
            } else {
                $body['position'] = 1;
            }
            api('POST', '/racks/' . oid($rk) . '/mounts/', $body);
        }
        foreach (RESERVATIONS as [$r, $label, $top, $h]) {
            if ($r === $rk) {
                api('POST', '/racks/' . oid($rk) . '/mounts/', ['kind' => 'RESERVATION', 'label' => $label, 'area' => 'FULL_DEPTH',
                    'start_slot' => $top, 'height' => $h, 'color' => '#FFC107']);
                for ($u = $top; $u > $top - $h; $u--) {
                    $used[$u] = true;
                }
            }
        }
        // close every remaining gap with blanking panels so the rack is completely populated
        $blanks = 0;
        for ($u = $heights[$rk]; $u >= 1;) {
            if (isset($used[$u])) {
                $u--;
                continue;
            }
            $top = $u;
            while ($u >= 1 && !isset($used[$u])) {
                $u--;
            }
            $h = $top - $u;
            $body = ['kind' => 'BLOCKER', 'label' => $h > 1 ? "Blindplatten {$h} HE" : 'Blindplatte 1 HE', 'area' => 'FRONT', 'start_slot' => $top, 'height' => $h, 'color' => '#9E9E9E'];
            [$c, $r] = http('POST', '/racks/' . oid($rk) . '/mounts/', $body);
            if ($c >= 300) {
                unset($body['label'], $body['color']);
                api('POST', '/racks/' . oid($rk) . '/mounts/', $body);
            }
            $blanks += $h;
        }
        say("  $rk: " . count($items) . " devices, $blanks HE Blindplatten");
    }
}

// ============================================================================================ cabling

function bulk(string $k, string $syntax, int $count, ?string $ptype, ?string $speed, int $start = 1, string $kind = 'STANDARD', ?string $desc = null): void
{
    $body = ['device_kind' => $kind, 'syntax' => $syntax, 'count' => $count, 'start_index' => $start,
             'status' => option('PORT_STATUS', 'Up'), 'port_type' => $ptype ? option('PORT_TYPE', $ptype) : null,
             'speed' => $speed ? option('PORT_SPEED', $speed) : null];
    if ($desc) {
        $body['description'] = $desc;
    }
    if ($kind === 'PATCH_PANEL') {
        $body += ['rear_syntax' => 'R{n:02}', 'rear_status' => option('PORT_STATUS', 'Up'), 'rear_port_type' => $body['port_type']];
    }
    api('POST', '/ports/object/' . oid($k) . '/bulk', $body);
}

function port(string $k, string $name, string $side = 'single'): int
{
    global $PORTS;
    if (!isset($PORTS[$k])) {
        foreach (results(api('GET', '/ports/object/' . oid($k) . '?limit=5000')) as $p) {
            $PORTS[$k]["{$p['side']}:{$p['name']}"] = $p;
        }
    }
    return $PORTS[$k]["$side:$name"]['public_id'] ?? fail("port $k $side:$name not found");
}

/** a/b = [object key, port name(, side)] */
function cable(array $a, array $b, ?string $type, ?string $len, ?string $color, ?string $desc, ?string $ci = null): void
{
    global $CAB;
    $CAB++;
    $body = ['endpoints' => [port(...$a), port(...$b)], 'connection_type' => 'CABLE'];
    if ($ci) {
        $body['cable_ci_id'] = oid($ci);
    } else {
        $body += ['cable_name' => sprintf('K-%04d', $CAB), 'cable_type' => option('CABLE_TYPE', $type), 'cable_length' => $len,
                  'cable_color' => $color, 'cable_description' => $desc];
    }
    api('POST', '/port_connections/', $body);
}

function set_port(string $k, string $name, array $changes, string $side = 'single'): void
{
    $id = port($k, $name, $side);
    $cur = api('GET', "/ports/$id");
    $cur = $cur['result'] ?? $cur;
    $body = array_intersect_key($cur, array_flip(['object_id', 'name', 'side', 'port_number', 'status', 'port_type', 'speed', 'description']));
    api('PUT', "/ports/$id", array_merge($body, $changes));
}

function phase_cabling(): void
{
    global $CLIENTS, $CAB, $PORTS;
    say('=== ports');
    // ---- network ports
    bulk('rt_ber', 'Gi0/0/{n}', 4, 'RJ45', '1G', 0);
    foreach (['fw_ber1', 'fw_ber2'] as $fw) {
        bulk($fw, 'port{n}', 16, 'RJ45', '1G');
        bulk($fw, 'x{n}', 4, 'SFP+', '10G');
        bulk($fw, 'ha{n}', 2, 'RJ45', '1G', 1, 'STANDARD', 'HA-Heartbeat');
        bulk($fw, 'mgmt', 1, 'RJ45', '1G', 1, 'STANDARD', 'Out-of-band Management');
    }
    foreach (['sw_core1', 'sw_core2'] as $sw) {
        bulk($sw, 'Twe1/0/{n}', 24, 'SFP28', '25G');
        bulk($sw, 'Hu1/0/{n}', 4, 'QSFP28', '100G', 25);
        bulk($sw, 'Gi0/0', 1, 'RJ45', '1G', 1, 'STANDARD', 'Out-of-band Management');
    }
    foreach (['sw_acc1', 'sw_acc2', 'sw_acc3'] as $sw) {
        bulk($sw, 'Gi1/0/{n}', 48, 'RJ45', '1G');
        bulk($sw, 'Te1/1/{n}', 4, 'SFP+', '10G');
    }
    bulk('sw_oob1', 'Gi1/0/{n}', 24, 'RJ45', '1G');
    bulk('sw_oob1', 'Gi1/1/{n}', 4, 'SFP', '1G');
    bulk('wlc_ber1', 'Te0/1/{n}', 4, 'SFP+', '10G', 0);
    bulk('ise_ber1', 'eth{n}', 2, 'RJ45', '1G', 0);
    bulk('con_ber1', 'NET{n}', 2, 'RJ45', '1G');
    bulk('con_ber1', 'Serial{n:02}', 48, 'RJ45', null, 1, 'STANDARD', 'RS-232 Konsole');
    bulk('ntp_ber1', 'LAN{n}', 2, 'RJ45', '1G', 0);
    bulk('cpe_ber1', 'LAN{n}', 2, 'RJ45', '1G');
    bulk('cpe_ber1', 'WAN', 1, 'LC', '10G', 1, 'STANDARD', 'Glasfaser vom Hausübergabepunkt (Provider)');
    foreach (['pp_r01_cu1', 'pp_r01_cu2', 'pp_r01_cu3', 'pp_r02_cu1', 'pp_hh1'] as $pp) {
        bulk($pp, 'F{n:02}', 24, 'RJ45', '10G', 1, 'PATCH_PANEL');
    }
    foreach (['pp_r01_fo1', 'pp_r02_fo1'] as $pp) {
        bulk($pp, 'F{n:02}', 24, 'LC', '25G', 1, 'PATCH_PANEL');
    }
    foreach (SERVERS as [$k, $n, , , , $oob]) {
        bulk($k, 'NIC1-P{n}', 2, 'SFP28', '25G', 1, 'STANDARD', 'Broadcom 57414 25GbE (LACP)');
        bulk($k, 'eno{n}', 2, 'RJ45', '1G', 1, 'STANDARD', 'LOM 1GbE');
        bulk($k, $oob, 1, 'RJ45', '1G', 1, 'STANDARD', 'Out-of-band Management');
    }
    bulk('srv_bak1', 'HBA-P{n}', 2, 'LC', null, 1, 'STANDARD', 'Emulex LPe35002 32G FC (Tape)');
    bulk('sto_ber1', 'e0c', 1, 'SFP28', '25G');
    bulk('sto_ber1', 'e0d', 1, 'SFP28', '25G');
    bulk('sto_ber1', 'e0M', 1, 'RJ45', '1G', 1, 'STANDARD', 'Management');
    bulk('tl_ber1', 'FC{n}', 2, 'LC', null, 1, 'STANDARD', 'LTO-9 Laufwerk FC');
    bulk('tl_ber1', 'LAN', 1, 'RJ45', '1G', 1, 'STANDARD', 'Management');
    bulk('kvm_ber1', 'LAN{n}', 2, 'RJ45', '1G');
    bulk('rt_hh', 'Gi0/0/{n}', 2, 'RJ45', '1G', 0);
    bulk('fw_hh1', 'wan{n}', 2, 'RJ45', '1G');
    bulk('fw_hh1', 'internal{n}', 5, 'RJ45', '1G');
    bulk('fw_hh1', 'dmz', 1, 'RJ45', '1G');
    bulk('cpe_hh1', 'LAN', 1, 'RJ45', '1G');
    bulk('sw_hh1', 'Gi1/0/{n}', 24, 'RJ45', '1G');
    bulk('sw_hh1', 'Gi1/1/{n}', 4, 'SFP', '1G');
    bulk('nas_hh1', 'LAN{n}', 4, 'RJ45', '1G');
    foreach (['ap_ber1', 'ap_ber2', 'ap_ber3', 'ap_ber4', 'ap_hh1'] as $k) {
        bulk($k, 'Gi0', 1, 'RJ45', '5G', 1, 'STANDARD', 'mGig PoE+ Uplink');
    }
    foreach (['prn_ber1', 'prn_ber2', 'prn_ber3', 'prn_hh1'] as $k) {
        bulk($k, 'eth0', 1, 'RJ45', '1G');
    }
    foreach ($CLIENTS as [$ck]) {
        bulk($ck, 'eth0', 1, 'RJ45', '1G', 1, 'STANDARD', 'Intel I219-LM');
    }
    // ---- power ports
    foreach (['pdu_r01a', 'pdu_r01b', 'pdu_r02a', 'pdu_r02b'] as $k) {
        bulk($k, 'C13-{n:02}', 21, 'C13', null);
        bulk($k, 'C19-{n}', 3, 'C19', null);
        bulk($k, 'Input', 1, str_ends_with($k, 'a') ? 'C20' : 'IEC 60309 16A', null, 1, 'STANDARD', 'Einspeisung');
        bulk($k, 'NET', 1, 'RJ45', '1G', 1, 'STANDARD', 'Network Management Card');
    }
    foreach (['pdu_hh1a', 'pdu_hh1b'] as $k) {
        bulk($k, 'C13-{n:02}', 14, 'C13', null);
        bulk($k, 'C19-{n}', 2, 'C19', null);
        bulk($k, 'Input', 1, $k === 'pdu_hh1a' ? 'C14' : 'IEC 60309 16A', null, 1, 'STANDARD', 'Einspeisung');
        bulk($k, 'NET', 1, 'RJ45', '1G', 1, 'STANDARD', 'Network Management Card');
    }
    foreach (['usv_r01' => 'IEC 60309 32A', 'usv_r02' => 'IEC 60309 32A', 'usv_hh1' => 'C14'] as $k => $in) {
        bulk($k, 'Input', 1, $in, null, 1, 'STANDARD', 'Netzeinspeisung');
        if ($k !== 'usv_hh1') {
            bulk($k, 'C19-{n}', 4, 'C19', null);
        }
        bulk($k, 'C13-{n}', 6, 'C13', null);
        bulk($k, 'NMC', 1, 'RJ45', '1G', 1, 'STANDARD', 'AP9641 Network Management Card 3');
        if ($k !== 'usv_hh1') {
            bulk($k, 'Battery-IN', 1, 'Anderson SB50', null, 1, 'STANDARD', 'Externe Batterie');
        }
    }
    foreach (['bat_r01', 'bat_r02a', 'bat_r02b'] as $k) {
        bulk($k, 'DC-OUT', 1, 'Anderson SB50', null);
        bulk($k, 'DC-IN', 1, 'Anderson SB50', null);
    }
    foreach (POWER as $devices) {
        foreach ($devices as $k => $psus) {
            bulk($k, $psus === 1 ? 'PSU' : 'PSU{n}', $psus, 'C14', null, 1, 'STANDARD', 'Netzteil');
        }
    }

    say('=== cabling');
    // cable objects: fiber trunk + spare stock
    for ($i = 1; $i <= 12; $i++) {
        obj(sprintf('cab_trunk_%02d', $i), 'cable', ['dg-cable-name' => sprintf('LWL-TRUNK-BER-R02-R01-%02d', $i), 'dg-cable-type' => 'OM4',
            'dg-cable-length' => '15 m', 'dg-cable-color' => 'violett', 'dg-cable-description' => 'Vorkonfektioniertes LC-Duplex Trunkkabel im Doppelboden'], false);
    }
    foreach ([['Cat6a', '2 m', 'blau'], ['Cat6a', '5 m', 'gelb'], ['OM4', '3 m', 'violett']] as $i => [$t, $l, $c]) {
        obj('cab_spare_' . ($i + 1), 'cable', ['dg-cable-name' => sprintf('LAGER-PK-%03d', $i + 1), 'dg-cable-type' => $t,
            'dg-cable-length' => $l, 'dg-cable-color' => $c, 'dg-cable-description' => 'Ersatzkabel im Lager (nicht verbaut)'], false);
    }
    // Berlin backbone
    foreach (['Hu1/0/27', 'Hu1/0/28'] as $p) {
        cable(['sw_core1', $p], ['sw_core2', $p], 'DAC', '1 m', 'schwarz', 'StackWise Virtual Link');
    }
    cable(['cpe_ber1', 'LAN1'], ['rt_ber', 'Gi0/0/0'], 'Cat6a', '1 m', 'rot', 'Provider-Übergabe DeutschlandLAN Connect IP 1 Gbit/s');
    cable(['rt_ber', 'Gi0/0/1'], ['fw_ber1', 'port1'], 'Cat6a', '1 m', 'rot', 'WAN-Transfer Edge -> FW01');
    cable(['rt_ber', 'Gi0/0/2'], ['fw_ber2', 'port1'], 'Cat6a', '1 m', 'rot', 'WAN-Transfer Edge -> FW02');
    foreach (['ha1', 'ha2'] as $p) {
        cable(['fw_ber1', $p], ['fw_ber2', $p], 'Cat6a', '0.5 m', 'gelb', 'FortiGate HA-Heartbeat');
    }
    foreach ([['fw_ber1', 'Twe1/0/23'], ['fw_ber2', 'Twe1/0/22']] as [$fw, $cp]) {
        cable([$fw, 'x1'], ['sw_core1', $cp], 'OM4', '2 m', 'violett', 'Firewall-Uplink (LACP)');
        cable([$fw, 'x2'], ['sw_core2', $cp], 'OM4', '2 m', 'violett', 'Firewall-Uplink (LACP)');
    }
    foreach (['sw_acc1', 'sw_acc2', 'sw_acc3'] as $i => $acc) {
        cable([$acc, 'Te1/1/1'], ['sw_core1', 'Twe1/0/' . ($i + 1)], 'OM4', '1 m', 'violett', 'Access-Uplink (MEC)');
        cable([$acc, 'Te1/1/2'], ['sw_core2', 'Twe1/0/' . ($i + 1)], 'OM4', '1 m', 'violett', 'Access-Uplink (MEC)');
    }
    cable(['wlc_ber1', 'Te0/1/0'], ['sw_core1', 'Twe1/0/20'], 'OM4', '1 m', 'violett', 'WLC-Uplink (LAG)');
    cable(['wlc_ber1', 'Te0/1/1'], ['sw_core2', 'Twe1/0/20'], 'OM4', '1 m', 'violett', 'WLC-Uplink (LAG)');
    cable(['ise_ber1', 'eth0'], ['sw_acc2', 'Gi1/0/40'], 'Cat6a', '1 m', 'blau', 'ISE Daten');
    cable(['ise_ber1', 'eth1'], ['sw_acc2', 'Gi1/0/41'], 'Cat6a', '1 m', 'blau', 'ISE Daten (Bond)');
    cable(['ntp_ber1', 'LAN0'], ['sw_acc2', 'Gi1/0/42'], 'Cat6a', '1 m', 'blau', 'NTP/PTP Zeitserver');
    cable(['sw_oob1', 'Gi1/0/24'], ['sw_acc2', 'Gi1/0/43'], 'Cat6a', '1 m', 'gelb', 'OOB-Switch Uplink');
    foreach ([[['sw_core1', 'Gi0/0'], 1], [['sw_core2', 'Gi0/0'], 2], [['fw_ber1', 'mgmt'], 3], [['fw_ber2', 'mgmt'], 4],
              [['rt_ber', 'Gi0/0/3'], 5], [['con_ber1', 'NET1'], 6], [['pdu_r01a', 'NET'], 7], [['pdu_r01b', 'NET'], 8],
              [['usv_r01', 'NMC'], 9], [['ntp_ber1', 'LAN1'], 10]] as [$a, $sp]) {
        cable($a, ['sw_oob1', "Gi1/0/$sp"], 'Cat6a', '1 m', 'gelb', 'OOB-Management VLAN 99');
    }
    // trunks R02 <-> R01: 12 fibre pairs (inventoried cable objects) and 24 copper links
    for ($n = 1; $n <= 24; $n++) {
        if ($n <= 12) {
            cable(['pp_r02_fo1', sprintf('R%02d', $n), 'rear'], ['pp_r01_fo1', sprintf('R%02d', $n), 'rear'], null, null, null, null, sprintf('cab_trunk_%02d', $n));
        }
        cable(['pp_r02_cu1', sprintf('R%02d', $n), 'rear'], ['pp_r01_cu2', sprintf('R%02d', $n), 'rear'], 'Cat6a', '14 m', 'grau', 'Kupfer-Trunk R02 -> R01 (Doppelboden)');
    }
    // server rack -> network rack via patch panels
    $hosts = [];
    foreach (SERVERS as [$k, $n, , , , $oob]) {
        $hosts[] = [$k, $n, ['NIC1-P1', 'NIC1-P2'], $oob, true];
    }
    $hosts[] = ['sto_ber1', 'sto-ber-01', ['e0c', 'e0d'], 'e0M', false];
    $fo = 0;
    foreach ($hosts as $si => [$k, $n, $dataPorts, $oob, $isServer]) {
        $si++;
        foreach ($dataPorts as $j => $p) {
            $fo++;
            $core = $j === 0 ? 'sw_core1' : 'sw_core2';
            cable([$k, $p], ['pp_r02_fo1', sprintf('F%02d', $fo), 'front'], 'OM4', '1 m', 'violett', "$n $p");
            cable(['pp_r01_fo1', sprintf('F%02d', $fo), 'front'], [$core, 'Twe1/0/' . (4 + $si)], 'OM4', '2 m', 'violett', "$n $p");
        }
        cable([$k, $oob], ['pp_r02_cu1', sprintf('F%02d', $si), 'front'], 'Cat6a', '1 m', 'gelb', "$n $oob");
        cable(['pp_r01_cu2', sprintf('F%02d', $si), 'front'], ['sw_acc2', "Gi1/0/$si"], 'Cat6a', '0.5 m', 'gelb', "$n $oob");
        if ($isServer) {
            cable([$k, 'eno1'], ['pp_r02_cu1', sprintf('F%02d', 6 + $si), 'front'], 'Cat6a', '1 m', 'grün', "$n eno1 Mgmt");
            cable(['pp_r01_cu2', sprintf('F%02d', 6 + $si), 'front'], ['sw_acc2', 'Gi1/0/' . (6 + $si)], 'Cat6a', '0.5 m', 'grün', "$n eno1 Mgmt");
        }
    }
    // R02 management devices via copper trunk F19-F24
    foreach ([['tl_ber1', 'LAN', 19], ['kvm_ber1', 'LAN1', 20], ['usv_r02', 'NMC', 21], ['pdu_r02a', 'NET', 22], ['pdu_r02b', 'NET', 23]] as [$d, $p, $f]) {
        cable([$d, $p], ['pp_r02_cu1', "F$f", 'front'], 'Cat6a', '1 m', 'gelb', "$d $p");
        cable(['pp_r01_cu2', "F$f", 'front'], ['sw_acc2', "Gi1/0/$f"], 'Cat6a', '0.5 m', 'gelb', "$d $p");
    }
    // tape library FC direct to backup server
    cable(['tl_ber1', 'FC1'], ['srv_bak1', 'HBA-P1'], 'OM4', '2 m', 'violett', 'FC LTO-9 Laufwerk 1');
    cable(['tl_ber1', 'FC2'], ['srv_bak1', 'HBA-P2'], 'OM4', '2 m', 'violett', 'FC LTO-9 Laufwerk 2');
    // office floors
    $floor = ['r_it' => 'pp_r01_cu1', 'r_sales' => 'pp_r01_cu3', 'r_fin' => 'pp_r01_cu3', 'r_gf' => 'pp_r01_cu3', 'r_hh_office' => 'pp_hh1'];
    $roomNr = ['r_it' => '3.12', 'r_sales' => '2.05', 'r_fin' => '2.10', 'r_gf' => '4.01', 'r_hh_office' => 'EG-01'];
    $eps = array_map(fn($c) => [$c[0], 'eth0', $c[3], 'blau', $c[1]], $CLIENTS);
    foreach ([['prn_ber2', 'eth0', 'r_it', 'grün'], ['prn_ber1', 'eth0', 'r_sales', 'grün'], ['prn_ber3', 'eth0', 'r_gf', 'grün'],
              ['prn_hh1', 'eth0', 'r_hh_office', 'grün'], ['ap_ber1', 'Gi0', 'r_it', 'gelb'], ['ap_ber2', 'Gi0', 'r_sales', 'gelb'],
              ['ap_ber3', 'Gi0', 'r_fin', 'gelb'], ['ap_ber4', 'Gi0', 'r_gf', 'gelb'], ['ap_hh1', 'Gi0', 'r_hh_office', 'gelb']] as $e) {
        $eps[] = [$e[0], $e[1], $e[2], $e[3], $e[0]];
    }
    $ppIdx = [];
    $swIdx = ['sw_acc1' => 0, 'sw_hh1' => 0];
    $lens = [18, 24, 31, 37, 42, 48];
    foreach ($eps as [$dk, $dp, $room, $color, $n]) {
        $pp = $floor[$room];
        $i = $ppIdx[$pp] = ($ppIdx[$pp] ?? 0) + 1;
        $sw = $pp === 'pp_hh1' ? 'sw_hh1' : 'sw_acc1';
        $swIdx[$sw]++;
        cable([$dk, $dp], [$pp, sprintf('R%02d', $i), 'rear'], 'Cat6a', $lens[mt_rand(0, 5)] . ' m', 'weiß', sprintf('Datendose %s-%02d -> %s (Verlegekabel)', $roomNr[$room], $i, $n));
        cable([$pp, sprintf('F%02d', $i), 'front'], [$sw, 'Gi1/0/' . $swIdx[$sw]], 'Cat6', '0.5 m', $color, $n);
    }
    // Hamburg
    cable(['cpe_hh1', 'LAN'], ['rt_hh', 'Gi0/0/0'], 'Cat6a', '0.5 m', 'rot', 'Provider-Übergabe Glasfaser 500 Mbit/s');
    cable(['rt_hh', 'Gi0/0/1'], ['fw_hh1', 'wan1'], 'Cat6a', '0.5 m', 'rot', 'WAN-Transfer Edge -> FW');
    cable(['fw_hh1', 'internal1'], ['sw_hh1', 'Gi1/0/24'], 'Cat6a', '0.5 m', 'blau', 'LAN-Uplink FW -> Switch');
    cable(['nas_hh1', 'LAN1'], ['sw_hh1', 'Gi1/0/20'], 'Cat6a', '0.5 m', 'blau', 'NAS Bond');
    cable(['nas_hh1', 'LAN2'], ['sw_hh1', 'Gi1/0/21'], 'Cat6a', '0.5 m', 'blau', 'NAS Bond');
    cable(['pdu_hh1a', 'NET'], ['sw_hh1', 'Gi1/0/22'], 'Cat6a', '0.5 m', 'gelb', 'PDU Management');
    cable(['pdu_hh1b', 'NET'], ['sw_hh1', 'Gi1/0/23'], 'Cat6a', '0.5 m', 'gelb', 'PDU Management');
    cable(['usv_hh1', 'NMC'], ['sw_hh1', 'Gi1/0/19'], 'Cat6a', '0.5 m', 'gelb', 'USV Management');
    $network = $CAB;

    // ---- power cabling: UPS -> PDU A, batteries -> UPS, every PSU -> PDU A / PDU B
    cable(['usv_r01', 'C19-1'], ['pdu_r01a', 'Input'], 'Stromkabel C19/C20', '2 m', 'schwarz', 'A-Feed USV -> PDU');
    cable(['usv_r02', 'C19-1'], ['pdu_r02a', 'Input'], 'Stromkabel C19/C20', '2 m', 'schwarz', 'A-Feed USV -> PDU');
    cable(['usv_hh1', 'C13-1'], ['pdu_hh1a', 'Input'], 'Kaltgerätekabel C13/C14', '1.5 m', 'schwarz', 'A-Feed USV -> PDU');
    cable(['bat_r01', 'DC-OUT'], ['usv_r01', 'Battery-IN'], 'Batterieleitung (Anderson SB50)', '1 m', 'schwarz', 'Batterieerweiterung');
    cable(['bat_r02a', 'DC-OUT'], ['usv_r02', 'Battery-IN'], 'Batterieleitung (Anderson SB50)', '1 m', 'schwarz', 'Batterieerweiterung');
    cable(['bat_r02b', 'DC-OUT'], ['bat_r02a', 'DC-IN'], 'Batterieleitung (Anderson SB50)', '0.5 m', 'schwarz', 'Batterieerweiterung (Kaskade)');
    $pduOf = ['r01' => ['pdu_r01a', 'pdu_r01b'], 'r02' => ['pdu_r02a', 'pdu_r02b'], 'hh1' => ['pdu_hh1a', 'pdu_hh1b']];
    foreach (POWER as $rack => $devices) {
        $out = [0, 0];
        foreach ($devices as $k => $psus) {
            for ($p = 1; $p <= $psus; $p++) {
                $side = $p - 1;   // PSU1 -> A-Feed (USV), PSU2 -> B-Feed (Netz)
                $out[$side]++;
                cable([$k, $psus === 1 ? 'PSU' : "PSU$p"], [$pduOf[$rack][$side], sprintf('C13-%02d', $out[$side])], 'Kaltgerätekabel C13/C14',
                    '1 m', $side === 0 ? 'rot' : 'blau', ($side === 0 ? 'A-Feed (USV)' : 'B-Feed (Netz)'));
            }
        }
    }
    say("  cables: $network network, " . ($CAB - $network) . ' power');

    // ---- port states and descriptions
    set_port('cpe_ber1', 'WAN', ['description' => 'Glasfaser vom Hausübergabepunkt, Leitungs-ID 4711-0815']);
    set_port('fw_hh1', 'wan2', ['status' => option('PORT_STATUS', 'Down'), 'description' => 'Reserve: LTE-Backup geplant']);
    set_port('usv_r01', 'Input', ['description' => 'UV-UG-01 F10 (32 A)']);
    set_port('usv_r02', 'Input', ['description' => 'UV-UG-01 F13 (32 A)']);
    set_port('usv_hh1', 'Input', ['description' => 'Wandsteckdose Technikraum (Stromkreis F3)']);
    foreach (['pdu_r01b' => 'UV-UG-01 F11 (16 A)', 'pdu_r02b' => 'UV-UG-01 F12 (16 A)', 'pdu_hh1b' => 'UV-EG-02 F4 (16 A)'] as $k => $d) {
        set_port($k, 'Input', ['description' => "Netz: $d"]);
    }
    foreach (['sw_acc1', 'sw_acc2', 'sw_acc3', 'sw_hh1', 'sw_oob1'] as $sw) {
        $pids = [];
        foreach (results(api('GET', '/port_connections/object/' . oid($sw) . '?limit=1000')) as $c) {
            foreach ($c['endpoints'] ?? [] as $e) {
                $pids[$e] = true;
            }
        }
        port($sw, 'Gi1/0/1');
        foreach ($PORTS[$sw] as $p) {
            if (isset($pids[$p['public_id']]) || !str_starts_with($p['name'], 'Gi1/0/')) {
                continue;
            }
            $nr = (int)substr($p['name'], strrpos($p['name'], '/') + 1);
            $disabled = $sw === 'sw_acc1' && $nr > 40;
            set_port($sw, $p['name'], ['status' => option('PORT_STATUS', $disabled ? 'Disabled' : 'Down'),
                'description' => $disabled ? 'shutdown (Security Policy)' : null]);
        }
    }
    foreach (SERVERS as [$k]) {
        set_port($k, 'eno2', ['status' => option('PORT_STATUS', 'Down'), 'description' => 'nicht belegt']);
    }

    // ---- port <-> IPAM interface links
    $links = [];
    foreach (SERVERS as [$k, , , , , $oob]) {
        $links[] = [$k, 'NIC1-P1', 1, 'BOND'];
        $links[] = [$k, 'NIC1-P2', 1, 'BOND'];
        $links[] = [$k, $oob, 2, 'PHYSICAL'];
    }
    $links = array_merge($links, [['sto_ber1', 'e0c', 1, 'BOND'], ['sto_ber1', 'e0d', 1, 'BOND'], ['sto_ber1', 'e0M', 2, 'PHYSICAL'],
        ['sw_core1', 'Gi0/0', 1, 'PHYSICAL'], ['sw_core2', 'Gi0/0', 1, 'PHYSICAL'], ['fw_ber1', 'mgmt', 1, 'PHYSICAL'], ['fw_ber2', 'mgmt', 1, 'PHYSICAL'],
        ['ise_ber1', 'eth0', 1, 'BOND'], ['ise_ber1', 'eth1', 1, 'BOND'], ['con_ber1', 'NET1', 1, 'PHYSICAL'], ['ntp_ber1', 'LAN1', 1, 'PHYSICAL'],
        ['tl_ber1', 'LAN', 1, 'PHYSICAL'], ['kvm_ber1', 'LAN1', 1, 'PHYSICAL'], ['nas_hh1', 'LAN1', 1, 'BOND'], ['nas_hh1', 'LAN2', 1, 'BOND']]);
    foreach (['usv_r01', 'usv_r02', 'usv_hh1'] as $k) {
        $links[] = [$k, 'NMC', 1, 'PHYSICAL'];
    }
    foreach (['pdu_r01a', 'pdu_r01b', 'pdu_r02a', 'pdu_r02b', 'pdu_hh1a', 'pdu_hh1b'] as $k) {
        $links[] = [$k, 'NET', 1, 'PHYSICAL'];
    }
    foreach (['ap_ber1', 'ap_ber2', 'ap_ber3', 'ap_ber4', 'ap_hh1'] as $k) {
        $links[] = [$k, 'Gi0', 1, 'PHYSICAL'];
    }
    foreach (['prn_ber1', 'prn_ber2', 'prn_ber3', 'prn_hh1'] as $k) {
        $links[] = [$k, 'eth0', 1, 'PHYSICAL'];
    }
    foreach ($CLIENTS as [$ck]) {
        $links[] = [$ck, 'eth0', 1, 'PHYSICAL'];
    }
    foreach ($links as [$k, $p, $row, $rel]) {
        api('POST', '/ports/' . port($k, $p) . '/interface_links/', ['interface_object_id' => oid($k), 'interface_section_id' => 'dg-ipam-interface',
            'interface_multi_data_id' => $row, 'relation_type' => $rel]);
    }
    say('  interface links: ' . count($links));
}

// ============================================================================================ relations

const APPS = [ // key, name, vendor, version, criticality, owner, url, description, runs on, depends on
    ['app_ad', 'Active Directory', 'Microsoft', '2022 (Forest Level 2016)', 'kritisch', 'u_tschulz', '', 'Zentraler Verzeichnisdienst und Authentifizierung',
     [['vm_dc01', 'Domain Controller (PDC)'], ['vm_dc02', 'Domain Controller']], []],
    ['app_fs', 'Dateidienste', 'Microsoft', 'DFS-N / SMB 3.1.1', 'hoch', 'u_jneumann', '\\\\nordlicht.local\\daten', 'Abteilungs- und Benutzerlaufwerke',
     [['vm_fs01', 'Fileserver']], [['app_ad', 'Authentifizierung']]],
    ['app_sql', 'Microsoft SQL Server', 'Microsoft', '2022 CU14 Standard', 'hoch', 'u_jneumann', '', 'Datenbankplattform für Fachanwendungen',
     [['vm_sql01', 'Datenbankserver']], [['app_ad', 'Authentifizierung']]],
    ['app_erp', 'SAP Business One', 'SAP', '10.0 FP 2405', 'kritisch', 'u_cfischer', 'https://erp.nordlicht.local', 'ERP: Finanzen, Einkauf, Vertrieb',
     [['vm_erp01', 'Applikationsserver']], [['app_ad', 'Single Sign-On'], ['app_sql', 'Datenbank']]],
    ['app_wms', 'LogiWMS', 'Nordwerk Software GmbH', '5.3.2', 'kritisch', 'u_hpetersen', 'https://wms.nordlicht.local', 'Lagerverwaltung Hamburg (Scanner, Kommissionierung)',
     [['vm_wms01', 'Applikationsserver']], [['app_erp', 'Auftragsdaten-Schnittstelle'], ['app_sql', 'Datenbank']]],
    ['app_web', 'Unternehmenswebsite', 'WordPress', '6.6.2', 'mittel', 'u_lbecker', 'https://www.nordlicht-logistik.de', 'Öffentliche Website inkl. Sendungsverfolgung',
     [['vm_web01', 'Webserver (DMZ, aktiv)'], ['vm_web02', 'Webserver (DMZ, passiv)']], [['app_wms', 'Tracking-API']]],
    ['app_mon', 'Zabbix Monitoring', 'Zabbix', '7.0 LTS', 'mittel', 'u_akaya', 'https://monitoring.nordlicht.local', 'Infrastruktur- und Service-Monitoring',
     [['vm_mon01', 'Monitoring-Server']], []],
    ['app_backup', 'Veeam Backup & Replication', 'Veeam', '12.2', 'hoch', 'u_tschulz', '', 'Datensicherung der VMware-Umgebung inkl. Tape-Auslagerung',
     [['vm_veeam01', 'Backup-Server'], ['srv_bak1', 'Backup-Repository (Hardened Linux)']], [['app_ad', 'Authentifizierung']]],
    ['app_print', 'Druckdienste', 'Microsoft', 'Print Server 2022', 'niedrig', 'u_tschulz', '', 'Zentrale Druckerwarteschlangen',
     [['vm_prt01', 'Druckserver']], [['app_ad', 'Authentifizierung']]],
    ['app_m365', 'Microsoft 365', 'Microsoft', 'E3 (SaaS)', 'hoch', 'u_skoch', 'https://portal.office.com', 'E-Mail, Teams, SharePoint (Cloud)',
     [], [['app_ad', 'Entra Connect Sync']]],
    ['app_nac', 'Netzwerkzugangskontrolle (802.1X)', 'Cisco', 'ISE 3.3', 'hoch', 'u_akaya', 'https://ise.nordlicht.local', 'RADIUS/802.1X für LAN und WLAN',
     [], [['app_ad', 'Benutzer- und Computerkonten']]],
];
const RELDEFS = [ // key, name, parent label, child label, parent types, child types, fields, [icons/colors]
    ['rel_runs', 'application-runs-on', 'läuft auf', 'hostet', ['application'], ['virtual_server', 'server', 'appliance'], [['Rolle', 'text']], ['fas fa-cubes', '#7B1FA2', 'fas fa-server', '#1565C0']],
    ['rel_dep', 'application-depends-on', 'hängt ab von', 'wird benötigt von', ['application'], ['application'], [['Art der Abhängigkeit', 'text']], ['fas fa-cubes', '#7B1FA2', 'fas fa-cubes', '#AB47BC']],
    ['rel_workplace', 'workplace', 'Arbeitsplatz in', 'Arbeitsplatz von', ['user'], ['room'], [['Schreibtisch', 'text'], ['Durchwahl', 'text']], ['fas fa-user', '#2E7D32', 'fas fa-door-open', '#795548']],
    ['rel_printer', 'default-printer', 'druckt auf', 'Standarddrucker für', ['user'], ['printer'], [], ['fas fa-user', '#2E7D32', 'fas fa-print', '#33BD03']],
    ['rel_support', 'service-contract', 'betreut', 'wird betreut von', ['company'], ['switch', 'router', 'appliance', 'server', 'ups', 'pdu'], [['Vertragsnummer', 'text'], ['SLA', 'text']], ['fas fa-building', '#0A69C7', 'fas fa-tools', '#607D8B']],
    ['rel_backup', 'backup', 'sichert', 'gesichert durch', ['application'], ['virtual_server'], [['Backup-Job', 'text'], ['Aufbewahrung', 'text']], ['fas fa-save', '#FF8F00', 'fas fa-server', '#9AD112']],
    ['rel_storage', 'storage-provider', 'stellt Speicher bereit für', 'nutzt Speicher von', ['appliance'], ['server'], [['Datastore', 'text'], ['Protokoll', 'text']], ['fas fa-database', '#00838F', 'fas fa-server', '#DF88BD']],
    ['rel_power', 'power-protection', 'schützt', 'abgesichert durch', ['ups'], ['pdu'], [['Autonomiezeit', 'text']], ['fas fa-car-battery', '#00897B', 'fas fa-bolt', '#F9A825']],
];

function phase_relations(): void
{
    global $TID;
    say('=== applications & relations');
    foreach (APPS as [$k, $n, $vendor, $ver, $crit, $owner, $url, $desc]) {
        obj($k, 'application', ['app-name' => $n, 'app-vendor' => $vendor, 'app-version' => $ver, 'app-criticality' => $crit,
            'app-lifecycle' => 'Produktiv', 'app-owner' => oid($owner), 'app-url' => $url, 'app-description' => $desc], false);
    }
    $defs = [];
    foreach (RELDEFS as [$k, $name, $pl, $cl, $pt, $ct, $fields, $look]) {
        $flds = [];
        foreach ($fields as $i => [$label, $type]) {
            $flds[] = ['type' => $type, 'name' => "$name-f" . ($i + 1), 'label' => $label];
        }
        $body = ['relation_name' => $name, 'relation_name_parent' => $pl, 'relation_name_child' => $cl,
                 'parent_type_ids' => array_map(fn($t) => $TID[$t], $pt), 'child_type_ids' => array_map(fn($t) => $TID[$t], $ct),
                 'description' => "$pl / $cl", 'relation_icon_parent' => $look[0], 'relation_color_parent' => $look[1],
                 'relation_icon_child' => $look[2], 'relation_color_child' => $look[3], 'fields' => $flds,
                 'sections' => $flds ? [['type' => 'section', 'name' => "$name-sec", 'label' => 'Details', 'fields' => array_column($flds, 'name')]] : []];
        $defs[$k] = ['id' => new_id(api('POST', '/relations/', $body)), 'name' => $name];
    }
    $count = 0;
    $link = function (string $rk, string $parent, string $child, ...$vals) use ($defs, &$count) {
        $fv = [];
        foreach ($vals as $i => $v) {
            $fv[] = ['name' => $defs[$rk]['name'] . '-f' . ($i + 1), 'value' => $v];
        }
        api('POST', '/object_relations/', ['relation_id' => $defs[$rk]['id'], 'relation_parent_id' => oid($parent), 'relation_child_id' => oid($child),
            'relation_parent_type_id' => 0, 'relation_child_type_id' => 0, 'field_values' => $fv]);
        $count++;
    };
    foreach (APPS as [$k, , , , , , , , $runs, $deps]) {
        foreach ($runs as [$t, $role]) {
            $link('rel_runs', $k, $t, $role);
        }
        foreach ($deps as [$t, $kind]) {
            $link('rel_dep', $k, $t, $kind);
        }
    }
    $link('rel_runs', 'app_nac', 'ise_ber1', 'Policy Service Node');
    $printers = ['r_it' => 'prn_ber2', 'r_sales' => 'prn_ber1', 'r_fin' => 'prn_ber1', 'r_gf' => 'prn_ber3', 'r_hh_office' => 'prn_hh1'];
    foreach (PEOPLE as $i => [$uk, , , , $room, $desk]) {
        $link('rel_workplace', $uk, $room, $desk, '-' . (201 + $i));
        $link('rel_printer', $uk, $printers[$room]);
    }
    foreach (['sw_core1', 'sw_core2', 'sw_acc1', 'sw_acc2', 'sw_acc3', 'sw_oob1', 'sw_hh1', 'rt_ber', 'rt_hh', 'fw_ber1', 'fw_ber2', 'fw_hh1', 'wlc_ber1', 'ise_ber1'] as $d) {
        $link('rel_support', 'c_hanseit', $d, 'HIT-2024-0117', 'Gold 24x7, 4h Reaktionszeit');
    }
    foreach (SERVERS as [$k]) {
        $link('rel_support', 'c_hanseit', $k, 'HIT-2024-0118', 'Silver 5x9, NBD');
    }
    foreach (['usv_r01', 'usv_r02', 'usv_hh1'] as $k) {
        $link('rel_support', 'c_hanseit', $k, 'HIT-2025-0042', 'Wartung 1x jährlich, Batterietausch inkl.');
    }
    foreach (VMS as [$vk]) {
        $link('rel_backup', 'app_backup', $vk, str_starts_with($vk, 'vm_web') ? 'BJ-DMZ-Daily' : 'BJ-VM-Daily', '30 Tage + 12 Monate (GFS), Immutable + Tape');
    }
    foreach (['srv_esx1', 'srv_esx2', 'srv_esx3'] as $k) {
        $link('rel_storage', 'sto_ber1', $k, 'DS-VMFS-PROD-01', 'NFS 4.1');
    }
    foreach ([['usv_r01', 'pdu_r01a', '18 min'], ['usv_r02', 'pdu_r02a', '24 min'], ['usv_hh1', 'pdu_hh1a', '35 min']] as [$u, $p, $t]) {
        $link('rel_power', $u, $p, $t);
    }
    say("  relation types: " . count($defs) . ", object relations: $count");
}

// ============================================================================================ isms

function phase_isms(): void
{
    global $TID, $CLIENTS;
    say('=== isms');
    $mk = fn(string $url, array $body) => new_id(api('POST', $url, $body));

    // ---- risk classes, likelihoods (rows) and impacts (columns): 5x5 scale
    $RC = [];
    foreach ([['Niedrig', '#4CAF50', 'Akzeptabel. Überwachung im Rahmen des jährlichen Reviews.'],
              ['Mittel', '#FFC107', 'Behandlung innerhalb von 12 Monaten oder begründete Akzeptanz durch den Risk Owner.'],
              ['Hoch', '#FF9800', 'Behandlung innerhalb von 3 Monaten, Freigabe durch IT-Leitung und ISB.'],
              ['Kritisch', '#F44336', 'Sofortmaßnahmen, Eskalation an die Geschäftsführung, Akzeptanz nicht zulässig.']] as $i => [$n, $c, $d]) {
        $RC[$n] = $mk('/isms/risk_classes/', ['name' => $n, 'color' => $c, 'description' => $d, 'sort' => $i + 1]);
    }
    $LH = [];
    foreach ([['Sehr selten', 'seltener als alle 10 Jahre'], ['Selten', 'alle 5 - 10 Jahre'], ['Möglich', 'alle 1 - 5 Jahre'],
              ['Wahrscheinlich', 'etwa einmal pro Jahr'], ['Häufig', 'mehrmals pro Jahr bis monatlich']] as $i => [$n, $d]) {
        $LH[$n] = $mk('/isms/likelihoods/', ['name' => $n, 'calculation_basis' => (float)($i + 1), 'description' => $d]);
    }
    $IM = [];
    foreach ([['Unbedeutend', 'keine spürbaren Auswirkungen'], ['Gering', 'geringe, schnell behebbare Auswirkungen'], ['Mittel', 'spürbare Beeinträchtigung einzelner Bereiche'],
              ['Hoch', 'erhebliche Beeinträchtigung des Geschäftsbetriebs'], ['Existenzbedrohend', 'Fortbestand des Unternehmens gefährdet']] as $i => [$n, $d]) {
        $IM[$n] = $mk('/isms/impacts/', ['name' => $n, 'calculation_basis' => (float)($i + 1), 'description' => $d]);
    }
    $impactNames = array_keys($IM);
    $IC = [];
    foreach (['Finanzieller Schaden' => ['< 5.000 EUR', '5.000 - 50.000 EUR', '50.000 - 250.000 EUR', '250.000 - 1 Mio. EUR', '> 1 Mio. EUR'],
              'Betriebsunterbrechung' => ['< 1 Stunde', '1 - 4 Stunden', '4 - 24 Stunden', '1 - 5 Tage', '> 5 Tage'],
              'Reputation' => ['nicht wahrnehmbar', 'intern bekannt', 'einzelne Kunden betroffen', 'regionale Presse / viele Kunden', 'überregionale Presse, Kundenverlust'],
              'Recht / Compliance' => ['kein Verstoß', 'interner Richtlinienverstoß', 'Vertragsverletzung', 'meldepflichtige Datenschutzverletzung (Art. 33 DSGVO)', 'Bußgeld, Haftung der Geschäftsführung'],
              'Personenbezogene Daten' => ['keine', 'einzelne Datensätze', 'Daten einer Abteilung', 'Kunden- oder Mitarbeiterstamm', 'besondere Kategorien (Art. 9 DSGVO)']] as $n => $ds) {
        $desc = [];
        foreach ($impactNames as $i => $imp) {
            $desc[] = ['impact_id' => $IM[$imp], 'value' => $ds[$i]];
        }
        $IC[$n] = $mk('/isms/impact_categories/', ['name' => $n, 'sort' => count($IC) + 1, 'impact_descriptions' => $desc]);
    }

    // ---- self-defined risk matrix: classification per cell (rows = likelihood, columns = impact)
    //                         Unbedeutend  Gering    Mittel    Hoch       Existenzbedrohend
    $MATRIX = ['Häufig'         => ['Mittel',  'Hoch',   'Hoch',   'Kritisch', 'Kritisch'],
               'Wahrscheinlich' => ['Niedrig', 'Mittel', 'Hoch',   'Kritisch', 'Kritisch'],
               'Möglich'        => ['Niedrig', 'Mittel', 'Mittel', 'Hoch',     'Kritisch'],
               'Selten'         => ['Niedrig', 'Niedrig', 'Mittel', 'Hoch',    'Kritisch'],
               'Sehr selten'    => ['Niedrig', 'Niedrig', 'Niedrig', 'Mittel', 'Hoch']];
    $m = api('GET', '/isms/risk_matrix/1');
    $m = $m['result'] ?? $m;
    $lhName = array_flip($LH);
    $imIdx = array_flip(array_values($IM));
    foreach ($m['risk_matrix'] as &$cell) {
        $cell['risk_class_id'] = $RC[$MATRIX[$lhName[$cell['likelihood_id']]][$imIdx[$cell['impact_id']]]];
    }
    unset($cell);
    api('PUT', '/isms/risk_matrix/1', ['risk_matrix' => $m['risk_matrix'], 'matrix_unit' => 'EUR']);
    $st = api('GET', '/isms/config/status');
    say('  config status: ' . json_encode($st));

    // ---- protection goals, threats, vulnerabilities
    $pg = array_column(results(api('GET', '/isms/protection_goals/?limit=100')), 'public_id', 'name');
    $C = $pg['Confidentiality'];
    $I = $pg['Integrity'];
    $A = $pg['Availability'];
    $Au = $mk('/isms/protection_goals/', ['name' => 'Authentizität', 'predefined' => false]);
    $bsi = option('THREAT_VULNERABILITY', 'BSI IT-Grundschutz-Kompendium');
    $internal = option('THREAT_VULNERABILITY', 'Interne Schwachstellenanalyse');
    $T = [];
    foreach ([['G 0.1', 'Feuer', 'Brand in Räumlichkeiten mit IT-Infrastruktur'], ['G 0.2', 'Ungünstige klimatische Bedingungen', 'Überhitzung oder Luftfeuchtigkeit außerhalb der Spezifikation'],
              ['G 0.4', 'Überschwemmung', 'Wassereintritt durch Starkregen oder Rohrbruch'], ['G 0.8', 'Ausfall oder Störung der Stromversorgung', ''],
              ['G 0.9', 'Ausfall oder Störung von Kommunikationsnetzen', 'Ausfall der WAN-/Internetanbindung'], ['G 0.16', 'Diebstahl von Geräten, Datenträgern oder Dokumenten', ''],
              ['G 0.18', 'Fehlplanung oder fehlende Anpassung', ''], ['G 0.19', 'Offenlegung schützenswerter Informationen', ''],
              ['G 0.23', 'Unbefugtes Eindringen in IT-Systeme', ''], ['G 0.25', 'Ausfall von Geräten oder Systemen', ''],
              ['G 0.28', 'Software-Schwachstellen oder -Fehler', ''], ['G 0.32', 'Missbrauch von Berechtigungen', ''],
              ['G 0.39', 'Schadprogramme', 'Ransomware, Trojaner, Würmer'], ['G 0.42', 'Social Engineering', 'Phishing, CEO-Fraud'],
              ['G 0.45', 'Datenverlust', '']] as [$id, $n, $d]) {
        $T[$id] = $mk('/isms/threats/', ['name' => $n, 'identifier' => $id, 'source' => $bsi, 'description' => $d ?: null]);
    }
    $V = [];
    foreach ([['V-01', 'Fehlende Netzsegmentierung zwischen Clients und Servern', 'Flache Netzstruktur im Client-VLAN'],
              ['V-02', 'Keine Offline-/Immutable-Kopie der Datensicherung', ''], ['V-03', 'Single Point of Failure Internetanbindung', 'Nur ein Provider, kein Backup-Pfad'],
              ['V-04', 'Nur ein Klimagerät im Serverraum', 'Keine N+1-Redundanz'], ['V-05', 'Keine Mehr-Faktor-Authentisierung für Fachanwendungen', ''],
              ['V-06', 'Verzögertes Patchmanagement in der DMZ', 'Patches > 30 Tage nach Release'], ['V-07', 'Wiederherstellung wird nicht regelmäßig getestet', ''],
              ['V-08', 'Unzureichende Security-Awareness der Mitarbeitenden', ''], ['V-09', 'Cluster-Kapazität ohne N+1-Reserve', 'Ausfall eines Hosts führt zu Überbuchung'],
              ['V-10', 'Brandmeldeanlage ohne Aufschaltung', ''], ['V-11', 'USV-Autonomiezeit < 20 Minuten, kein Notstromaggregat', ''],
              ['V-12', 'Serverraum im Untergeschoss ohne Wassermelder', ''], ['V-13', 'Notebooks ohne Pre-Boot-Authentisierung', ''],
              ['V-14', 'Changes an Firewall-Regeln ohne Vier-Augen-Prinzip', ''], ['V-15', 'Administrative Konten ohne Tiering / PAM', ''],
              ['V-16', 'Keine Data-Loss-Prevention für Cloud-Dienste', ''], ['V-17', 'Bandlaufwerke ohne Wartungsvertrag', '']] as [$id, $n, $d]) {
        $V[$id] = $mk('/isms/vulnerabilities/', ['name' => $n, 'identifier' => $id, 'source' => $internal, 'description' => $d ?: null]);
    }

    // ---- risks
    $cat = [];
    foreach (['IT-Betrieb', 'Informationssicherheit', 'Infrastruktur', 'Lieferanten', 'Datenschutz'] as $n) {
        $cat[$n] = option('RISK', $n);
    }
    $R = [];
    foreach ([['R-01', 'Ransomware-Befall der Dateidienste', 'Informationssicherheit', [$C, $I, $A], ['G 0.39'], ['V-01', 'V-02']],
              ['R-02', 'Ausfall des VMware-Clusters', 'IT-Betrieb', [$A], ['G 0.25'], ['V-09']],
              ['R-03', 'Ausfall der Internetanbindung', 'Infrastruktur', [$A], ['G 0.9'], ['V-03']],
              ['R-04', 'Brand im Serverraum', 'Infrastruktur', [$A, $I], ['G 0.1'], ['V-10']],
              ['R-05', 'Überhitzung des Serverraums', 'Infrastruktur', [$A], ['G 0.2'], ['V-04']],
              ['R-06', 'Unbefugter Zugriff auf ERP-Daten', 'Informationssicherheit', [$C, $I, $Au], ['G 0.23', 'G 0.19'], ['V-05']],
              ['R-07', 'Kompromittierung der Webserver in der DMZ', 'Informationssicherheit', [$C, $I, $A], ['G 0.28'], ['V-06']],
              ['R-08', 'Datenverlust durch fehlerhafte Datensicherung', 'IT-Betrieb', [$I, $A], ['G 0.45'], ['V-07']],
              ['R-09', 'Kompromittierung von Benutzerkonten durch Phishing', 'Informationssicherheit', [$C, $Au], ['G 0.42'], ['V-08']],
              ['R-11', 'Länger andauernder Stromausfall im Rechenzentrum', 'Infrastruktur', [$A], ['G 0.8'], ['V-11']],
              ['R-12', 'Wassereintritt im Serverraum (Untergeschoss)', 'Infrastruktur', [$A, $I], ['G 0.4'], ['V-12']],
              ['R-13', 'Verlust oder Diebstahl mobiler Endgeräte', 'Datenschutz', [$C], ['G 0.16'], ['V-13']],
              ['R-14', 'Fehlkonfiguration der Firewall-Regeln', 'Informationssicherheit', [$C, $A], ['G 0.18'], ['V-14']],
              ['R-15', 'Missbrauch privilegierter Administrationskonten', 'Informationssicherheit', [$C, $I, $Au], ['G 0.32'], ['V-15']],
              ['R-16', 'Abfluss vertraulicher Daten über Cloud-Dienste', 'Datenschutz', [$C], ['G 0.19'], ['V-16']],
              ['R-17', 'Ausfall der Bandsicherung', 'IT-Betrieb', [$A, $I], ['G 0.25'], ['V-17']]] as [$id, $n, $c, $goals, $ths, $vus]) {
        $R[$id] = $mk('/isms/risks/', ['name' => $n, 'identifier' => $id, 'risk_type' => 'THREAT_X_VULNERABILITY', 'protection_goals' => $goals,
            'threats' => array_map(fn($t) => $T[$t], $ths), 'vulnerabilities' => array_map(fn($v) => $V[$v], $vus), 'category_id' => $cat[$c],
            'consequences' => null, 'description' => null]);
    }
    $R['R-10'] = $mk('/isms/risks/', ['name' => 'Insolvenz oder Ausfall des IT-Dienstleisters', 'identifier' => 'R-10', 'risk_type' => 'EVENT',
        'protection_goals' => [$A], 'threats' => [], 'vulnerabilities' => [], 'category_id' => $cat['Lieferanten'],
        'consequences' => 'Kein Support für Netzwerk-Infrastruktur, verlängerte Ausfallzeiten bei Störungen',
        'description' => 'Wesentliche Netzwerk- und Server-Wartung ist an die Hanse IT-Systemhaus GmbH ausgelagert']);

    // ---- control measures (ISO/IEC 27001:2022 Annex A)
    $iso = option('CONTROL_MEASURE', 'ISO/IEC 27001:2022 Anhang A');
    $ist = [];
    foreach (['Open', 'In Progress', 'Implemented'] as $s) {
        $ist[$s] = option('IMPLEMENTATION_STATE', $s);
    }
    $CM = [];
    foreach ([['A.5.15', 5, 'Zugangssteuerung', 'Implemented'], ['A.5.19', 5, 'Informationssicherheit in Lieferantenbeziehungen', 'In Progress'],
              ['A.5.23', 5, 'Informationssicherheit für die Nutzung von Cloud-Diensten', 'In Progress'],
              ['A.5.24', 5, 'Planung und Vorbereitung des Managements von Informationssicherheitsvorfällen', 'In Progress'],
              ['A.5.30', 5, 'IKT-Bereitschaft für Business Continuity', 'Open'], ['A.6.3', 6, 'Sensibilisierung, Ausbildung und Schulung zur Informationssicherheit', 'In Progress'],
              ['A.7.5', 7, 'Schutz vor physischen und umweltbedingten Bedrohungen', 'Implemented'], ['A.7.11', 7, 'Versorgungseinrichtungen', 'In Progress'],
              ['A.7.13', 7, 'Instandhaltung von Geräten und Betriebsmitteln', 'Implemented'], ['A.8.1', 8, 'Endpunktgeräte des Benutzers', 'Implemented'],
              ['A.8.2', 8, 'Privilegierte Zugangsrechte', 'Open'], ['A.8.5', 8, 'Sichere Authentisierung', 'In Progress'],
              ['A.8.7', 8, 'Schutz gegen Schadsoftware', 'Implemented'], ['A.8.8', 8, 'Handhabung von technischen Schwachstellen', 'In Progress'],
              ['A.8.12', 8, 'Verhinderung von Datenlecks', 'Open'], ['A.8.13', 8, 'Sicherung von Information', 'Implemented'],
              ['A.8.14', 8, 'Redundanz von informationsverarbeitenden Einrichtungen', 'Open'], ['A.8.16', 8, 'Überwachung von Aktivitäten', 'Implemented'],
              ['A.8.22', 8, 'Trennung von Netzwerken', 'Open'], ['A.8.24', 8, 'Verwendung von Kryptographie', 'Implemented'],
              ['A.8.32', 8, 'Änderungssteuerung', 'In Progress'], ['A.8.30', 8, 'Ausgegliederte Entwicklung', 'Open']] as [$id, $ch, $title, $state]) {
        $na = $id === 'A.8.30';
        $chapter = [5 => '5 Organisatorische Maßnahmen', 6 => '6 Personenbezogene Maßnahmen', 7 => '7 Physische Maßnahmen', 8 => '8 Technologische Maßnahmen'][$ch];
        $CM[$id] = $mk('/isms/control_measures/', ['title' => $title, 'control_measure_type' => 'CONTROL', 'source' => $iso,
            'implementation_state' => $ist[$state], 'identifier' => $id, 'chapter' => $chapter, 'description' => null,
            'is_applicable' => !$na, 'reason' => $na ? 'Es findet keine ausgelagerte Softwareentwicklung statt' : null]);
    }

    // ---- persons, person groups, object groups
    $P = [];
    foreach ([['p_weber', 'Markus', 'Weber', '+49 30 5550101', 'markus.weber@nordlicht-logistik.de'], ['p_koch', 'Sabine', 'Koch', '+49 30 5550102', 'sabine.koch@nordlicht-logistik.de'],
              ['p_kaya', 'Ali', 'Kaya', '+49 30 5550105', 'ali.kaya@nordlicht-logistik.de'], ['p_schulz', 'Thomas', 'Schulz', '+49 30 5550103', 'thomas.schulz@nordlicht-logistik.de'],
              ['p_neumann', 'Julia', 'Neumann', '+49 30 5550104', 'julia.neumann@nordlicht-logistik.de'], ['p_fischer', 'Claudia', 'Fischer', '+49 30 5550110', 'claudia.fischer@nordlicht-logistik.de'],
              ['p_petersen', 'Hauke', 'Petersen', '+49 40 5550113', 'hauke.petersen@nordlicht-logistik.de'], ['p_lange', 'Robert', 'Lange', '+49 40 3330120', 'r.lange@hanse-it.example'],
              ['p_dsb', 'Eva', 'Brandt', '+49 30 9998877', 'datenschutz@nordlicht-logistik.de']] as [$k, $f, $l, $ph, $em]) {
        $P[$k] = $mk('/persons/', ['display_name' => "$f $l", 'first_name' => $f, 'last_name' => $l, 'phone_number' => $ph, 'email' => $em, 'groups' => []]);
    }
    $G = [];
    foreach ([['g_gf', 'Geschäftsführung', 'gf@nordlicht-logistik.de', ['p_weber']], ['g_it', 'IT-Betrieb', 'it@nordlicht-logistik.de', ['p_koch', 'p_schulz', 'p_neumann']],
              ['g_isms', 'ISMS-Team', 'isms@nordlicht-logistik.de', ['p_kaya', 'p_koch', 'p_dsb']], ['g_hit', 'Hanse IT (Dienstleister)', 'support@hanse-it.example', ['p_lange']]] as [$k, $n, $em, $mem]) {
        $G[$k] = $mk('/person_groups/', ['name' => $n, 'email' => $em, 'group_members' => array_map(fn($x) => $P[$x], $mem)]);
    }
    $crit = option('OBJECT_GROUP', 'Kritische Systeme');
    $notebooks = array_map(fn($c) => oid($c[0]), array_values(array_filter($CLIENTS, fn($c) => $c[4])));
    $OG = [
        'esx' => $mk('/object_groups/', ['name' => 'VMware-Cluster Berlin', 'group_type' => 'STATIC', 'assigned_ids' => [oid('srv_esx1'), oid('srv_esx2'), oid('srv_esx3')], 'categories' => [$crit]]),
        'clients' => $mk('/object_groups/', ['name' => 'Alle Arbeitsplatzrechner', 'group_type' => 'DYNAMIC', 'assigned_ids' => [$TID['client']], 'categories' => []]),
        'notebooks' => $mk('/object_groups/', ['name' => 'Mobile Endgeräte (Notebooks)', 'group_type' => 'STATIC', 'assigned_ids' => $notebooks, 'categories' => []]),
        'net' => $mk('/object_groups/', ['name' => 'Netzwerk-Infrastruktur', 'group_type' => 'STATIC', 'assigned_ids' => array_map('oid',
            ['rt_ber', 'fw_ber1', 'fw_ber2', 'sw_core1', 'sw_core2', 'sw_acc1', 'sw_acc2', 'sw_acc3', 'wlc_ber1', 'rt_hh', 'fw_hh1', 'sw_hh1']), 'categories' => [$crit]]),
        'power' => $mk('/object_groups/', ['name' => 'USV-Anlagen', 'group_type' => 'DYNAMIC', 'assigned_ids' => [$TID['ups']], 'categories' => [$crit]]),
    ];

    // ---- risk assessments: [risk, target type, target, owner, before [likelihood, impacts per category], after, treatment, measures, priority, date, status, audit]
    $icNames = array_keys($IC);
    $calc = function (string $l, array $imps) use ($LH, $IM, $IC, $icNames) {
        $out = [];
        foreach ($icNames as $i => $c) {
            $out[] = ['impact_category_id' => $IC[$c], 'impact_id' => isset($imps[$i]) && $imps[$i] ? $IM[$imps[$i]] : null];
        }
        return ['impacts' => $out, 'likelihood_id' => $LH[$l], 'likelihood_value' => null, 'maximum_impact_id' => null, 'maximum_impact_value' => null];
    };
    $ref = fn(string $k) => str_starts_with($k, 'p_') ? ['PERSON', $P[$k]] : ['PERSON_GROUP', $G[$k]];
    $RA = [
        ['R-01', 'OBJECT', oid('vm_fs01'), 'p_koch', ['Wahrscheinlich', ['Hoch', 'Hoch', 'Mittel', 'Hoch', 'Mittel']], ['Selten', ['Mittel', 'Mittel', 'Gering', 'Mittel', 'Gering']],
         'REDUCE', [['A.8.7', 'Implemented', 3, 'g_it'], ['A.8.13', 'Implemented', 4, 'g_it'], ['A.8.22', 'Open', 3, 'g_hit']], 4, '2026-08-12', 'In Progress', null],
        ['R-01', 'OBJECT', oid('vm_erp01'), 'p_fischer', ['Möglich', ['Existenzbedrohend', 'Hoch', 'Hoch', 'Hoch', 'Mittel']], ['Selten', ['Hoch', 'Mittel', 'Mittel', 'Mittel', 'Gering']],
         'REDUCE', [['A.8.7', 'Implemented', 3, 'g_it'], ['A.8.13', 'Implemented', 4, 'g_it'], ['A.8.22', 'Open', 4, 'g_hit']], 4, '2026-08-12', 'In Progress', null],
        ['R-02', 'OBJECT_GROUP', $OG['esx'], 'p_koch', ['Möglich', ['Mittel', 'Hoch', 'Gering', 'Gering', null]], ['Selten', ['Mittel', 'Mittel', 'Gering', 'Gering', null]],
         'REDUCE', [['A.8.14', 'Open', 3, 'g_it'], ['A.8.16', 'Implemented', 2, 'p_kaya']], 3, '2026-08-12', 'Open', null],
        ['R-03', 'OBJECT', oid('rt_ber'), 'p_koch', ['Möglich', ['Mittel', 'Hoch', 'Mittel', 'Gering', null]], ['Selten', ['Gering', 'Mittel', 'Gering', 'Gering', null]],
         'REDUCE', [['A.8.14', 'Open', 3, 'g_hit']], 3, '2026-08-19', 'Open', null],
        ['R-03', 'OBJECT', oid('rt_hh'), 'p_petersen', ['Wahrscheinlich', ['Mittel', 'Hoch', 'Mittel', 'Gering', null]], ['Möglich', ['Gering', 'Mittel', 'Gering', 'Gering', null]],
         'REDUCE', [['A.8.14', 'Open', 4, 'g_hit']], 4, '2026-08-19', 'Open', null],
        ['R-04', 'OBJECT', oid('r_srv'), 'g_gf', ['Selten', ['Existenzbedrohend', 'Existenzbedrohend', 'Hoch', 'Mittel', null]], ['Sehr selten', ['Hoch', 'Hoch', 'Mittel', 'Mittel', null]],
         'REDUCE', [['A.7.5', 'Implemented', 4, 'p_koch'], ['A.5.30', 'Open', 3, 'g_isms']], 3, '2026-08-19', 'In Progress', null],
        ['R-05', 'OBJECT', oid('r_srv'), 'p_koch', ['Möglich', ['Mittel', 'Hoch', 'Gering', 'Gering', null]], ['Selten', ['Mittel', 'Mittel', 'Gering', 'Gering', null]],
         'REDUCE', [['A.7.11', 'In Progress', 3, 'g_it'], ['A.7.13', 'Implemented', 2, 'g_hit']], 3, '2026-08-19', 'In Progress', null],
        ['R-06', 'OBJECT', oid('app_erp'), 'p_fischer', ['Möglich', ['Hoch', 'Mittel', 'Hoch', 'Hoch', 'Hoch']], ['Selten', ['Hoch', 'Mittel', 'Mittel', 'Mittel', 'Mittel']],
         'REDUCE', [['A.8.5', 'In Progress', 4, 'g_it'], ['A.5.15', 'Implemented', 3, 'p_neumann']], 4, '2026-09-02', 'In Progress', null],
        ['R-07', 'OBJECT', oid('vm_web01'), 'p_kaya', ['Wahrscheinlich', ['Mittel', 'Mittel', 'Hoch', 'Mittel', 'Gering']], ['Möglich', ['Gering', 'Gering', 'Mittel', 'Gering', 'Gering']],
         'REDUCE', [['A.8.8', 'In Progress', 3, 'p_schulz'], ['A.8.16', 'Implemented', 2, 'p_kaya']], 3, '2026-09-02', 'In Progress', null],
        ['R-08', 'OBJECT', oid('app_backup'), 'p_koch', ['Möglich', ['Hoch', 'Hoch', 'Mittel', 'Mittel', 'Mittel']], ['Sehr selten', ['Hoch', 'Mittel', 'Gering', 'Gering', 'Gering']],
         'REDUCE', [['A.8.13', 'Implemented', 3, 'p_schulz']], 2, '2026-09-09', 'Implemented', ['2026-09-30', 'Restore-Test erfolgreich: ber-erp01 in 1:45 h wiederhergestellt (RTO 4 h)']],
        ['R-09', 'OBJECT_GROUP', $OG['clients'], 'p_kaya', ['Häufig', ['Mittel', 'Mittel', 'Mittel', 'Hoch', 'Mittel']], ['Möglich', ['Gering', 'Gering', 'Gering', 'Mittel', 'Gering']],
         'REDUCE', [['A.6.3', 'In Progress', 3, 'g_isms'], ['A.8.5', 'In Progress', 3, 'g_it'], ['A.8.7', 'Implemented', 3, 'g_it']], 3, '2026-09-09', 'In Progress', null],
        ['R-10', 'OBJECT_GROUP', $OG['net'], 'g_gf', ['Selten', ['Mittel', 'Hoch', 'Gering', 'Gering', null]], ['Selten', ['Mittel', 'Mittel', 'Gering', 'Gering', null]],
         'ACCEPT', [['A.5.19', 'In Progress', 2, 'p_koch']], 2, '2026-09-16', 'In Progress', null],
        ['R-11', 'OBJECT_GROUP', $OG['power'], 'p_koch', ['Möglich', ['Mittel', 'Hoch', 'Mittel', 'Gering', null]], ['Selten', ['Gering', 'Mittel', 'Gering', 'Gering', null]],
         'REDUCE', [['A.7.11', 'In Progress', 4, 'g_hit'], ['A.7.13', 'Implemented', 2, 'g_hit']], 4, '2026-09-16', 'In Progress', null],
        ['R-12', 'OBJECT', oid('r_srv'), 'g_gf', ['Selten', ['Hoch', 'Hoch', 'Mittel', 'Gering', null]], ['Selten', ['Gering', 'Mittel', 'Gering', 'Gering', null]],
         'TRANSFER_SHARE', [['A.7.5', 'Implemented', 3, 'p_koch']], 3, '2026-09-16', 'Implemented', null],
        ['R-13', 'OBJECT_GROUP', $OG['notebooks'], 'p_kaya', ['Wahrscheinlich', ['Gering', 'Gering', 'Mittel', 'Hoch', 'Mittel']], ['Wahrscheinlich', ['Gering', 'Gering', 'Gering', 'Gering', 'Gering']],
         'REDUCE', [['A.8.1', 'Implemented', 3, 'g_it'], ['A.8.24', 'Implemented', 4, 'g_it']], 3, '2026-09-23', 'Implemented', ['2026-10-07', 'BitLocker mit TPM+PIN auf allen Notebooks verifiziert']],
        ['R-14', 'OBJECT', oid('fw_ber1'), 'p_kaya', ['Möglich', ['Mittel', 'Hoch', 'Mittel', 'Mittel', 'Gering']], ['Selten', ['Gering', 'Mittel', 'Gering', 'Gering', 'Gering']],
         'REDUCE', [['A.8.32', 'In Progress', 3, 'g_hit'], ['A.8.16', 'Implemented', 2, 'p_kaya']], 3, '2026-09-23', 'In Progress', null],
        ['R-15', 'OBJECT', oid('app_ad'), 'p_koch', ['Möglich', ['Existenzbedrohend', 'Hoch', 'Hoch', 'Hoch', 'Hoch']], ['Selten', ['Hoch', 'Mittel', 'Mittel', 'Mittel', 'Mittel']],
         'REDUCE', [['A.8.2', 'Open', 4, 'g_it'], ['A.8.5', 'In Progress', 4, 'g_it'], ['A.8.16', 'Implemented', 3, 'p_kaya']], 4, '2026-09-30', 'Open', null],
        ['R-16', 'OBJECT', oid('app_m365'), 'p_dsb', ['Möglich', ['Mittel', 'Unbedeutend', 'Hoch', 'Hoch', 'Hoch']], ['Selten', ['Mittel', 'Unbedeutend', 'Mittel', 'Mittel', 'Mittel']],
         'REDUCE', [['A.5.23', 'In Progress', 3, 'g_isms'], ['A.8.12', 'Open', 3, 'g_it']], 3, '2026-09-30', 'Open', null],
        ['R-17', 'OBJECT', oid('tl_ber1'), 'p_schulz', ['Wahrscheinlich', ['Gering', 'Gering', 'Unbedeutend', 'Mittel', null]], ['Selten', ['Gering', 'Gering', 'Unbedeutend', 'Gering', null]],
         'AVOID', [['A.8.13', 'Implemented', 2, 'p_schulz']], 2, '2026-10-07', 'Open', null],
    ];
    foreach ($RA as [$rid, $rt, $target, $owner, $before, $after, $opt, $measures, $prio, $date, $status, $audit]) {
        $own = $ref($owner);
        $resp = $ref($opt === 'ACCEPT' || $opt === 'TRANSFER_SHARE' ? 'g_gf' : 'g_it');
        $text = ['REDUCE' => 'Risikoreduktion durch die zugeordneten Maßnahmen bis zum Zieltermin.',
                 'ACCEPT' => 'Restrisiko durch die Geschäftsführung akzeptiert (Beschluss GF-2026-09). Jährliche Neubewertung.',
                 'TRANSFER_SHARE' => 'Risikotransfer über Elementarschaden- und Betriebsunterbrechungsversicherung (Police 2026-ELM-778).',
                 'AVOID' => 'Risikovermeidung: Ablösung der Bandsicherung durch Immutable Object Storage (S3 Object Lock) bis Q2/2027.'][$opt];
        api('POST', '/isms/risk_assessments/', [
            'risk_id' => $R[$rid], 'object_id_ref_type' => $rt, 'object_id' => $target,
            'risk_calculation_before' => $calc(...$before), 'risk_calculation_after' => $calc(...$after),
            'risk_assessor_id' => $P['p_kaya'], 'risk_owner_id_ref_type' => $own[0], 'risk_owner_id' => $own[1],
            'interviewed_persons' => [$P['p_koch'], $P['p_schulz']], 'risk_assessment_date' => ms($date),
            'additional_info' => 'Bewertung im Rahmen des ISMS-Risikoworkshops 2026', 'risk_treatment_option' => $opt,
            'responsible_persons_id_ref_type' => $resp[0], 'responsible_persons_id' => $resp[1], 'risk_treatment_description' => $text,
            'required_resources' => $opt === 'REDUCE' ? 'interne Personentage IT-Betrieb, ggf. Dienstleister' : null,
            'costs_for_implementation' => ['REDUCE' => 4500.0, 'ACCEPT' => null, 'TRANSFER_SHARE' => 2800.0, 'AVOID' => 18000.0][$opt],
            'costs_for_implementation_currency' => 'EUR', 'planned_implementation_date' => ms('2026-12-31'),
            'finished_implementation_date' => $status === 'Implemented' ? ms('2026-09-30') : null,
            'implementation_status' => $ist[$status], 'priority' => $prio,
            'audit_done_date' => $audit ? ms($audit[0]) : null, 'audit_result' => $audit[1] ?? null,
            'auditor_id_ref_type' => 'PERSON', 'auditor_id' => $P['p_dsb'],
            'control_measure_assignments' => array_map(fn($x) => [
                'control_measure_id' => $CM[$x[0]], 'planned_implementation_date' => ms('2026-12-31'),
                'implementation_status' => $ist[$x[1]], 'finished_implementation_date' => $x[1] === 'Implemented' ? ms('2026-07-01') : null,
                'priority' => $x[2], 'responsible_for_implementation_id_ref_type' => $ref($x[3])[0],
                'responsible_for_implementation_id' => $ref($x[3])[1]], $measures),
        ]);
    }
    say('  risks: ' . count($R) . ', controls: ' . count($CM) . ', assessments: ' . count($RA));
}

// ============================================================================================ main

$CLIENTS = [];
login();
load_types();
$existing = api('GET', '/objects/?limit=1')['total'] ?? 0;
if ($existing > 0 && !$WIPE) {
    fail("The tenant already contains $existing objects. Re-run with --wipe to delete EVERYTHING and rebuild the demo.");
}
if ($WIPE) {
    wipe();
}
$t0 = microtime(true);
phase_types();
phase_ipam();
phase_base();
phase_hw();
phase_racks();
phase_cabling();
phase_relations();
phase_isms();
say(sprintf("\nDone in %.0f s: %d objects created.", microtime(true) - $t0, count($O)));
