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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, OnDestroy, OnInit, Renderer2 } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { ConnectionService } from './services/connection.service';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    templateUrl: './connect.component.html',
    styleUrls: ['./connect.component.scss'],
    standalone: false
})
export class ConnectComponent implements OnInit, OnDestroy {

    public connectionTest: boolean = false;
    public connectionResponse;
    public connectionForm: UntypedFormGroup;
    private connectionValues;

    private readonly defaultHost: string = '127.0.0.1';
    private readonly defaultPort: number = 4000;
    private readonly defaultProtocol: string = 'http';

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(private domRender: Renderer2, private connService: ConnectionService, private router: Router) {
        this.connectionForm = new UntypedFormGroup({
            host: new UntypedFormControl(this.defaultHost, Validators.required),
            port: new UntypedFormControl(this.defaultPort, Validators.required),
            protocol: new UntypedFormControl(this.defaultProtocol)
        });
    }


    public ngOnInit(): void {
        this.domRender.addClass(document.body, 'embedded');
    }


    public ngOnDestroy(): void {
        this.domRender?.removeClass(document?.body, 'embedded');
    }

    /* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    public async checkConnection() {
        const formData = this.connectionForm.getRawValue();

        try {
            this.connectionResponse = await this.connService.testCustomURL(
                formData.protocol, formData.host, formData.port
            );
            this.connectionTest = true;
            this.connectionValues = formData;
        } catch (e) {
            this.connectionTest = false;
        }
    }


    public useConnection() {
        this.connService.setConnectionURL(this.connectionValues.protocol, this.connectionValues.host, this.connectionValues.port);
        this.router.navigate(['/']).then(() => {
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        });
    }
}