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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import {
    ChangeDetectorRef,
    Component,
    ComponentFactory,
    ComponentFactoryResolver,
    ComponentRef,
    EventEmitter,
    forwardRef,
    Input,
    OnChanges,
    OnDestroy,
    OnInit,
    Output,
    SimpleChanges,
    ViewChild,
    ViewContainerRef
} from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { BehaviorSubject, finalize, Observable, Subscription } from 'rxjs';

import { TypeService } from '../../../../../framework/services/type.service';

import { CmdbType } from '../../../../../framework/models/cmdb-type';
import { JsonMappingComponent } from '../json-mapping/json-mapping.component';
import { CsvMappingComponent } from '../csv-mapping/csv-mapping.component';
import { TypeMappingBaseComponent } from './type-mapping-base.component';
import { AccessControlPermission } from 'src/app/modules/acl/acl.types';
import { LoaderService } from 'src/app/core/services/loader.service';
import { UnsupportedImportFieldGroup } from '../../../models/import-object.models';
/* ------------------------------------------------------------------------------------------------------------------ */

export const mappingComponents: { [type: string]: any } = {
    json: JsonMappingComponent,
    csv: CsvMappingComponent
};

/** Field types whose references the object importer cannot resolve yet. */
export const unsupportedImportFieldTypes: { [type: string]: string } = {
    'ref': 'Reference',
    'location': 'Location',
    'ref-section-field': 'Referenced section'
};

@Component({
    selector: 'cmdb-type-mapping',
    templateUrl: './type-mapping.component.html',
    styleUrls: ['./type-mapping.component.scss'],
    providers: [{ provide: TypeMappingBaseComponent, useExisting: forwardRef(() => TypeMappingComponent) }],
    standalone: false
})
export class TypeMappingComponent extends TypeMappingBaseComponent implements OnInit, OnChanges, OnDestroy {

    @ViewChild('mappingContainer', { read: ViewContainerRef, static: false }) mappingContainer;
    @Output() public typeChange: EventEmitter<any>;
    @Input() public fileFormat;
    @Input() public manuallyMapping: boolean = true;

    private readonly defaultMappingValues = [
        {
            name: 'public_id',
            label: 'Public ID',
            type: 'property'
        },
        {
            name: 'active',
            label: 'Active',
            type: 'property'
        }
    ];

    private typeListSubscription: Subscription;
    private valueChangeSubscription: Subscription;

    private typeIDSubject: BehaviorSubject<number>;
    public typeID: Observable<number>;
    private typeIDSubscription: Subscription;
    public typeList: CmdbType[];
    public typeInstance: CmdbType;
    public configForm: UntypedFormGroup;
    public unsupportedFieldGroups: UnsupportedImportFieldGroup[] = [];

    private component: any;
    public componentRef: ComponentRef<any>;
    private currentFactory: ComponentFactory<any>;
    public isLoading$ = this.loaderService.isLoading$;


    public get currentTypeID(): number {
        return this.typeIDSubject.value;
    }

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private typeService: TypeService,
        private ref: ChangeDetectorRef,
        private resolver: ComponentFactoryResolver,
        private loaderService: LoaderService
    ) {
        super();

        this.typeChange = new EventEmitter<any>();

        this.configForm = new UntypedFormGroup({
            typeID: new UntypedFormControl(null, Validators.required)
        });

        this.typeIDSubject = new BehaviorSubject<number>(null);
        this.typeID = this.typeIDSubject.asObservable();
        this.typeIDSubscription = new Subscription();
    }


    public ngOnInit(): void {
        this.loaderService.show();
        this.typeListSubscription = this.typeService.getTypeList(
            [AccessControlPermission.READ, AccessControlPermission.CREATE, AccessControlPermission.UPDATE])
            .pipe(finalize(() => this.loaderService.hide()))
            .subscribe((typeList: CmdbType[]) => {
                this.typeList = typeList;

                if (typeList.length === 1) {
                    this.configForm.get('typeID').patchValue(this.typeList[0].public_id);
                }
            });

            this.valueChangeSubscription = this.configForm.get('typeID').valueChanges.subscribe((typeID: number) => {
                this.loaderService.show();
                this.typeService.getType(+typeID).pipe(finalize(() => this.loaderService.hide())).subscribe((typeInstance: CmdbType) => {
                    this.typeInstance = Object.assign(new CmdbType(), typeInstance) as CmdbType;
                    this.typeIDSubject.next(+typeID);
                    this.typeChange.emit({ typeID: this.currentTypeID, typeInstance: this.typeInstance });
                });
            });

            this.typeIDSubscription = this.typeID.subscribe((typeID: number) => {
                if (typeID !== null && typeID !== undefined) {
                    this.initMapping();
                }
            }
        );
    }


    public ngOnChanges(changes: SimpleChanges): void {
        if (changes.parsedData !== undefined &&
            changes.parsedData.currentValue !== undefined &&
            changes.parsedData.firstChange !== true) {
                this.initMapping();
        }
    }


    public ngOnDestroy(): void {
        this.typeListSubscription?.unsubscribe();
        this.valueChangeSubscription?.unsubscribe();
        this.typeIDSubscription?.unsubscribe();
    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public initMapping() {
        this.currentMapping = [];
        this.mappingControls = [];
        this.unsupportedFieldGroups = [];

        for (const meta of this.defaultMappingValues) {
            this.mappingControls.push({
                name: meta.name,
                label: meta.label,
                type: 'property'
            });
        }

        if (this.typeInstance !== undefined) {
            for (const field of this.typeInstance.fields) {
                this.mappingControls.push({
                name: field.name,
                label: field.label,
                type: 'field'
                });
            }

            this.unsupportedFieldGroups = this.groupUnsupportedFields(this.typeInstance);
        }

        this.loadMappingComponent();
    }


    /**
     * Groups the fields whose references the importer drops by kind, so the step can warn about them
     * in one compact line per kind instead of repeating the kind on every field.
     */
    private groupUnsupportedFields(typeInstance: CmdbType): UnsupportedImportFieldGroup[] {
        const fields = typeInstance.fields ?? [];

        return Object.keys(unsupportedImportFieldTypes)
            .map((fieldType) => ({
                kind: unsupportedImportFieldTypes[fieldType],
                names: fields
                    .filter((field) => field?.type === fieldType)
                    .map((field) => field.label || field.name)
                    .join(', ')
            }))
            .filter((group) => group.names !== '');
    }


    private resetMappingComponent(): void {
        this.mappingContainer.clear();
        this.component = mappingComponents[this.fileFormat];
        this.currentFactory = this.resolver.resolveComponentFactory(this.component);
    }


    private loadMappingComponent(): void {
        this.resetMappingComponent();
        this.componentRef = this.mappingContainer.createComponent(this.currentFactory);
        this.componentRef.instance.parserConfig = this.parserConfig;
        this.componentRef.instance.parsedData = this.parsedData;
        this.componentRef.instance.mappingControls = this.mappingControls;
        this.componentRef.instance.currentMapping = this.currentMapping;
        this.componentRef.instance.mappingChange = this.mappingChange;
    }
}
