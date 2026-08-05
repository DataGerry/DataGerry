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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

/**
 * Bundles verify.ts for Node and runs it.
 *
 * The wizard's compiler and target catalog are plain classes with constructor injection, so they need
 * no Angular runtime - @angular/core is aliased to a stub that supplies the decorators as no-ops.
 * esbuild ships with @angular/build, so this adds no dependency.
 */
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const esbuild = join(here, '..', '..', 'node_modules', 'esbuild', 'bin', 'esbuild');
const workDir = mkdtempSync(join(tmpdir(), 'dg-verify-compiler-'));
const bundle = join(workDir, 'verify.cjs');

try {
    const build = spawnSync(esbuild, [
        join(here, 'verify.ts'),
        '--bundle',
        '--platform=node',
        '--format=cjs',
        `--alias:@angular/core=${join(here, 'stub-angular-core.js')}`,
        `--outfile=${bundle}`,
        '--log-level=error'
    ], { stdio: 'inherit' });

    if (build.status !== 0) {
        process.exit(build.status ?? 1);
    }

    // The bundle executes from a temp directory, so it cannot derive the repository root itself.
    const run = spawnSync(process.execPath, [bundle, ...process.argv.slice(2)], {
        stdio: 'inherit',
        env: { ...process.env, DG_REPO_ROOT: join(here, '..', '..', '..') }
    });
    process.exit(run.status ?? 1);
} finally {
    rmSync(workDir, { recursive: true, force: true });
}
