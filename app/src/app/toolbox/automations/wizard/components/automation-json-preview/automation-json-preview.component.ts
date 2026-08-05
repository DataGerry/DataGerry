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
import { ChangeDetectionStrategy, Component, inject, Input } from '@angular/core';

import { CopyService } from 'src/app/core/services/copy.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The concept's "technical view": the compiled OpenCelium JSON, read-only, for administrators.
 *
 * Collapsed by default - the whole point of the wizard is that nobody has to look at this. It stays
 * available for diagnosing what the compiler produced.
 */
@Component({
    selector: 'app-automation-json-preview',
    templateUrl: './automation-json-preview.component.html',
    styleUrls: ['./automation-json-preview.component.scss'],
    standalone: false,
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class AutomationJsonPreviewComponent {

    @Input() public json = '';
    @Input() public warnings: string[] = [];

    private readonly copyService = inject(CopyService);

    public expanded = false;

    /* --------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    public toggle(): void {
        this.expanded = !this.expanded;
    }


    public onCopy(): void {
        if (this.json) {
            this.copyService.copyWithFeedback(this.json, 'OpenCelium definition');
        }
    }


    public get lineCount(): number {
        return this.json ? this.json.split('\n').length : 0;
    }
}
