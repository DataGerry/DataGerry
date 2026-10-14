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

import { AsyncPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize } from 'rxjs/operators';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { environment } from 'src/environments/environment';
import { CoreModule } from '../../core/core.module';
import { LoaderService } from '../../core/services/loader.service';
import { ConnectionService } from '../../modules/connect/services/connection.service';
/* ------------------------------------------------------------------------------------------------------------------ */

type Edition = 'community' | 'subscription';

interface EditionOption {
    id: Edition;
    icon: string;
    title: string;
    description: string;
    features: string[];
    badge: string;
}

interface OnboardingStep {
    id: string;
    title: string;
    description: string;
}

@Component({
    selector: 'cmdb-onboarding-assistant',
    templateUrl: './onboarding-assistant.component.html',
    styleUrls: ['./onboarding-assistant.component.scss'],
    imports: [AsyncPipe, CoreModule],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class OnboardingAssistantComponent implements OnInit {
    private readonly connectionService = inject(ConnectionService);
    private readonly loaderService = inject(LoaderService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly activeModal = inject(NgbActiveModal);
    public readonly isLoading$ = this.loaderService.isLoading$;

    /** Set to false by the opener when the data model already exists. */
    public readonly isUsable = signal(true);

    public readonly isCloud = environment.cloudMode;
    public readonly version = signal('');
    public readonly currentStepIndex = signal(0);

    public readonly steps = computed<OnboardingStep[]>(() => [
        {
            id: 'welcome',
            title: 'Welcome',
            description: this.isCloud ? 'DATAGERRY Cloud' : 'Self-hosted'
        },
        this.isCloud
            ? { id: 'plan', title: 'Your plan', description: 'Trial or subscription' }
            : { id: 'edition', title: 'Edition', description: 'Community or Subscription' }
    ]);

    public readonly currentStep = computed(() => this.steps()[this.currentStepIndex()]);
    public readonly progressPercent = computed(() => ((this.currentStepIndex() + 1) / this.steps().length) * 100);
    public readonly selectedEdition = signal<Edition | null>(null);

    public readonly canGoNext = computed(() =>
        this.currentStep().id !== 'edition' || this.selectedEdition() !== null
    );

    public readonly editionOptions: EditionOption[] = [
        {
            id: 'community',
            icon: 'fas fa-heart',
            title: 'Community',
            description: 'Free and open source under AGPL.',
            features: ['Types, categories, objects', 'Import and export', 'User and permission management', 'Community support'],
            badge: 'Free'
        },
        {
            id: 'subscription',
            icon: 'fas fa-key',
            title: 'Subscription',
            description: 'License with Pro features and vendor support.',
            features: ['Everything in Community', 'REST API, IPAM, Document Generator', 'Automations, ISMS depending on plan', 'Support by becon'],
            badge: 'Core · Business · Corporate'
        }
    ];

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        if (this.isUsable()) {
            this.loadVersion();
        }
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onNext(): void {
        if (!this.canGoNext()) {
            return;
        }

        // Later steps run in the opener's data model flow.
        if (this.currentStepIndex() === this.steps().length - 1) {
            this.activeModal.close(true);
            return;
        }

        this.currentStepIndex.update(index => index + 1);
    }


    public onSecondaryAction(): void {
        if (this.currentStepIndex() === 0) {
            this.onSetUpLater();
            return;
        }

        this.currentStepIndex.update(index => index - 1);
    }


    public onEditionSelected(edition: Edition): void {
        this.selectedEdition.set(edition);
    }


    public onSetUpLater(): void {
        this.activeModal.dismiss(false);
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private loadVersion(): void {
        this.loaderService.show();

        this.connectionService.getBackendInfo().pipe(
            takeUntilDestroyed(this.destroyRef),
            finalize(() => this.loaderService.hide())
        ).subscribe({
            next: info => this.version.set(info?.version ?? ''),
            error: () => this.version.set('')
        });
    }
}
