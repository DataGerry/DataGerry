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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import { Injectable } from '@angular/core';
import { NgbModal, NgbModalOptions, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';

@Injectable({ providedIn: 'root' })
export class FullscreenModalService {

  open(modalService: NgbModal, content: any, options: NgbModalOptions = {}): NgbModalRef {
    return modalService.open(content, this.withFullscreenContainer(options));
  }

  withFullscreenContainer(options: NgbModalOptions = {}): NgbModalOptions {
    const fullscreenContainer = this.getFullscreenContainer();
    return fullscreenContainer
      ? { ...options, container: fullscreenContainer }
      : options;
  }

  private getFullscreenContainer(): HTMLElement | undefined {
    return document.fullscreenElement instanceof HTMLElement
      ? document.fullscreenElement
      : undefined;
  }
}