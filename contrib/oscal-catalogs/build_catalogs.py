#!/usr/bin/env python3
# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Builds the OSCAL catalogs DataGerry ships that have no upstream OSCAL source

  - ``eu-nis2.json`` - NIS2 (Directive (EU) 2022/2555: Art. 20, 21, 23) and the annex of Implementing
    Regulation (EU) 2024/2690 (technical and methodological requirements), German, from the official
    texts of the EU Publications Office. EU legal texts may be reused with acknowledgement of the source
    (Commission Decision 2011/833/EU)
  - ``iso-27001-2022-annex-a.json`` - the 93 controls of ISO/IEC 27001:2022 Annex A as numbers and titles
    only. The control text is ISO copyright and is NOT included; users add it from their licensed copy

Usage (writes into app/src/assets/oscal/catalogs and updates manifest.json):

    python3 contrib/oscal-catalogs/build_catalogs.py [--nis2-dir DIR]

Without --nis2-dir the two NIS2 texts are downloaded as XHTML from
``http://publications.europa.eu/resource/celex/<CELEX>`` (German); with it, DIR must hold
``32022L2555.xhtml`` and ``32024R2690.xhtml``. The output is deterministic: UUIDs are derived (uuid5) from
the control ids, so a rebuild of unchanged texts yields identical files.
"""
import argparse
import html
import json
import re
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / 'app' / 'src' / 'assets' / 'oscal' / 'catalogs'
MANIFEST = CATALOG_DIR / 'manifest.json'

OSCAL_VERSION = '1.1.3'
UUID_NAMESPACE = uuid.UUID('6f0d3c3e-6d1a-4f3e-9a55-5d8e3b1b7a10')

CELEX_NIS2 = '32022L2555'
CELEX_IR = '32024R2690'
CELLAR_URL = 'http://publications.europa.eu/resource/celex/{celex}'

# --------------------------------------------------------------------------------------------------------------------- #
#                                                        HELPERS                                                        #
# --------------------------------------------------------------------------------------------------------------------- #

def stable_uuid(name: str) -> str:
    """Deterministic UUID for an OSCAL object"""
    return str(uuid.uuid5(UUID_NAMESPACE, name))


def text_lines(xhtml: str) -> list[str]:
    """The non-empty text lines of an EU Publications Office XHTML document"""
    text = html.unescape(re.sub(r'<[^>]+>', '\n', xhtml)).replace('\xa0', ' ')
    return [' '.join(line.split()) for line in text.split('\n') if line.strip()]


def oscal_token(value: str) -> str:
    """An OSCAL token (id) from a label"""
    return re.sub(r'[^A-Za-z0-9._-]', '-', value)


def prop(name: str, value: str) -> dict[str, str]:
    return {'name': name, 'value': value}


def statement(control_id: str, prose: str | None, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The statement part of a control: prose plus labelled items"""
    part: dict[str, Any] = {'id': f'{control_id}_smt', 'name': 'statement'}
    if prose:
        part['prose'] = prose
    if items:
        part['parts'] = items
    return part


def item(control_id: str, index: int, label: str | None, prose: str) -> dict[str, Any]:
    entry: dict[str, Any] = {'id': f'{control_id}_smt.{index}', 'name': 'item', 'prose': prose}
    if label:
        entry['props'] = [prop('label', label)]
    return entry


def control(control_id: str, label: str, title: str, prose: str | None,
            items: list[dict[str, Any]] | None = None, extra_props: list[dict[str, str]] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        'id': control_id,
        'title': title,
        'props': [prop('label', label)] + (extra_props or []),
    }
    if prose or items:
        entry['parts'] = [statement(control_id, prose, items)]
    return entry


def catalog_document(name: str, title: str, version: str, last_modified: str, remarks: str,
                     groups: list[dict[str, Any]], links: list[dict[str, str]], party: str) -> dict[str, Any]:
    party_uuid = stable_uuid(f'{name}:party')
    return {
        'catalog': {
            'uuid': stable_uuid(f'{name}:catalog'),
            'metadata': {
                'title': title,
                'last-modified': last_modified,
                'version': version,
                'oscal-version': OSCAL_VERSION,
                'roles': [{'id': 'creator', 'title': 'Creator'}],
                'parties': [{'uuid': party_uuid, 'type': 'organization', 'name': party}],
                'responsible-parties': [{'role-id': 'creator', 'party-uuids': [party_uuid]}],
                'links': links,
                'remarks': remarks,
            },
            'groups': groups,
        }
    }

