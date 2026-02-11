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

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, Input } from '@angular/core';
import { Router } from '@angular/router';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

@Component({
    selector: 'core-warning-modal',
    templateUrl: './core-warning-modal.component.html',
    standalone: false
})
export class CoreWarningModalComponent {
  @Input() title: string = 'Attention';
  @Input() message: string;
  @Input() confirmLabel: string;
  @Input() cancelLabel: string = 'Close';
  @Input() warningTitle: string = 'Warning:';
  @Input() warningIconClass: string = 'fas fa-exclamation-circle';
  @Input() route: string;

  constructor(public activeModal: NgbActiveModal, private router: Router) {}

  navigate(): void {
    this.activeModal.close('confirmed');
    if (this.route) {
      this.router.navigate([this.route]);
    }
  }

  cancel(): void {
    this.activeModal.dismiss('cancelled');
  }
}
