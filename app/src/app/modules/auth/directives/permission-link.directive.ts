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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Directive, Input, TemplateRef, ViewContainerRef } from '@angular/core';

import { PermissionService } from '../services/permission.service';
import { AclPermissionService } from '../services/acl-permission.service';

import { AccessControlList } from 'src/app/modules/acl/acl.types';
/* ------------------------------------------------------------------------------------------------------------------ */

@Directive({
    selector: '[permissionLink]',
    exportAs: 'permissionLink',
    standalone: false
})
export class PermissionLinkDirective {

    private rightNames: string[] = [];
    private requirements: string | string[];
    private acl: AccessControlList;

    @Input('permissionLinkRequirements') set permissionLinkRequirements(requirements: string | string[]) {
        this.requirements = requirements;
    }

    @Input('permissionLink') set permissionLink(rightNames: string | string[]) {
        if (rightNames !== undefined) {
            if (Array.isArray(rightNames)) {
                this.rightNames = rightNames;
            } else {
                this.rightNames = [];
                this.rightNames.push(rightNames);
            }
        }

        this.updateView();
    }


    @Input('permissionLinkAcl') set permissionLinkType(acl: AccessControlList) {
        this.acl = acl;
        this.updateView();
    }


    @Input() routerLink: string = undefined;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(
        private templateRef: TemplateRef<any>,
        private viewContainer: ViewContainerRef,
        private permissionService: PermissionService,
        private aclPermissionService: AclPermissionService
    ) {

    }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    private checkPermission() {
        let hasPermission = false;

        for (const right of this.rightNames) {
            if (this.permissionService.hasRight(right) || this.permissionService.hasExtendedRight(right)) {
                hasPermission = true;
            } else {
                hasPermission = false;
                break;
            }
        }


        if (this.requirements && this.acl && hasPermission) {
            const aclperms = this.aclPermissionService.checkRights(this.acl, this.requirements);

            if (aclperms !== null) {
                hasPermission = aclperms;
            }
        }

        return hasPermission;
    }


    private updateView() {
        this.viewContainer.clear();

        if (this.checkPermission()) {
            this.viewContainer.createEmbeddedView(this.templateRef);
        }
    }
}