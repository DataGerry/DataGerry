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
import {
    Component,
    ComponentFactoryResolver,
    ComponentRef,
    Input, OnDestroy,
    OnInit,
    Output,
    ViewChild,
    EventEmitter,
    ViewContainerRef
} from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';

import { ReplaySubject, Subscription } from 'rxjs';

import { configComponents } from './configs.list';
import { CmdbType } from '../../../models/cmdb-type';
import { CmdbMode } from '../../../modes.enum';
import { ConfigEditBaseComponent } from './config.edit';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-config-edit',
    templateUrl: './config-edit.component.html',
    styleUrls: ['./config-edit.component.scss'],
    standalone: false
})
export class ConfigEditComponent implements OnInit, OnDestroy {

    public modes: typeof CmdbMode = CmdbMode;

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    public form: UntypedFormGroup;

    @Input() public mode: CmdbMode = CmdbMode.Create;
    @Input() public data: any;

    @Input() public fields: Array<any> = [];
    @Input() public sections: Array<any> = [];
    @Input() public types: Array<CmdbType> = [];
    @Input() public fieldSectionType: string;
    @Input() public hiddenStatus: boolean;
    @Input() public isDisabled: boolean = false;

    @ViewChild('configContainer', { read: ViewContainerRef, static: true }) container;

    private component: any;
    private componentRef: ComponentRef<any>;

    fieldChangesSubscription: Subscription;

    // Changed values emitter of components created
    @Output() valuesChanged: EventEmitter<any> = new EventEmitter();

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */
    constructor(private resolver: ComponentFactoryResolver) {
        this.form = new UntypedFormGroup({});
    }


    public ngOnInit(): void {
        this.container.clear();
        this.component = configComponents[this.data.type];

        const factory = this.resolver.resolveComponentFactory<ConfigEditBaseComponent>(this.component);
        this.componentRef = this.container.createComponent(factory);
        this.componentRef.instance.mode = this.mode;
        this.componentRef.instance.data = this.data;
        this.componentRef.instance.form = this.form;
        this.componentRef.instance.sections = this.sections;
        this.componentRef.instance.fields = this.fields;
        this.componentRef.instance.fieldSectionType = this.fieldSectionType;
        this.componentRef.instance.hiddenStatus = this.hiddenStatus;

        this.fieldChangesSubscription = this.componentRef.instance.fieldChanges$.subscribe(
            (data: any) => this.fieldValueChanged(data)
        );
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
        this.fieldChangesSubscription?.unsubscribe();
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Emits changes of values
     * @param data new values
     */
    public fieldValueChanged(data: any) {
        this.valuesChanged.emit(data);
    }
}
