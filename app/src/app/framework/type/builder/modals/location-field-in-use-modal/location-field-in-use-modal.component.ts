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
import { Router } from '@angular/router';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

export type LocationFieldDeletionScope = 'field' | 'section';

@Component({
    selector: 'cmdb-location-field-in-use-modal',
    templateUrl: './location-field-in-use-modal.component.html',
    standalone: false
})
export class LocationFieldInUseModalComponent {
    @Input() scope: LocationFieldDeletionScope = 'field';
    @Input() objectPublicIds: number[] = [];

    public readonly activeModal = inject(NgbActiveModal);
    private readonly router = inject(Router);

    public get title(): string {
        return this.scope === 'section'
            ? 'Cannot delete section'
            : 'Cannot delete location field';
    }

    public get message(): string {
        return this.scope === 'section'
            ? 'This section contains a location field that is still used by existing objects. '
              + 'Remove the location from the listed objects before deleting the section.'
            : 'The location field is still used by existing objects. '
              + 'Remove the location from the listed objects before deleting the field.';
    }

    public openObject(publicId: number): void {
        this.activeModal.dismiss('navigate');
        this.router.navigate(['/framework/object/view', publicId]);
    }
}
