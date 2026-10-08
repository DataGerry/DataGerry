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
import { Component, inject, Input } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
/* ------------------------------------------------------------------------------------------------------------------ */

/** What the user chose. Closing the dialog any other way means: do not run. */
export interface SaveBeforeRunChoice {
    action: 'save' | 'run-saved';

    /** Only meaningful with 'save': save before every run from now on, without asking. */
    remember: boolean;
}


/**
 * Asked before a run when the editor holds changes that are not saved.
 *
 * A run executes the stored automation, so starting one over unsaved edits tests the previous
 * version - which reads as a verdict on the edits in front of the user. The dialog makes that a
 * choice instead of a surprise. When the edits cannot be saved yet, saving is not offered.
 */
@Component({
    selector: 'app-save-before-run-modal',
    templateUrl: './save-before-run-modal.component.html',
    standalone: false
})
export class SaveBeforeRunModalComponent {

    /** False while the edits do not validate: they cannot be saved, only set aside for this run. */
    @Input() public canSave = true;

    public remember = false;

    public readonly activeModal = inject(NgbActiveModal);


    public choose(action: SaveBeforeRunChoice['action']): void {
        this.activeModal.close({ action, remember: action === 'save' && this.remember } as SaveBeforeRunChoice);
    }


    public cancel(): void {
        this.activeModal.dismiss();
    }
}
