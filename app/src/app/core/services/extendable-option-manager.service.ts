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
import { Injectable, inject } from '@angular/core';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { EMPTY, Observable, defer, from, of } from 'rxjs';
import { catchError, finalize, map, switchMap, tap } from 'rxjs/operators';

import { ExtendableOptionService } from 'src/app/toolbox/isms/services/extendable-option.service';
import { ExtendableOption } from 'src/app/framework/models/object-group.model';
import { ExtendableOptionCatalogService } from './extendable-option-catalog.service';
import { LoaderService } from './loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import {
    ExtendableOptionManagerComponent
} from '../components/extendable_option_manager/extendable-option-manager.component';
import { ManageableOptionType, manageableOptionType } from '../components/extendable_option_manager/manageable-option-types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Opens the shared option manager for a field's `option_type`, so every Manage action behaves alike. */
@Injectable({ providedIn: 'root' })
export class ExtendableOptionManagerService {

    private readonly extendableOptionService = inject(ExtendableOptionService);
    private readonly optionCatalog = inject(ExtendableOptionCatalogService);
    private readonly modalService = inject(NgbModal);
    private readonly loaderService = inject(LoaderService);
    private readonly toast = inject(ToastService);

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** True while this option type may be extended from the field that uses it. */
    public isManageable(optionType: string): boolean {
        return !!manageableOptionType(optionType);
    }


    public descriptorOf(optionType: string): ManageableOptionType | null {
        return manageableOptionType(optionType);
    }


    /** Emits once the manager closes, with the catalog already invalidated. */
    public open(optionType: string): Observable<void> {
        const manageable = manageableOptionType(optionType);

        if (!manageable) {
            return EMPTY;
        }

        return defer(() => {
            this.loaderService.show();
            return this.extendableOptionService.getExtendableOptionsByType(manageable.optionType);
        }).pipe(
            finalize(() => this.loaderService.hide()),
            catchError((error) => {
                this.toast.error(error?.error?.message);
                return EMPTY;
            }),
            switchMap((response) => this.awaitManager(manageable, response?.results ?? [])),
            tap(() => this.optionCatalog.invalidate(manageable.optionType))
        );
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** Dismissing the manager counts as closing it: options may have changed either way. */
    private awaitManager(manageable: ManageableOptionType, options: Array<ExtendableOption>): Observable<void> {
        const modalRef = this.modalService.open(ExtendableOptionManagerComponent, {
            size: 'lg',
            windowClass: 'dg-modal-window',
            backdropClass: 'dg-modal-window-backdrop'
        });

        modalRef.componentInstance.options = options;
        modalRef.componentInstance.optionType = manageable.optionType;
        modalRef.componentInstance.modalTitle = manageable.modalTitle;
        modalRef.componentInstance.itemLabel = manageable.itemLabel;
        modalRef.componentInstance.itemLabelPlural = manageable.itemLabelPlural;

        return from(modalRef.result).pipe(
            catchError(() => of(undefined)),
            map(() => undefined)
        );
    }
}
