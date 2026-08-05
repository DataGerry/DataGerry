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
import { NotificationType } from 'src/app/core/state/notification/notification.model';
import { NotificationService } from 'src/app/core/state/notification/notification.service';

interface ToastOptions {
  headerName?: string;
  icon?: string;
  classname?: string;
  iconClass?: string;
  [key: string]: unknown;
}

@Injectable({
  providedIn: 'root'
})

export class ToastService {
  private static readonly TYPE_CONFIG: Record<NotificationType, Required<Pick<ToastOptions, 'headerName' | 'icon' | 'iconClass'>> & { borderClass: string }> = {
    error: {
      headerName: 'An Error Occurred',
      icon: 'fas fa-exclamation-circle',
      iconClass: 'text-danger',
      borderClass: 'border-danger'
    },
    warning: {
      headerName: 'Warning',
      icon: 'fas fa-exclamation-triangle',
      iconClass: 'text-warning',
      borderClass: 'border-warning'
    },
    success: {
      headerName: 'Success',
      icon: 'fas fa-check-circle',
      iconClass: 'text-success',
      borderClass: 'border-success'
    },
    info: {
      headerName: 'Information',
      icon: 'fas fa-info-circle',
      iconClass: 'text-info',
      borderClass: 'border-info'
    }
  };

  constructor(private readonly notificationService: NotificationService) {}
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
  public showToast(text: string, options: ToastOptions = {}, direction?: string, type: NotificationType = 'info') {
    this.notificationService.add(text, type);

    if (!options.icon) {
      options.icon = 'fas fa-info-circle';
    }

    const toast = { text, ...options };

    switch (direction) {
      case 'right': {
        this.toastsright.push(toast);
        break;
      }
      case 'left': {
        this.toastsleft.push(toast);
        break;
      }
      case 'downleft': {
        this.toastsdownleft.push(toast);
        break;
      }
      case 'downright': {
        this.toastsdownright.push(toast);
        break;
      }
      case 'center': {
        this.toastscenter.push(toast);
        break;
      }
      default: {
        this.toastsright.push(toast);
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
  public error(text: string, options: ToastOptions = {}, direction?: string) {
    this.showTypedToast('error', text, options, direction);
  }


  /**
   * Warning Toast for displaying warnings
   *
   * @param text your text content
   * @param options get following parameters {headerName: 'your header name', icon : 'fas fa-cube', classname: class for the toast }
   * @param direction position of your toast
   */
  public warning(text: string, options: ToastOptions = {}, direction?: string) {
    this.showTypedToast('warning', text, options, direction);
  }


  /**
   * Success Toast for successfully executing a task
   *
   * @param text your text content
   * @param options get following parameters {headerName: 'your header name', icon : 'fas fa-cube', classname: class for the toast }
   * @param direction position of your toast
   */
  public success(text: string, options: ToastOptions = {}, direction?: string) {
    this.showTypedToast('success', text, options, direction);
  }

  /**
   * Info Toast for displaying information
   *
   * @param text your text content
   * @param options get following parameters {headerName: 'your header name', icon : 'fas fa-cube', classname: class for the toast }
   * @param direction position of your toast
   */
  public info(text: string, options: ToastOptions = {}, direction?: string) {
    this.showTypedToast('info', text, options, direction);
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

  private showTypedToast(type: NotificationType, text: string, options: ToastOptions, direction?: string): void {
    const config = ToastService.TYPE_CONFIG[type];
    const normalizedOptions: ToastOptions = {
      headerName: config.headerName,
      icon: config.icon,
      ...options
    };

    normalizedOptions.classname = `${normalizedOptions.classname ?? ''} ${config.borderClass}`.trim();
    normalizedOptions.iconClass = config.iconClass;

    this.showToast(text, normalizedOptions, direction, type);
  }

}
