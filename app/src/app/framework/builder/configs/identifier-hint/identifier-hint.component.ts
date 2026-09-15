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
import { Component, input } from '@angular/core';
import { AbstractControl } from '@angular/forms';

/**
 * Identifier helper row for the type builder field/section editors.
 *
 * Shows the "use a unique identifier" hint on the left and, when the bound control fails the
 * reserved-prefix rule (see reservedIdentifierPrefixValidator), a right-aligned error on the same line.
 *
 *   <cmdb-identifier-hint [control]="nameControl"></cmdb-identifier-hint>
 *
 * Default change detection is intentional: the control's errors/dirty/touched state mutates without
 * changing the control reference, so an OnPush strategy would leave the message stale.
 */
@Component({
    selector: 'cmdb-identifier-hint',
    standalone: true,
    template: `
        <div class="d-flex justify-content-between align-items-center">
            <small class="form-text text-muted text-start">{{ hint() }}</small>
            @if (control()?.errors?.['reservedPrefix'] && (control()?.dirty || control()?.touched)) {
            <small class="form-text text-danger text-end ms-2 mb-0">
                Identifier cannot start with "dg-" or "dg_" (reserved prefix)
            </small>
            }
        </div>
    `
})
export class IdentifierHintComponent {

    public readonly control = input<AbstractControl | null>(null);
    public readonly hint = input<string>('Use a unique field identifier');
}
