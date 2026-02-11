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

import { Component } from '@angular/core';
import { CmdbStatus } from '../../models/cmdb-status';
import { StatusService } from '../../services/status.service';
import { FormControl, FormGroup, Validators } from '@angular/forms';
import { Router } from '@angular/router';

@Component({
  selector: 'cmdb-status-add',
  templateUrl: './status-add.component.html',
  styleUrls: ['./status-add.component.scss']
})
export class StatusAddComponent {

  public shortMaxLength: number = 5;
  public addStatusForm: FormGroup;

  constructor(private statusService: StatusService<CmdbStatus>, private router: Router) {
    this.addStatusForm = new FormGroup({
      name: new FormControl('', Validators.required),
      label: new FormControl('', Validators.required),
      short: new FormControl('', Validators.maxLength(this.shortMaxLength))
    });
  }

  public get name() {
    return this.addStatusForm.get('name');
  }

  public get label() {
    return this.addStatusForm.get('label');
  }

  public get controls() {
    return this.addStatusForm.controls;
  }

  public saveStatus() {
    this.addStatusForm.markAllAsTouched();
    if (this.addStatusForm.valid) {
      const newStatus: CmdbStatus = this.addStatusForm.getRawValue();
      this.statusService.postStatus(newStatus).subscribe((newPublicID: number) => {
        this.router.navigate([`/framework/status/`]);
      }, error => {
        // console.error(error);
      });
    }
  }

}
