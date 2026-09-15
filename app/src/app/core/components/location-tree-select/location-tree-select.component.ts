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
import { Component, EventEmitter, forwardRef, inject, Input, Output } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

import { LocationPickerService } from './location-picker.service';
import { LocationSelection } from './location-tree-select.model';
/* ------------------------------------------------------------------------------------------------------------------ */


@Component({
    selector: 'app-location-tree-select',
    templateUrl: './location-tree-select.component.html',
    styleUrls: ['./location-tree-select.component.scss'],
    standalone: false,
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => LocationTreeSelectComponent),
            multi: true
        }
    ]
})
export class LocationTreeSelectComponent implements ControlValueAccessor {

    private static readonly DEFAULT_ICON = 'fas fa-map-marker-alt';

    /** public_id of the edited object; its own node and descendants stay unselectable in the picker. */
    @Input() public excludeObjectId: number | null = null;

    /** When false the value cannot be cleared (e.g. the object is already a parent of a location). */
    @Input() public clearable = true;

    @Input() public placeholder = 'No location set';

    /** Lets the host render the selection for a preselected value without an extra lookup. */
    @Input()
    public set selectedDisplay(value: { name: string; icon: string } | null) {
        this._selectedDisplay = value;
        this.refreshDisplay();
    }

    @Output() public selectionChange = new EventEmitter<LocationSelection | null>();

    public selectedId: number | null = null;
    public disabled = false;
    public display: { name: string; icon: string } | null = null;

    private _selectedDisplay: { name: string; icon: string } | null = null;

    private readonly picker = inject(LocationPickerService);

    private onChange: (value: number | null) => void = () => {};
    private onTouched: () => void = () => {};

    /* ---------------------------------------------- CONTROL VALUE ACCESSOR ------------------------------------------- */

    public writeValue(value: number | string | null): void {
        const isEmpty = value === null || value === undefined || value === '';
        this.selectedId = isEmpty ? null : Number(value);
        this.refreshDisplay();
    }

    public registerOnChange(fn: (value: number | null) => void): void {
        this.onChange = fn;
    }

    public registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    public setDisabledState(isDisabled: boolean): void {
        this.disabled = isDisabled;
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    /** Opens the picker; applies the pick when the user confirms one, no-op when dismissed. */
    public async openPicker(): Promise<void> {
        if (this.disabled) {
            return;
        }

        const selection = await this.picker.open({
            selectedId: this.selectedId,
            excludeObjectId: this.excludeObjectId
        });

        this.onTouched();

        if (selection) {
            this.selectedId = selection.public_id;
            this.display = { name: selection.name, icon: selection.icon };
            this.onChange(selection.public_id);
            this.selectionChange.emit(selection);
        }
    }

    public clear(event: MouseEvent): void {
        event.stopPropagation();

        if (!this.clearable || this.disabled) {
            return;
        }

        this.selectedId = null;
        this.display = null;
        this.onChange(null);
        this.onTouched();
        this.selectionChange.emit(null);
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ---------------------------------------------- */

    private refreshDisplay(): void {
        if (this.selectedId == null) {
            this.display = null;
            return;
        }

        this.display = this._selectedDisplay
            ?? { name: `Location #${ this.selectedId }`, icon: LocationTreeSelectComponent.DEFAULT_ICON };
    }
}
