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

import { Directive, EventEmitter, HostListener, Output } from '@angular/core';
import { InfiniteScrollService } from '../../../services/infinite-scroll.service';

enum SortType {
  TYPE = 'metadata.mime_type',
  SIZE = 'length',
  AUTHOR = 'metadata.author_id',
  DATE = 'uploadDate',
  FILENAME = 'filename'
}

@Directive({
    selector: '[tableSortEvent]',
    standalone: false
})
export class TableSortEventDirective {

  constructor( private scrollService: InfiniteScrollService) {
  }

  @Output() valueChanged = new EventEmitter<any>();

  public htmlElement: HTMLElement;
  private readonly tag: string = 'viewScroll';

  @HostListener('click', ['$event'])
  sortDirectionHandler(event: MouseEvent) {
    document.getElementById('file-view-list').scrollTop = 0;
    this.htmlElement = (event.target as HTMLElement);
    if (this.htmlElement.getAttribute('scope')) {
      this.removeActiveClass();
      this.setSortDirection();
    }
  }


  private removeActiveClass(): void {
    const children = this.htmlElement.parentNode.children;
    let count = children.length;
    while (count--) { children[count].classList.remove('active'); }
  }

  private setSortDirection(): void {
    if (this.htmlElement.classList.contains('_desc')) {
      this.htmlElement.classList.remove('_desc');
      this.htmlElement.classList.add('_asc');
    } else {
      this.htmlElement.classList.remove('_asc');
      this.htmlElement.classList.add('_desc');
    }
    this.htmlElement.classList.add('active');
    this.reloadApiParameters();
  }

  private reloadApiParameters() {
    this.scrollService.setCollectionParameters(
      1,
      100,
      (SortType)[this.htmlElement.innerText.toUpperCase()],
      this.htmlElement.classList.contains('_desc') ? -1 : 1,
      this.tag);
    this.valueChanged.emit(this.scrollService.getCollectionParameters(this.tag));
  }
}
