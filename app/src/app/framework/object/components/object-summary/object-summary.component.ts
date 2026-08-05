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

import { Component, inject, Input } from "@angular/core";
import { ToastService } from "../../../../layout/toast/toast.service";
import { RenderResult } from "../../../models/cmdb-render";
import { CmdbMode } from "../../../modes.enum";
import { DateSettingsService } from "src/app/settings/services/date-settings.service";
import { DateFormatterPipe } from "src/app/layout/pipes/date-formatter.pipe";

@Component({
    selector: "cmdb-object-summary",
    templateUrl: "./object-summary.component.html",
    styleUrls: ["./object-summary.component.scss"],
    standalone: false
})
export class ObjectSummaryComponent {
    @Input() summaries: any = [];
    @Input() renderResult: RenderResult;
    public mode: CmdbMode = CmdbMode.Simple;

    private readonly toast = inject(ToastService);
    private readonly dateSettingsService = inject(DateSettingsService);
    private readonly dateFormatterPipe = inject(DateFormatterPipe);

    /**
     * Retrieves the label corresponding to a given value from the options array.
     */
    getLabelForValue(value: string, data: any): string {
        // Locate the option within the options array where the 'name' property corresponds to the provided value.
        const matchingOption = data.options.find(option => option.name === value);


        //If a corresponding option is discovered, retrieve its label; otherwise, provide an empty string.
        return matchingOption.label ? matchingOption.label : '';
    }


    public async clipBoardSummary(data: any, value: string) {


        const selBox = document.createElement("textarea");
        selBox.style.position = "fixed";
        selBox.style.left = "0";
        selBox.style.top = "0";
        selBox.style.opacity = "0";
        selBox.value = data.options ? this.getLabelForValue(value, data) : value;
        document.body.appendChild(selBox);
        selBox.focus();
        selBox.select();
        try {
            await navigator.clipboard.writeText(selBox.value);
            this.toast.info("Summary was copied to clipboard");
        } catch (err) {
            this.toast.error('Unable to copy to clipboard')
        } finally {
            document.body.removeChild(selBox);
        }
    }


    formatDate(date: any): string {
        return this.dateFormatterPipe.transform(date);
    }

    clipBoardFormattedSummary(value: any) {
        const formattedValue = this.formatDate(value);
        this.clipBoardSummary('date', formattedValue);
    }
}
