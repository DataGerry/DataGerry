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

import { Directive, ElementRef, Input, OnChanges, Renderer2, SimpleChanges } from '@angular/core';

@Directive({
    selector: '[rightLevelColor]',
    standalone: false
})
export class RightLevelColorDirective implements OnChanges {

  @Input() classPrefix: string = '';
  @Input() level: number = 0;

  private readonly levelColor = {
    100: 'danger',
    80: 'primary',
    50: 'secondary',
    30: 'info',
    10: 'dark',
    0: ''
  };

  public constructor(private renderer: Renderer2, private hostElement: ElementRef) {

  }

  public ngOnChanges(changes: SimpleChanges): void {
    const addClass = `${ this.classPrefix }${ this.levelColor[this.level] }`;
    if (addClass !== '') {
      this.renderer.addClass(this.hostElement.nativeElement, addClass);
    }
  }

}
