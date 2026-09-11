#!/usr/bin/env node
/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

/**
 * Guards the button system: no template may gain a Bootstrap button class.
 *
 * Buttons are `<app-button>` with a variant and a tone
 * (app/src/app/core/components/base/button). The templates that still carry `btn btn-*` are
 * the areas the migration has not reached yet, so this runs as a ratchet rather than a wall:
 * legacy-buttons-baseline.json records what each file is still allowed, the check fails when a
 * file goes over its allowance or a file not in the baseline uses one at all, and every
 * migrated area lowers the numbers until the baseline is empty and the guard is absolute.
 *
 *   node tools/check-legacy-buttons.js            verify (exit 1 on a regression)
 *   node tools/check-legacy-buttons.js --update    re-record the baseline after a migration
 */

const fs = require('fs');
const path = require('path');

const TEMPLATE_ROOT = path.join(__dirname, '..', 'src');
const BASELINE_FILE = path.join(__dirname, 'legacy-buttons-baseline.json');

/**
 * `btn-close` is deliberately absent: it is Bootstrap's dismiss control rather than a button
 * style, and the shared modal shell owns the few that exist.
 */
const LEGACY_CLASS = /^(btn|btn-group|btn-group-sm|btn-group-lg|btn-block|btn-sm|btn-lg|btn-(?:outline-)?(?:primary|secondary|success|danger|warning|info|light|dark|link|cmdb-primary))$/;

function collectTemplates(dir, found = []) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        // AppleDouble sidecars on the shared mount are not source files.
        if (entry.name.startsWith('._')) {
            continue;
        }

        const full = path.join(dir, entry.name);

        if (entry.isDirectory()) {
            collectTemplates(full, found);
        } else if (entry.isFile() && entry.name.endsWith('.html')) {
            found.push(full);
        }
    }

    return found;
}

/**
 * Collects the class names a template applies, from static attributes as well as from the
 * `[class.x]`, `[class]` and `[ngClass]` bindings that can smuggle the same names in.
 */
function findLegacyClasses(source) {
    const hits = [];

    const record = (name, index) => {
        if (!LEGACY_CLASS.test(name)) {
            return;
        }

        hits.push({ name, line: source.slice(0, index).split('\n').length });
    };

    for (const match of source.matchAll(/\bclass\s*=\s*"([^"]*)"/g)) {
        for (const name of match[1].trim().split(/\s+/)) {
            record(name, match.index);
        }
    }

    for (const match of source.matchAll(/\[class\.([A-Za-z0-9_-]+)\]/g)) {
        record(match[1], match.index);
    }

    for (const match of source.matchAll(/\[(?:ngClass|class)\]\s*=\s*"([^"]*)"/g)) {
        for (const literal of match[1].matchAll(/'([^']*)'/g)) {
            for (const name of literal[1].trim().split(/\s+/)) {
                record(name, match.index);
            }
        }
    }

    return hits;
}

const current = new Map();
const removedInput = [];

for (const file of collectTemplates(TEMPLATE_ROOT)) {
    const source = fs.readFileSync(file, 'utf8');
    const name = path.relative(TEMPLATE_ROOT, file).split(path.sep).join('/');
    const hits = findLegacyClasses(source);

    if (hits.length) {
        current.set(name, hits);
    }

    for (const match of source.matchAll(/\[?bootstrapClass\]?\s*=/g)) {
        removedInput.push({ file: name, line: source.slice(0, match.index).split('\n').length });
    }
}

/*
 * `bootstrapClass` was deleted along with its adapter, so an occurrence is broken markup rather
 * than debt: the bound form fails template compilation and the static form is silently dropped.
 * Never ratcheted — a branch that lands one has to fix it.
 */
if (removedInput.length) {
    console.error('`bootstrapClass` was removed from app-button; these bindings do nothing.');
    console.error('Translate each one into variant/tone/size — see the migration map in');
    console.error('app/src/app/core/components/base/button.\n');

    for (const { file, line } of removedInput) {
        console.error(`    ${ file }:${ line }`);
    }

    process.exit(1);
}

if (process.argv.includes('--update')) {
    const baseline = {};

    for (const [file, hits] of [...current.entries()].sort()) {
        baseline[file] = hits.length;
    }

    const total = Object.values(baseline).reduce((sum, count) => sum + count, 0);

    fs.writeFileSync(BASELINE_FILE, `${ JSON.stringify(baseline, null, 4) }\n`);
    console.log(`Recorded ${ total } legacy button classes in ${ Object.keys(baseline).length } templates.`);
    process.exit(0);
}

if (!fs.existsSync(BASELINE_FILE)) {
    console.error(`No baseline at ${ BASELINE_FILE }. Create one with --update.`);
    process.exit(1);
}

const baseline = JSON.parse(fs.readFileSync(BASELINE_FILE, 'utf8'));
const regressions = [];
const improvements = [];

for (const [file, hits] of current) {
    const allowed = baseline[file] ?? 0;

    if (hits.length > allowed) {
        regressions.push({ file, allowed, hits });
    }
}

for (const [file, allowed] of Object.entries(baseline)) {
    const actual = current.get(file)?.length ?? 0;

    if (actual < allowed) {
        improvements.push({ file, allowed, actual });
    }
}

if (regressions.length) {
    console.error('Bootstrap button classes are not allowed in new markup.');
    console.error('Use <app-button variant="…" tone="…">; see app/src/app/core/components/base/button.\n');

    for (const { file, allowed, hits } of regressions) {
        console.error(`${ file }  (allowed ${ allowed }, found ${ hits.length })`);

        for (const { name, line } of hits) {
            console.error(`    ${ file }:${ line }  ${ name }`);
        }
    }

    process.exit(1);
}

const total = [...current.values()].reduce((sum, hits) => sum + hits.length, 0);

if (improvements.length) {
    console.log(`${ improvements.length } template(s) improved. Re-record with --update:\n`);

    for (const { file, allowed, actual } of improvements) {
        console.log(`    ${ file }  ${ allowed } -> ${ actual }`);
    }

    console.log('');
}

console.log(`No new Bootstrap button classes. ${ total } remaining in ${ current.size } templates.`);
