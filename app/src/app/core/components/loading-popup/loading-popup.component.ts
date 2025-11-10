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

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, Input, OnChanges } from '@angular/core';

@Component({
    selector: 'app-loading-popup',
    templateUrl: './loading-popup.component.html',
    styleUrls: ['./loading-popup.component.scss'],
    standalone: false
})
export class LoadingPopupComponent implements OnChanges {
  @Input() message = 'Creating your object...';
  @Input() isVisible = false;
  @Input() progress = 0;
  
  stages = [
    { label: 'Validating', active: false },
    { label: 'Sending', active: false },
    { label: 'Processing', active: false }
  ];

  ngOnChanges() {
    if(this.isVisible) {
      this.animateStages();
    }
  }

  private animateStages() {
    this.stages.forEach((stage, index) => {
      setTimeout(() => {
        stage.active = true;
        if(index === this.stages.length - 1) {
          setTimeout(() => this.resetStages(), 2000);
        }
      }, index * 1500);
    });
  }

  private resetStages() {
    this.stages.forEach(stage => stage.active = false);
    this.animateStages();
  }
}