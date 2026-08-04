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
import { Component, inject, ChangeDetectorRef, Input, OnDestroy, OnInit } from '@angular/core';
import { Router } from '@angular/router';

import { finalize, Observable, ReplaySubject, Subscription, takeUntil } from 'rxjs';

import { TypeService } from '../../services/type.service';
import { UserService } from '../../../management/services/user.service';
import { ToastService } from '../../../layout/toast/toast.service';
import { GroupService } from '../../../management/services/group.service';
import { SidebarService } from '../../../layout/services/sidebar.service';
import { ValidationService } from '../services/validation.service';

import { CmdbType, CmdbTypeSection } from '../../models/cmdb-type';
import { CmdbMode } from '../../modes.enum';
import { Group } from '../../../management/models/group';
import { User } from '../../../management/models/user';
import { CollectionParameters } from '../../../services/models/api-parameter';
import { APIGetMultiResponse } from '../../../services/models/api-response';
import { AccessControlList } from 'src/app/modules/acl/acl.types';
import { LoaderService } from 'src/app/core/services/loader.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-type-builder',
    templateUrl: './type-builder.component.html',
    styleUrls: ['./type-builder.component.scss'],
    standalone: false
})
export class TypeBuilderComponent implements OnInit, OnDestroy {
    private readonly router = inject(Router);
    private readonly typeService = inject(TypeService);
    private readonly toast = inject(ToastService);
    private readonly userService = inject(UserService);
    private readonly groupService = inject(GroupService);
    private readonly sidebarService = inject(SidebarService);
    private readonly validationService = inject(ValidationService);
    private readonly changeDetector = inject(ChangeDetectorRef);
    private readonly loaderService = inject(LoaderService);

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();
    private subscriptions = new Subscription();
    isHighlighted: boolean = false;

    @Input() public typeInstance: CmdbType;

    // Selected render mode
    @Input() public mode: CmdbMode = CmdbMode.Create;

    // Index of start step
    @Input() public stepIndex: number = 0;

    // Possible render modes
    public modes = CmdbMode;

    // List of possible groups
    public groups: Array<Group> = [];
    // List of possible users
    public users: Array<User> = [];
    // List of possible types
    public types: Array<CmdbType> = [];

    // Basic step valid
    public basicValid: boolean = true;
    // Content step valid
    public contentValid: boolean = true;
    // Meta step valid
    public metaValid: boolean = true;
    // ACL step valid
    public accessValid: boolean = true;

    // 1-based positions of the steps the stepper has to mark as failing
    public invalidSteps: Array<number> = [];

    isNameValid = true;
    isLabelValid = true;
    isValid$: Observable<boolean>;
    isSectionValid$: Observable<boolean>;

    public isIdentifierValid: boolean;
    private subscription: Subscription;

    isSectionHighlighted: boolean = false;
    isFieldHighlighted: boolean = false;
    disableFields: boolean = false
    isSectionWithoutFields: boolean = false

