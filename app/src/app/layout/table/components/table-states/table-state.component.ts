/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import { Component, ElementRef, EventEmitter, Input, Output, Renderer2, ViewChild } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { TableState } from '../../table.types';
/* ------------------------------------------------------------------------------------------------------------------ */
@Component({
    selector: 'table-state',
    templateUrl: './table-state.component.html',
    styleUrls: ['./table-state.component.scss'],
    standalone: false
})
export class TableStateComponent {
    // Current possible table states
    @Input() public tableStates: Array<TableState> = [];

    // Current selected state
    @Input() public currentState: TableState;

    // State selection event emitter
    @Output() public stateSelect: EventEmitter<TableState> = new EventEmitter<TableState>();

    // State save event emitter
    @Output() public stateSave: EventEmitter<string> = new EventEmitter<string>();

    // State update event emitter
    @Output() public stateUpdate: EventEmitter<TableState> = new EventEmitter<TableState>();

    // State delete event emitter
    @Output() public stateDelete: EventEmitter<TableState> = new EventEmitter<TableState>();

    // State reset event emitter
    @Output() public stateReset: EventEmitter<void> = new EventEmitter<void>();

    // Toggle button element reference
    @ViewChild('toggleButton') toggleButton: ElementRef;

    // Name form validation
    public form: UntypedFormGroup;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(private renderer: Renderer2) {
        this.form = new UntypedFormGroup({
            name: new UntypedFormControl('', Validators.required)
        });
    }


    ngAfterViewInit(): void {
        this.renderer.listen('window', 'click',(e:Event)=>{
            // Only run when toggleButton is not clicked
            if(e.target !== this.toggleButton.nativeElement){
                this.form.reset();
            }
        });
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * Get the control of the settings
     */
    public get nameControl(): UntypedFormControl {
        return this.form.get('name') as UntypedFormControl;
    }


    /**
     * On state selection change
     * @param state
     */
    public selectState(state: TableState) {
        this.stateSelect.emit(state);
    }


    /**
     * Reset to a existing state.
     */
    public resetState() {
        this.stateReset.emit();
    }


    /**
     * Save new state
     * @param name
     * @param event
     */
    public saveState(name: string, event: Event) {
        event.stopPropagation();
        this.stateSave.emit(name);
        this.form.reset();
    }


    /**
     * Update a existing state
     * @param state
     * @param event
     */
    public updateState(state: TableState, event: Event) {
        event.stopPropagation();
        this.stateUpdate.emit(state);
    }


    /**
     * Delete a existing state.
     * @param state
     * @param event
     */
    public deleteState(state: TableState, event: Event) {
        event.stopPropagation();
        const index = this.tableStates.indexOf(state, 0);
        if (index > -1) {
        this.tableStates.splice(index, 1);
        }
        this.stateDelete.emit(state);
    }
}
