import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

/** Formatters for ticks/value badges. */
type TickFormatter = (value: number, index: number, totalTicks: number) => string;

/** Traffic-light zone keys and a simple tuple for gradient pairs. */
type ZoneKey = 'ok' | 'warn' | 'bad';
type ColorPair = readonly [string, string];

@Component({
    selector: 'app-usage-bar',
    templateUrl: './app-usage-bar.component.html',
    styleUrls: ['./app-usage-bar.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
})
export class AppUsageBarComponent {
    /* ===================== Range & Value ===================== */
    @Input() min = 0;
    @Input() max = 100;
    @Input() value = 0;

    /* ======================== Visuals ======================== */
    @Input() height = 12;                 // bar height in px
    @Input() rounded = true;
    @Input() ariaLabel = 'usage progress';

    /** Zones as fractions of the range (0..1). */
    @Input() zones: Readonly<Record<'ok' | 'warn', number>> = { ok: 0.50, warn: 0.90 };

    /** Traffic-light gradient colors (tuples are important). */
    @Input() palette: Readonly<Record<ZoneKey, ColorPair>> = {
        ok: ['#16a34a', '#22c55e'],
        warn: ['#f59e0b', '#fbbf24'],
        bad: ['#ef4444', '#f87171']
    };

    /* ====================== Ticks & Labels ====================== */
    @Input() showTicks = true;
    /** Number of segments; total tick marks = tickCount + 1 */
    @Input() tickCount = 10;
    /** Hide the last grid label to avoid crowding; use pinned edge label instead. */
    @Input() showLastTickLabel = false;
    /** Optional dotted guides under each tick. */
    @Input() showTickGuides = false;
    /** Optional unit (not rendered by default; you can include in your formatter). */
    @Input() unit = '';
    /** Custom tick formatter; */
    @Input() tickFormatter?: TickFormatter;

    /* ===================== Value Badge ===================== */
    @Input() showValueBadge = true;
    @Input() valueFormatter: TickFormatter = (v) =>
        Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(v % 1000 ? 1 : 0)}K` : `${v}`;

    /** Color of the pinned max label at the far right (limit). */
    @Input() maxLabelColor = '#ef4444';

    
    /* ======================= Computed ======================= */
    /** 0..100 percent of value inside [min,max], clamped. */
    get percent(): number {
        const range = Math.max(this.max - this.min, 0);
        if (!range) return 0;
        const clamped = Math.min(Math.max(this.value, this.min), this.max);
        return ((clamped - this.min) / range) * 100;
    }


    /** Current traffic-light zone by percent. */
    get zone(): ZoneKey {
        const ratio = this.percent / 100;
        if (ratio <= this.zones.ok) return 'ok';
        if (ratio <= this.zones.warn) return 'warn';
        return 'bad';
    }


    /** Gradient colors for the active zone. */
    private get barColors(): ColorPair {
        return this.palette[this.zone];
    }


    /** Inline styles for the progress fill. */
    get progressStyle() {
        const radius = this.rounded ? '999px' : '0';
        const [start, end] = this.barColors;
        return {
            width: `${this.percent}%`,
            height: `${this.height}px`,
            borderRadius: radius,
            background: `linear-gradient(90deg, ${start}, ${end})`
        } as const;
    }


    /** Inline styles for the track. */
    get trackStyle() {
        const radius = this.rounded ? '999px' : '0';
        return { height: `${this.height}px`, borderRadius: radius } as const;
    }


    /** CSS variables used by the template/SCSS (badge position & colors). */
    get badgeVars() {
        const [badgeBg] = this.barColors;
        return {
            '--p': `${this.percent}%`,
            '--badge-bg': badgeBg,
            '--max-label-color': this.maxLabelColor
        } as Record<string, string>;
    }


    /** Grid columns for ticks. */
    get ticksGridStyle() {
        return { 'grid-template-columns': `repeat(${this.tickCount + 1}, 1fr)` };
    }


    /** Tick model for the template. */
    get ticks() {
        const count = Math.max(this.tickCount, 1);
        const totalTicks = count + 1;
        const step = (this.max - this.min) / count;

        const format: TickFormatter =
            this.tickFormatter ??
            ((val) => {
                if (Math.abs(val) >= 1000) {
                    const k = val / 1000;
                    return Number.isInteger(k) ? `${k}K` : `${k.toFixed(1)}K`;
                }
                return `${val}`;
            });

        return Array.from({ length: totalTicks }, (_, i) => {
            const v = Math.round((this.min + step * i) * 100) / 100;
            return { value: v, label: format(v, i, totalTicks) };
        });
    }


    /** Pinned label for the dynamic max */
    get maxLabel(): string {
        const f = this.tickFormatter ?? this.valueFormatter;
        return f(this.max, this.tickCount, this.tickCount + 1);
    }
}