    public isLoading$ = this.loaderService.isLoading$;

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    public ngOnInit(): void {

        const sectionHighlightSubscription = this.validationService?.isSectionHighlighted$.subscribe((highlighted) => {

            setTimeout(() => {
                this.isSectionHighlighted = highlighted;
            });
        });

        // Subscribe to the field highlight state
        const fieldHighlightSubscription = this.validationService?.isFieldHighlighted$.subscribe((highlighted) => {

            setTimeout(() => {
                this.isFieldHighlighted = highlighted;
            });
        });

        const disableFieldsSubscription = this.validationService?.disableFields$.subscribe((disableFields) => {

            setTimeout(() => {
                this.disableFields = disableFields;
            });
        });

        const sectionWithoutFieldSubscription = this.validationService?.isSectionWithoutField$.subscribe((disabledSection) => {
            setTimeout(() => {
                this.isSectionWithoutFields = disabledSection
            });
        });

        this.subscriptions?.add(sectionHighlightSubscription);
        this.subscriptions?.add(fieldHighlightSubscription);
        this.subscriptions?.add(disableFieldsSubscription)
        this.subscriptions?.add(sectionWithoutFieldSubscription)

        this.isValid$ = this.validationService?.getIsValid();
        this.isSectionValid$ = this.validationService?.overallSectionValidity();

        if (this.mode === CmdbMode.Create) {
            this.typeInstance = new CmdbType();
            this.typeInstance.active = true;
            this.typeInstance.version = '1.0.0';
            this.typeInstance.author_id = this.userService?.getCurrentUser()?.public_id;
            this.typeInstance.render_meta = {
                icon: undefined,
                sections: [],
                externals: [],
                summary: {
                    fields: []                
                }
            };
            this.typeInstance.ci_explorer_label = null;

            this.typeInstance.acl = new AccessControlList(false);
        }

        const groupsCallParameters: CollectionParameters = {
            filter: undefined,
            limit: 0,
            sort: 'public_id',
            order: 1,
            page: 1
        };

        this.groupService?.getGroups(groupsCallParameters).pipe(takeUntil(this.subscriber))
            .subscribe({
                next: (response: APIGetMultiResponse) => {
                    this.groups = [...response?.results as Array<Group>];
                },
                error: (e) => {
                    this.toast.error(e?.error?.message)
                },
                complete: () => {
                    this.checkAclGroupExist();
                }
            });

        const typesCallParameters: CollectionParameters = {
            filter: undefined,
            limit: 0,
            sort: 'public_id',
            order: 1,
            page: 1,
            projection: { public_id: 1, name: 1, label: 1, render_meta: 1 }
        };
        this.typeService.getTypes(typesCallParameters).pipe(takeUntil(this.subscriber))
            .subscribe((response: APIGetMultiResponse) => {
                this.types = response?.results as Array<CmdbType>;
                this.changeDetector.detectChanges();
            });

        this.changeDetector.detectChanges();
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
        if (this.subscription) {
            this.subscription?.unsubscribe();
        }
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onBasicValidityChange(valid: boolean): void {
        this.basicValid = valid;
        this.refreshInvalidSteps();
    }


    public onContentValidityChange(valid: boolean): void {
        this.contentValid = valid;
        this.refreshInvalidSteps();
    }


    public onAccessValidityChange(valid: boolean): void {
        this.accessValid = valid;
        this.refreshInvalidSteps();
    }


    /* ----------------------------------------------- CSS CLASS HANDLERS ------------------------------------------------ */


    get isSaveButtonDisabled(): boolean {
        return !this.basicValid || !this.contentValid || !this.metaValid || !this.accessValid || !this.isLabelValid || !this.isNameValid || this.isSectionHighlighted || this.isFieldHighlighted || this.disableFields || !this.isSectionWithoutFields;
    }


    /* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * Collects the failing steps for the stepper, by the position the wizard renders them in:
     * basic information, content, meta, access.
     */
    private refreshInvalidSteps(): void {
        const failing: Array<number> = [];

        if (!this.basicValid) {
            failing.push(1);
        }

        if (!this.contentValid) {
            failing.push(2);
        }

        if (!this.metaValid) {
            failing.push(3);
        }

        if (!this.accessValid) {
            failing.push(4);
        }

        this.invalidSteps = failing;
    }


    /**
     * Check ACL group assignment.
     * Check if assigned groups still exist. Error message if group cannot be found.
     * @private
     */
    private checkAclGroupExist(): void {
        if (this.typeInstance.acl && this.typeInstance?.acl?.groups && this.typeInstance?.acl?.groups?.includes && this.groups) {
            Object.keys(this.typeInstance?.acl?.groups?.includes).forEach((key) => {
                const found = this.groups.find(g => g?.public_id === Number(key));

                if (!found) {
                    this.toast.error(`The group for the ACL setting does not exist: GroupID: ${key}`);
                }
            });
        }
    }


    public saveType() {
        if(this.isSaveButtonDisabled){
            this.toast.error('Form is invalid or incomplete. Cannot save.');
            return;
        }
        const saveTypeInstance: CmdbType = Object.assign({}, this.typeInstance) as CmdbType;
        const sections: Array<CmdbTypeSection> = [];

        for (const section of saveTypeInstance?.render_meta.sections) {
            const fields = [];

            for (const field of section?.fields) {
                if (typeof field === 'object' && field !== null) {
                    fields.push(field?.name);
                } else {
                    fields.push(field);
                }
            }

            section.fields = fields;
            sections.push(section);
        }

        saveTypeInstance.render_meta.sections = sections;

        if (this.mode === CmdbMode.Create) {
            this.loaderService.show();
            let newTypeID = null;
            saveTypeInstance.editor_id = undefined;

            this.typeService?.postType(saveTypeInstance)?.pipe(finalize(() => this.loaderService.hide())).subscribe({
                next: (typeIDResp: CmdbType) => {
                    newTypeID = +typeIDResp?.public_id;
                    this.router.navigate(['/framework/type/'], { queryParams: { typeAddSuccess: newTypeID } });
                    this.sidebarService?.loadCategoryTree();
                    this.toast.success(`Type was successfully created: TypeID: ${newTypeID}`);
                },
                error: (e) => {
                    this.toast.error(e?.error?.message);
                }
            });
        } else if (this.mode === CmdbMode.Edit) {
            this.loaderService.show();
            saveTypeInstance.editor_id = this.userService?.getCurrentUser()?.public_id;
            this.typeService.putType(saveTypeInstance).pipe(finalize(() =>  this.loaderService.hide())).subscribe({
                next: (updateResp: CmdbType) => {
                    this.toast.success(`Type was successfully edited: TypeID: ${updateResp?.public_id}`);
                    this.sidebarService.loadCategoryTree();
                    this.router.navigate(['/framework/type/'],
                        { queryParams: { typeEditSuccess: updateResp?.public_id } });
                },
                error: (error) => {
                    this.toast.error(error?.error?.message);
                }
            });
        }
    }

}