# --------------------------------------------------------------------------------------------------------------------- #
#                                                          NIS2                                                         #
# --------------------------------------------------------------------------------------------------------------------- #

PARAGRAPH = re.compile(r'^\((\d+)\)\s+(.*)$')
LETTER = re.compile(r'^([a-z])\)$')
NUMBER = re.compile(r'^(\d+(?:\.\d+)*)\.$')


def article_lines(lines: list[str], number: int, title: str) -> list[str]:
    """The body lines of an article of the directive (heading 'Artikel N' followed by its title)"""
    for i in range(len(lines) - 1):
        if lines[i] == f'Artikel {number}' and lines[i + 1] == title:
            body = []
            for line in lines[i + 2:]:
                if re.fullmatch(r'Artikel \d+', line):
                    break
                body.append(line)
            return body
    raise ValueError(f'Artikel {number} ({title}) not found')


def paragraphs(body: list[str]) -> list[dict[str, Any]]:
    """Paragraphs '(n) text' of an article, each with its lettered items and trailing sub-paragraphs"""
    result: list[dict[str, Any]] = []
    pending_letter: str | None = None

    for line in body:
        match = PARAGRAPH.match(line)
        if match:
            result.append({'number': match.group(1), 'prose': match.group(2), 'items': []})
            pending_letter = None
            continue
        if not result:
            continue
        letter = LETTER.match(line)
        if letter:
            pending_letter = letter.group(1)
            continue
        current = result[-1]
        if pending_letter:
            current['items'].append((f'{pending_letter})', line))
            pending_letter = None
        elif current['items']:
            current['items'].append((None, line))
        else:
            current['prose'] += '\n' + line
    return result


