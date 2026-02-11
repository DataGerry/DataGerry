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

import { Component, OnInit } from '@angular/core';
import { FormControl, FormGroup, Validators } from '@angular/forms';
import { StatusService } from '../../services/status.service';
import { CmdbStatus } from '../../models/cmdb-status';
import { ActivatedRoute, Router } from '@angular/router';

@Component({
  selector: 'cmdb-status-edit',
  templateUrl: './status-edit.component.html',
  styleUrls: ['./status-edit.component.scss']
})
export class StatusEditComponent implements OnInit {

  public statusID: number;
  public shortMaxLength: number = 5;
  public editStatusForm: FormGroup;
  public editStatus: CmdbStatus;

  constructor(private statusService: StatusService<CmdbStatus>, private route: ActivatedRoute, private router: Router) {
    this.route.params.subscribe((params) => {
      this.statusID = params.publicID;
    });
    this.editStatusForm = new FormGroup({
      name: new FormControl('', Validators.required),
      label: new FormControl('', Validators.required),
      short: new FormControl('', Validators.maxLength(this.shortMaxLength))
    });
  }


  public ngOnInit(): void {
    this.statusService.getStatus(this.statusID).subscribe((respStatus: CmdbStatus) => {
      this.editStatus = respStatus;
      this.editStatusForm.reset();
      this.editStatusForm.patchValue(this.editStatus);
      this.editStatusForm.markAllAsTouched();
    });
  }

  public get name() {
    return this.editStatusForm.get('name');
  }

  public get label() {
    return this.editStatusForm.get('label');
  }

  public get controls() {
    return this.editStatusForm.controls;
  }

  public saveStatus() {
    this.editStatusForm.markAllAsTouched();
    if (this.editStatusForm.valid) {
      Object.assign(this.editStatus, this.editStatusForm.getRawValue());
      this.statusService.putStatus(this.editStatus).subscribe(() => {
          this.router.navigate(['/framework/status/']);
        },
        error => {
          // console.error(error);
        });
    }
  }

}
