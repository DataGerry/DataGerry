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
import { Component, EventEmitter, Input, OnDestroy, OnInit, Output } from '@angular/core';

import { Subscription } from 'rxjs';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { LinkService } from '../../../services/link.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-object-link-delete-modal',
    templateUrl: './object-link-delete-modal.component.html',
    styleUrls: ['./object-link-delete-modal.component.scss'],
    standalone: false
})
export class ObjectLinkDeleteModalComponent implements OnInit, OnDestroy {

  @Input() public publicID: number = null;
  @Output() public closeEmitter: EventEmitter<string> = new EventEmitter<string>();

  private deleteSubscription: Subscription;

/* --------------------------------------------------- LIFE CYCCLE -------------------------------------------------- */
    constructor(public activeModal: NgbActiveModal,
                private linkService: LinkService,
                private toastService: ToastService) {
    }


    public ngOnInit(): void {
        this.deleteSubscription = new Subscription();
    }


    public ngOnDestroy(): void {
        this.deleteSubscription?.unsubscribe();
    }

/* -------------------------------------------------- EVENT HANDLER ------------------------------------------------- */

    public onDelete() {
        //DAT-774
        this.deleteSubscription = this.linkService.deleteLink(this.publicID).subscribe(() => {
            this.activeModal.close();
            this.closeEmitter.emit('deleted');
            this.toastService.success("ObjectLink was deleted!");
        });
    }
}