def nis2_directive_groups(lines: list[str]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []

    def paragraph_controls(article: int, paras: list[dict[str, Any]], title: str, keep: set[str]) -> list[dict[str, Any]]:
        controls = []
        for para in paras:
            if para['number'] not in keep:
                continue
            control_id = f'nis2-{article}.{para["number"]}'
            label = f'NIS2-{article}.{para["number"]}'
            items = [item(control_id, i + 1, lbl, text) for i, (lbl, text) in enumerate(para['items'])]
            controls.append(control(control_id, label, f'Art. {article} Abs. {para["number"]} - {title}',
                                    para['prose'], items))
        return controls

    # Art. 20 Governance - both paragraphs address the entities
    art20 = paragraphs(article_lines(lines, 20, 'Governance'))
    groups.append({'id': 'nis2-art-20', 'title': 'Art. 20 Governance', 'props': [prop('label', 'Art. 20')],
                   'controls': paragraph_controls(20, art20, 'Governance', {'1', '2'})})

    # Art. 21 - paragraph 2 split into its ten measures a) to j); paragraphs 1, 3 and 4 as they are
    art21_title = 'Risikomanagementmaßnahmen im Bereich der Cybersicherheit'
    art21 = paragraphs(article_lines(lines, 21, art21_title))
    controls = paragraph_controls(21, [p for p in art21 if p['number'] == '1'], art21_title, {'1'})
    para2 = next(p for p in art21 if p['number'] == '2')
    for label, text in para2['items']:
        if not label:
            continue
        letter = label.rstrip(')')
        control_id = f'nis2-21.2.{letter}'
        measure = text.rstrip(';.')
        controls.append(control(
            control_id, f'NIS2-21.2.{letter}', measure,
            f'{para2["prose"]}\n{label} {text}',
            extra_props=[prop('nis2-measure', letter)],
        ))
    controls += paragraph_controls(21, [p for p in art21 if p['number'] in ('3', '4')], art21_title, {'3', '4'})
    groups.append({'id': 'nis2-art-21', 'title': f'Art. 21 {art21_title}', 'props': [prop('label', 'Art. 21')],
                   'controls': controls})

    # Art. 23 - paragraphs 1 to 4 are the reporting obligations of the entities; 5 to 11 address authorities
    art23 = paragraphs(article_lines(lines, 23, 'Berichtspflichten'))
    groups.append({'id': 'nis2-art-23', 'title': 'Art. 23 Berichtspflichten', 'props': [prop('label', 'Art. 23')],
                   'controls': paragraph_controls(23, art23, 'Berichtspflichten', {'1', '2', '3', '4'})})

    return groups


def implementing_regulation_groups(lines: list[str]) -> list[dict[str, Any]]:
    """The annex of Implementing Regulation (EU) 2024/2690: chapters > sections > numbered requirements"""
    start = lines.index('ANHANG')
    annex = lines[start + 2:]  # skip 'ANHANG' and its title line

    chapters: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None
    current_control: dict[str, Any] | None = None
    pending_letter: str | None = None
    expect_title_for: tuple[str, str] | None = None

    for line in annex:
        if expect_title_for:
            kind, number = expect_title_for
            expect_title_for = None
            if kind == 'chapter':
                chapters.append({'number': number, 'title': line, 'sections': []})
            else:
                current_section = {'number': number, 'title': line, 'controls': []}
                chapters[-1]['sections'].append(current_section)
            current_control = None
            continue

        number = NUMBER.match(line)
        if number:
            depth = number.group(1).count('.')
            if depth == 0:
                expect_title_for = ('chapter', number.group(1))
            elif depth == 1:
                expect_title_for = ('section', number.group(1))
            else:
                current_control = {'number': number.group(1), 'prose': [], 'items': []}
                current_section['controls'].append(current_control)
            pending_letter = None
            continue

        if current_control is None:
            continue
        letter = LETTER.match(line)
        if letter:
            pending_letter = letter.group(1)
            continue
        if pending_letter:
            current_control['items'].append((f'{pending_letter})', line))
            pending_letter = None
        elif current_control['items']:
            current_control['items'].append((None, line))
        else:
            current_control['prose'].append(line)

    groups = []
    for chapter in chapters:
        # "Kryptografie (Artikel 21 Absatz 2 Buchstabe h der Richtlinie (EU) 2022/2555)" -> letters for a prop
        letters = re.findall(r'Buchstaben? ([a-j](?:(?:, | und )[a-j])*)', chapter['title'])
        measure_props = [prop('nis2-measure', l) for l in re.findall(r'[a-j]', letters[0])] if letters else []
        short_title = re.sub(r'\s*\(Artikel 21 .*\)$', '', chapter['title'])
        sections = []
        for section in chapter['sections']:
            controls = []
            for req in section['controls']:
                control_id = f'dvo-{req["number"]}'
                items = [item(control_id, i + 1, lbl, text) for i, (lbl, text) in enumerate(req['items'])]
                controls.append(control(control_id, f'DVO-{req["number"]}', section['title'],
                                        '\n'.join(req['prose']), items, extra_props=measure_props))
            sections.append({'id': f'dvo-{section["number"]}', 'title': section['title'],
                             'props': [prop('label', f'DVO-{section["number"]}')], 'controls': controls})
        groups.append({'id': f'dvo-{chapter["number"]}', 'title': f'{chapter["number"]}. {short_title}',
                       'props': [prop('label', f'DVO-{chapter["number"]}')] + measure_props,
                       'parts': [{'id': f'dvo-{chapter["number"]}_ovw', 'name': 'overview', 'prose': chapter['title']}],
                       'groups': sections})
    return groups


def build_nis2(nis2_dir: Path | None) -> dict[str, Any]:
    def load(celex: str) -> str:
        if nis2_dir:
            return (nis2_dir / f'{celex}.xhtml').read_text(encoding='utf-8')
        request = urllib.request.Request(CELLAR_URL.format(celex=celex), headers={
            'Accept': 'application/xhtml+xml', 'Accept-Language': 'deu'})
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read().decode('utf-8')

    directive = text_lines(load(CELEX_NIS2))
    regulation = text_lines(load(CELEX_IR))

    groups = [
        {'id': 'nis2', 'title': 'NIS2-Richtlinie (EU) 2022/2555', 'props': [prop('label', 'NIS2')],
         'groups': nis2_directive_groups(directive)},
        {'id': 'dvo', 'title': 'DVO (EU) 2024/2690 - Anhang',
         'props': [prop('label', 'DVO')],
         'parts': [{'id': 'dvo_ovw', 'name': 'overview', 'prose': (
             'Die Durchführungsverordnung gilt unmittelbar für DNS-Diensteanbieter, TLD-Namenregister, Anbieter von '
             'Cloud-Computing-Diensten, Rechenzentrumsdiensten, Content-Delivery-Netzen, verwalteten (Sicherheits-)'
             'Diensten, Online-Marktplätzen, Suchmaschinen, sozialen Netzwerken und Vertrauensdiensten. Für andere '
             'Einrichtungen dient sie als Referenz für die Umsetzung von Art. 21 Abs. 2 NIS2.')}],
         'groups': implementing_regulation_groups(regulation)},
    ]

    return catalog_document(
        'eu-nis2',
        'NIS2 - Richtlinie (EU) 2022/2555 und Durchführungsverordnung (EU) 2024/2690',
        '2022/2555 + 2024/2690', '2024-10-18T00:00:00Z',
        'Pflichten der Einrichtungen aus der NIS2-Richtlinie (Art. 20 Governance, Art. 21 Risikomanagementmaßnahmen, '
        'Art. 23 Berichtspflichten) und die technischen und methodischen Anforderungen aus dem Anhang der '
        'Durchführungsverordnung (EU) 2024/2690. Quelle: Amtsblatt der Europäischen Union, © Europäische Union, '
        'https://eur-lex.europa.eu/ - Weiterverwendung gemäß Beschluss 2011/833/EU. Nur die im Amtsblatt '
        'veröffentlichten Fassungen sind verbindlich.',
        groups,
        [{'href': 'https://eur-lex.europa.eu/eli/dir/2022/2555/oj', 'rel': 'reference', 'text': 'Richtlinie (EU) 2022/2555'},
         {'href': 'https://eur-lex.europa.eu/eli/reg_impl/2024/2690/oj', 'rel': 'reference',
          'text': 'Durchführungsverordnung (EU) 2024/2690'}],
        'Europäische Union (Amtsblatt der Europäischen Union)',
    )

# --------------------------------------------------------------------------------------------------------------------- #
#                                                 ISO/IEC 27001:2022 ANNEX A                                            #
# --------------------------------------------------------------------------------------------------------------------- #

ISO_THEMES: list[tuple[str, str, list[str]]] = [
    ('5', 'Organizational controls', [
        'Policies for information security', 'Information security roles and responsibilities',
        'Segregation of duties', 'Management responsibilities', 'Contact with authorities',
        'Contact with special interest groups', 'Threat intelligence', 'Information security in project management',
        'Inventory of information and other associated assets',
        'Acceptable use of information and other associated assets', 'Return of assets',
        'Classification of information', 'Labelling of information', 'Information transfer', 'Access control',
        'Identity management', 'Authentication information', 'Access rights',
        'Information security in supplier relationships', 'Addressing information security within supplier agreements',
        'Managing information security in the ICT supply chain',
        'Monitoring, review and change management of supplier services',
        'Information security for use of cloud services',
        'Information security incident management planning and preparation',
        'Assessment and decision on information security events', 'Response to information security incidents',
        'Learning from information security incidents', 'Collection of evidence',
        'Information security during disruption', 'ICT readiness for business continuity',
        'Legal, statutory, regulatory and contractual requirements', 'Intellectual property rights',
        'Protection of records', 'Privacy and protection of PII', 'Independent review of information security',
        'Compliance with policies, rules and standards for information security', 'Documented operating procedures',
    ]),
    ('6', 'People controls', [
        'Screening', 'Terms and conditions of employment', 'Information security awareness, education and training',
        'Disciplinary process', 'Responsibilities after termination or change of employment',
        'Confidentiality or non-disclosure agreements', 'Remote working', 'Information security event reporting',
    ]),
    ('7', 'Physical controls', [
        'Physical security perimeters', 'Physical entry', 'Securing offices, rooms and facilities',
        'Physical security monitoring', 'Protecting against physical and environmental threats',
        'Working in secure areas', 'Clear desk and clear screen', 'Equipment siting and protection',
        'Security of assets off-premises', 'Storage media', 'Supporting utilities', 'Cabling security',
        'Equipment maintenance', 'Secure disposal or re-use of equipment',
    ]),
    ('8', 'Technological controls', [
        'User end point devices', 'Privileged access rights', 'Information access restriction',
        'Access to source code', 'Secure authentication', 'Capacity management', 'Protection against malware',
        'Management of technical vulnerabilities', 'Configuration management', 'Information deletion',
        'Data masking', 'Data leakage prevention', 'Information backup',
        'Redundancy of information processing facilities', 'Logging', 'Monitoring activities',
        'Clock synchronization', 'Use of privileged utility programs', 'Installation of software on operational systems',
        'Networks security', 'Security of network services', 'Segregation of networks', 'Web filtering',
        'Use of cryptography', 'Secure development life cycle', 'Application security requirements',
        'Secure system architecture and engineering principles', 'Secure coding',
        'Security testing in development and acceptance', 'Outsourced development',
        'Separation of development, test and production environments', 'Change management', 'Test information',
        'Protection of information systems during audit testing',
    ]),
]

ISO_TEXT_NOTE = ('Control text not included: ISO/IEC 27001:2022 is protected by copyright of ISO. '
                 'Add the control text from your licensed copy of the standard.')


def build_iso27001() -> dict[str, Any]:
    groups = []
    for theme, title, controls in ISO_THEMES:
        groups.append({
            'id': f'iso27001-a.{theme}', 'title': f'A.{theme} {title}', 'props': [prop('label', f'A.{theme}')],
            'controls': [{
                'id': f'iso27001-a.{theme}.{index}',
                'title': control_title,
                'props': [prop('label', f'A.{theme}.{index}')],
                'parts': [{'id': f'iso27001-a.{theme}.{index}_gdn', 'name': 'guidance', 'prose': ISO_TEXT_NOTE}],
            } for index, control_title in enumerate(controls, start=1)],
        })

    assert sum(len(c) for _, _, c in ISO_THEMES) == 93, 'ISO/IEC 27001:2022 Annex A has 93 controls'

    return catalog_document(
        'iso-27001-2022-annex-a',
        'ISO/IEC 27001:2022 Annex A - Information security controls (titles)',
        '2022', '2022-10-25T00:00:00Z',
        'The 93 controls of ISO/IEC 27001:2022 Annex A (identical to ISO/IEC 27002:2022), grouped by the four themes. '
        'Only control numbers and titles are listed; the control text and guidance are protected by copyright of ISO '
        'and are not part of this catalog. ISO/IEC 27001 is available from ISO (https://www.iso.org/standard/27001) '
        'and, in Germany, as DIN EN ISO/IEC 27001 from DIN Media.',
        groups,
        [{'href': 'https://www.iso.org/standard/27001', 'rel': 'reference', 'text': 'ISO/IEC 27001:2022'}],
        'International Organization for Standardization (ISO) / IEC',
    )

# --------------------------------------------------------------------------------------------------------------------- #
#                                                        MANIFEST                                                       #
# --------------------------------------------------------------------------------------------------------------------- #

def count(catalog: dict[str, Any]) -> tuple[int, int]:
    groups = controls = 0

    def walk_controls(items: list[dict[str, Any]]) -> None:
        nonlocal controls
        for entry in items or []:
            controls += 1
            walk_controls(entry.get('controls'))

    def walk_groups(items: list[dict[str, Any]]) -> None:
        nonlocal groups
        for entry in items or []:
            groups += 1
            walk_controls(entry.get('controls'))
            walk_groups(entry.get('groups'))

    walk_groups(catalog['catalog'].get('groups'))
    walk_controls(catalog['catalog'].get('controls'))
    return groups, controls


def write_catalog(entry: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    path = CATALOG_DIR / f'{entry["id"]}.json'
    data = json.dumps(document, ensure_ascii=False, separators=(',', ':'))
    path.write_text(data, encoding='utf-8')
    groups, controls = count(document)
    metadata = document['catalog']['metadata']
    return {
        **entry,
        'version': metadata['version'],
        'lastModified': metadata['last-modified'],
        'groups': groups,
        'controls': controls,
        'file': f'assets/oscal/catalogs/{path.name}',
        'size': path.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    parser.add_argument('--nis2-dir', type=Path, help='directory holding 32022L2555.xhtml and 32024R2690.xhtml')
    args = parser.parse_args()

    entries = [
        write_catalog({
            'id': 'eu-nis2',
            'title': 'NIS2 (Richtlinie (EU) 2022/2555 und DVO (EU) 2024/2690)',
            'publisher': 'EU',
            'language': 'de',
            'license': 'EU legal text (reuse permitted)',
            'licenseFile': 'assets/oscal/licenses/eu-legal-texts-reuse.txt',
            'source': 'https://eur-lex.europa.eu/eli/dir/2022/2555/oj',
        }, build_nis2(args.nis2_dir)),
        write_catalog({
            'id': 'iso-27001-2022-annex-a',
            'title': 'ISO/IEC 27001:2022 Anhang A (Control-Titel)',
            'publisher': 'ISO/IEC',
            'language': 'en',
            'license': 'Titles only (text © ISO)',
            'licenseFile': 'assets/oscal/licenses/iso-27001-titles-only.txt',
            'source': 'https://www.iso.org/standard/27001',
        }, build_iso27001()),
    ]

    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    ids = {entry['id'] for entry in entries}
    manifest['catalogs'] = [c for c in manifest['catalogs'] if c['id'] not in ids] + entries
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    for entry in entries:
        print(f'{entry["id"]}: {entry["groups"]} groups, {entry["controls"]} controls, {entry["size"]} bytes')


if __name__ == '__main__':
    main()
