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

import {Injectable} from '@angular/core';

@Injectable({
  providedIn: 'root'
})

export class ToastService {

  public toastsright: any[] = [];
  public toastsleft: any[] = [];
  public toastsdownleft: any[] = [];
  public toastsdownright: any[] = [];
  public toastscenter: any[] = [];


  /**
   * Receives requests to show toasts and determines what position to put
   * them in based on the direction parameter
   *
   * @param text The text contained inside the toast
   * @param options Contains the toast configurations
   * @param direction Determines where the toast will be positioned
   */
  public showToast(text: string, options: any = {}, direction?: string) {
    if (!options.icon) {
      options.icon = 'fas fa-info-circle';
    }
    switch (direction) {
      case 'right': {
        this.toastsright.push({text, ...options});
        break;
      }
      case 'left': {
        this.toastsleft.push({text, ...options});
        break;
      }
      case 'downleft': {
        this.toastsdownleft.push({text, ...options});
        break;
      }
      case 'downright': {
        this.toastsdownright.push({text, ...options});
        break;
      }
      case 'center': {
        this.toastscenter.push({text, ...options});
        break;
      }
      default: {
        this.toastsright.push({text, ...options});
        break;
      }
    }
  }

  /**
   * Error Toast for displaying an error
   *
   * @param text your text content
   * @param options get following parameters {headerName: 'your header name', icon : 'fas fa-cube', classname: class for the toast }
   * @param direction position of your toast
   */
  public error(text: string, options: any = {headerName: 'An Error Occurred', icon: 'fas fa-exclamation-circle'}, direction?: string) {
    options.classname += ' border-danger';
    options.iconClass = 'text-danger';
    this.showToast(text, options, direction);
  }


  /**
   * Warning Toast for displaying warnings
   *
   * @param text your text content
   * @param options get following parameters {headerName: 'your header name', icon : 'fas fa-cube', classname: class for the toast }
   * @param direction position of your toast
   */
  public warning(text: string, options: any = {headerName: 'Warning', icon: 'fas fa-exclamation-triangle'}, direction?: string) {
    options.classname += ' border-warning';
    options.iconClass = 'text-warning';
    this.showToast(text, options, direction);
  }


  /**
   * Success Toast for successfully executing a task
   *
   * @param text your text content
   * @param options get following parameters {headerName: 'your header name', icon : 'fas fa-cube', classname: class for the toast }
   * @param direction position of your toast
   */
  public success(text: string, options: any = {headerName: 'Success', icon: 'fas fa-check-circle'}, direction?: string) {
    options.classname += ' border-success';
    options.iconClass = 'text-success';
    this.showToast(text, options, direction);
  }

  /**
   * Info Toast for displaying information
   *
   * @param text your text content
   * @param options get following parameters {headerName: 'your header name', icon : 'fas fa-cube', classname: class for the toast }
   * @param direction position of your toast
   */
  public info(text: string, options: any = {headerName: 'Information', icon: 'fas fa-info-circle'}, direction?: string) {
    options.classname += ' border-info';
    options.iconClass = 'text-info';
    this.showToast(text, options, direction);
  }


  /**
   * Removes the toast which was passed to the parameter
   *
   * @param toast The toast you want to remove
   */
  public remove(toast) {
    this.toastscenter =  this.toastscenter.filter(t => t !== toast);
    this.toastsdownright =  this.toastsdownright.filter(t => t !== toast);
    this.toastsdownleft =  this.toastsdownleft.filter(t => t !== toast);
    this.toastsleft =  this.toastsleft.filter(t => t !== toast);
    this.toastsright =  this.toastsright.filter(t => t !== toast);
  }

}
