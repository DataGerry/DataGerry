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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, EventEmitter, Input, Output } from '@angular/core';

import { LinkService } from '../../../../services/link.service';

import { CmdbLink } from '../../../../models/cmdb-link';
import { AccessControlList } from 'src/app/modules/acl/acl.types';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-object-links-table-action-cell',
    templateUrl: './object-links-table-action-cell.component.html',
    styleUrls: ['./object-links-table-action-cell.component.scss'],
    standalone: false
})
export class ObjectLinksTableActionCellComponent {

    public link: CmdbLink;

    @Input() public objectID: number;
    @Input() public acl: AccessControlList;

    public partnerLinkID: number;

    @Input('link')
    public set Link(link: CmdbLink) {
        this.link = link;
        this.partnerLinkID = this.linkService.getPartnerID(this.objectID, link);
    }

    @Output() deleteEmitter: EventEmitter<CmdbLink> = new EventEmitter();

    constructor(private linkService: LinkService) {

    }
}