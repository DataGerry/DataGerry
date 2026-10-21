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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    ElementRef,
    Injector,
    afterNextRender,
    computed,
    effect,
    inject,
    signal,
    viewChild
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl } from '@angular/forms';

import { RackOverviewStore } from '../../services/rack-overview-store.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** How much of the notes the folded header carries: enough to read the gist, not the whole note. */
const PREVIEW_LENGTH = 100;

/** How far back a cut may reach for a word break before it is not worth it. */
const PREVIEW_WORD_BREAK = 0.6;


/**
 * The notes card of the side column. The notes belong to the rack object, not to the rack's contents,
 * so the card only ever reads and writes that one field.
 *
 * A disclosure rather than a panel that is always open: the column belongs to the rows in the rack,
 * and the notes are a reference beside them. Folded, the header still carries a line of them, so
 * there is no need to open the card to find out whether it holds anything.
 */
@Component({
    selector: 'cmdb-rack-notes',
    templateUrl: './rack-notes.component.html',
    styleUrls: ['./rack-notes.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        'class': 'rack-notes',
        '[hidden]': 'isHidden()'
    },
    standalone: false
})
export class RackNotesComponent {

    public readonly store = inject(RackOverviewStore);

    private readonly injector = inject(Injector);
    private readonly destroyRef = inject(DestroyRef);

    private readonly editor = viewChild<ElementRef<HTMLTextAreaElement>>('editor');
    private readonly toggle = viewChild.required<ElementRef<HTMLButtonElement>>('toggle');

    public readonly isExpanded = signal(false);
    public readonly isEditing = signal(false);

    /** Holds what is being typed. Only what is stored is read back from the rack. */
    public readonly draft = new FormControl<string>('', { nonNullable: true });

    public readonly notes = computed(() => this.store.notes().trim());

    public readonly hasNotes = computed(() => this.notes().length > 0);

    /** Nothing to read and no right to write: the column keeps the space for the drawing. */
    public readonly isHidden = computed(() => !this.hasNotes() && !this.store.canEditNotes);

    /** The opening of the notes for the folded header, with the line breaks flattened out. */
    public readonly preview = computed(() => {
        const singleLine = this.notes().replace(/\s+/g, ' ');

        if (singleLine.length <= PREVIEW_LENGTH) {
            return singleLine;
        }

        const cut = singleLine.slice(0, PREVIEW_LENGTH);
        const lastSpace = cut.lastIndexOf(' ');
        // Back to the last whole word, unless there is none in reach and the cut has to fall mid-word.
        const trimmed = lastSpace > PREVIEW_LENGTH * PREVIEW_WORD_BREAK ? cut.slice(0, lastSpace) : cut;

        return `${ trimmed.trimEnd() }…`;
    });

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        // Another rack is another note: nothing opened or half-typed here may follow the view over.
        effect(() => {
            this.store.rackId();

            this.isEditing.set(false);
            this.isExpanded.set(false);
        });
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onToggle(): void {
        this.isExpanded.update(expanded => !expanded);
    }


    public onEdit(): void {
        this.draft.setValue(this.notes());
        this.isExpanded.set(true);
        this.isEditing.set(true);

        this.focusAfterRender(() => this.editor()?.nativeElement);
    }


    public onCancel(): void {
        this.isEditing.set(false);
        this.focusAfterRender(() => this.toggle().nativeElement);
    }


    public onSave(): void {
        const notes = this.draft.value.trim();

        // Nothing was changed, so there is nothing to write - closing the editor is the whole of it.
        if (notes === this.notes()) {
            this.onCancel();

            return;
        }

        this.store.saveNotes(notes)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.onCancel());
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /**
     * Focus has to be moved by hand across the two modes: the control that was clicked is taken out
     * of the DOM by the very click, and focus would otherwise be dropped on the body.
     */
    private focusAfterRender(target: () => HTMLElement | undefined): void {
        afterNextRender(() => target()?.focus(), { injector: this.injector });
    }
}
