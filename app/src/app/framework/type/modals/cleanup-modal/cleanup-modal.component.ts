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
import { AfterViewInit, Component, Input, OnDestroy } from '@angular/core';

import { ReplaySubject, takeUntil } from 'rxjs';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { ObjectService } from '../../../services/object.service';
import { UserService } from '../../../../management/services/user.service';

import { CmdbType } from '../../../models/cmdb-type';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-cleanup-modal',
    templateUrl: './cleanup-modal.component.html',
    styleUrls: ['./cleanup-modal.component.scss'],
    standalone: false
})
export class CleanupModalComponent implements AfterViewInit, OnDestroy {
    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    // Type instance of the cleanable objects
    @Input() public type: CmdbType;
    // Number of uncleaned objects
    public numberOfObjects: number = 0;
    // In current cleaning operation
    public cleaning: boolean = false;

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYCLE                                                     */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private objectService: ObjectService,
        public userService: UserService,
        public activeModal: NgbActiveModal
    ) {

    }


    public ngAfterViewInit(): void {
        this.objectService.countUncleanObjects(this.type.public_id).pipe(takeUntil(this.subscriber))
        .subscribe((count: number) => {
            this.numberOfObjects = count;
        });
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
      }

/* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * Triggers the api clean call.
     */
    public clean(): void {
        this.cleaning = true;

        this.objectService.cleanObjects(this.type.public_id).pipe(takeUntil(this.subscriber))
        .subscribe(() => {
            this.cleaning = false;
            this.activeModal.close('Clean');
        });
    }
}
