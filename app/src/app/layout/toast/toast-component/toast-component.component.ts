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

import {Component, Input} from '@angular/core';
import {ToastService} from '../toast.service';

@Component({
    selector: 'cmdb-toast-component',
    templateUrl: './toast-component.component.html',
    styleUrls: ['./toast-component.component.scss'],
    standalone: false
})
export class ToastComponentComponent {

  private _toast: any = {};

  @Input()
  public set toast(value: any) {
    this._toast = value;
  }

  public get toast(): any {
    return this._toast;
  }

  constructor(public toastService: ToastService) {
  }

  /**
   * Sets the animation of the Progressbar
   *
   * @param time The Toast delay
   */
  parse(time: number) {
    if (time) {
      return 'progressBars ' + time.toString() + ' s linear';
    }
    return 'progressBar 3.5s linear';
  }

  /**
   * Initiates a timer for the delay and disposes of the toasts if it wasn't closed within the given time
   *
   * @param time set delay
   * @param toast the toast which is affected
   */
  waitTillDisposal(time: number, toast) {
    function delay(ms: number) {
      return new Promise( resolve => {
        setTimeout(resolve, ms);
      });
    }

    (async () => {
      await delay(time);
      if (toast) {
        this.toastService.remove(toast);
      }
    })();
  }

  closeToast(toast: any) {
    this.toastService.remove(toast);
  }
  
}
