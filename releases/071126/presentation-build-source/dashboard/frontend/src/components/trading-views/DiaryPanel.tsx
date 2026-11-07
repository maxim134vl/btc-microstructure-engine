import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "../../i18n";
import { pnlTone, pct, signedPct, signedUsd } from "./format";
import { dayResultMap, type DayResult } from "./ledger";

import { ViewFrame } from "./ViewFrame";

const WEEKDAY_IDS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

function monthCells(year: number, monthIndex: number): Array<number | null> {
  const first = new Date(Date.UTC(year, monthIndex, 1));
  const lead = (first.getUTCDay() + 6) % 7;
  const count = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
  const cells: Array<number | null> = [];
  for (let i = 0; i < lead; i += 1) cells.push(null);
  for (let day = 1; day <= count; day += 1) cells.push(day);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

function dateKey(year: number, monthIndex: number, day: number): string {
  const month = String(monthIndex + 1).padStart(2, "0");
  const dd = String(day).padStart(2, "0");
  return `${year}-${month}-${dd}`;
}

function shiftMonth(year: number, monthIndex: number, delta: number): { year: number; monthIndex: number } {
  const next = new Date(Date.UTC(year, monthIndex + delta, 1));
  return { year: next.getUTCFullYear(), monthIndex: next.getUTCMonth() };
}

function daySurface(day: DayResult | undefined, selected: boolean): string {
  const ring = selected ? "diary-day-selected" : "ring-1 ring-ds-border/40";
  if (!day) return `bg-ds-surface ${ring}`;
  if (day.success) return `diary-day-success ${ring}`;
  return `diary-day-failure ${ring}`;
}

function monthFromIso(iso: string | null): { year: number; monthIndex: number } | null {
  if (!iso) return null;
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  return { year: date.getUTCFullYear(), monthIndex: date.getUTCMonth() };
}

function currentUtcMonth(): { year: number; monthIndex: number } {
  const now = new Date();
  return { year: now.getUTCFullYear(), monthIndex: now.getUTCMonth() };
}

export function DiaryPanel({ fillWindow = false }: { fillWindow?: boolean }) {
  const { t, locale } = useTranslation();

  const days: DayResult[] = []; // Native per-day owner publication is not available.
  const byDate = useMemo(() => dayResultMap(days), [days]);
  const latestDate = days[days.length - 1]?.date ?? null;
  const [cursor, setCursor] = useState(currentUtcMonth);
  const [monthPinned, setMonthPinned] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    if (monthPinned || !latestDate) return;
    const month = monthFromIso(latestDate);
    if (month) setCursor(month);
  }, [latestDate, monthPinned]);
  const activeDate = selected ?? latestDate;

  const cells = monthCells(cursor.year, cursor.monthIndex);
  const monthLabel = new Date(Date.UTC(cursor.year, cursor.monthIndex, 1)).toLocaleDateString(locale === "ru" ? "ru-RU" : "en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  const selectedDay = activeDate ? byDate.get(activeDate) : undefined;
  const weekdays = WEEKDAY_IDS.map((id) => t(`tradingViews.diary.weekdays.${id}`));

  return (
    <ViewFrame fillWindow={fillWindow}>
      <p className="px-0.5 text-[12px] text-ds-text-secondary">{t("tradingViews.unavailable")}</p>
      <section className="grid gap-3.5 xl:grid-cols-[minmax(0,1fr)_280px]" data-section="diary-calendar">
        <article className="ops-card p-3.5 sm:p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="font-ds-display text-[18px] font-semibold capitalize text-ds-text-primary">{monthLabel}</h2>
            <div className="theme-selector inline-flex rounded-ds-input border border-ds-border bg-ds-surface-secondary p-0.5">
              <button
                type="button"
                className="theme-selector-btn rounded-ds-input px-2.5 py-1 text-[12px] font-medium"
                onClick={() => {
                  setMonthPinned(true);
                  setCursor((current) => shiftMonth(current.year, current.monthIndex, -1));
                }}
                aria-label={t("tradingViews.diary.previousMonth")}
              >
                ‹
              </button>
              <button
                type="button"
                className="theme-selector-btn rounded-ds-input px-2.5 py-1 text-[12px] font-medium"
                onClick={() => {
                  setMonthPinned(true);
                  setCursor((current) => shiftMonth(current.year, current.monthIndex, 1));
                }}
                aria-label={t("tradingViews.diary.nextMonth")}
              >
                ›
              </button>
            </div>
          </div>
          <div className="mb-3 flex flex-wrap gap-3 text-[11px] text-ds-text-secondary">
            <Legend swatch="diary-day-success" label={t("tradingViews.diary.success")} />
            <Legend swatch="diary-day-failure" label={t("tradingViews.diary.failure")} />
            <Legend swatch="bg-ds-surface ring-1 ring-ds-border/50" label={t("tradingViews.diary.noTrades")} />
          </div>
          <div className="grid grid-cols-7 gap-1.5">
            {weekdays.map((label) => (
              <div key={label} className="px-1 py-1 text-center text-[11px] font-semibold uppercase tracking-[0.06em] text-ds-text-tertiary">
                {label}
              </div>
            ))}
            {cells.map((day, index) => {
              if (day == null) return <div key={`empty-${index}`} />;
              const key = dateKey(cursor.year, cursor.monthIndex, day);
              const result = byDate.get(key);
              const active = activeDate === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setSelected(key)}
                  className={`flex min-h-[92px] flex-col rounded-[12px] px-1.5 py-1.5 text-left transition-shadow ${daySurface(result, active)}`}
                >
                  <span className="text-[12px] font-semibold tabular-nums text-ds-text-primary">{day}</span>
                  {result ? (
                    <span className="mt-auto space-y-0.5">
                      <span className="block text-[11px] font-medium tabular-nums text-ds-text-secondary">
                        {pct(result.winRate * 100)}
                      </span>
                      <span className="block text-[11px] font-semibold tabular-nums" style={{ color: pnlTone(result.pnlUsd) }}>
                        {signedUsd(result.pnlUsd)}
                      </span>
                      <span className="block text-[10px] tabular-nums" style={{ color: pnlTone(result.returnPct) }}>
                        {result.returnPct == null ? "—" : signedPct(result.returnPct)}
                      </span>
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        </article>

        <article className="ops-card h-fit p-3.5 sm:p-4">
          <p className="text-[11px] uppercase tracking-[0.06em] text-ds-text-tertiary">{activeDate ?? "—"}</p>
          {selectedDay ? (
            <div className="mt-3 space-y-3">
              <p
                className="font-ds-display text-[28px] font-semibold tabular-nums"
                style={{ color: pnlTone(selectedDay.pnlUsd) }}
              >
                {signedUsd(selectedDay.pnlUsd)}
              </p>
              <Detail
                label={t("tradingViews.diary.returnPct")}
                value={selectedDay.returnPct == null ? "—" : signedPct(selectedDay.returnPct)}
                tone={pnlTone(selectedDay.returnPct)}
              />
              <Detail label={t("tradingViews.diary.winRate")} value={pct(selectedDay.winRate * 100)} />
              <Detail label={t("tradingViews.diary.trades")} value={`${selectedDay.wins}/${selectedDay.trades}`} />
              <p className="text-[13px] font-medium" style={{ color: selectedDay.success ? "var(--ds-status-healthy)" : "var(--ds-status-error)" }}>
                {selectedDay.success ? t("tradingViews.diary.success") : t("tradingViews.diary.failure")}
              </p>
            </div>
          ) : (
            <p className="mt-3 text-[13px] text-ds-text-secondary">
              {activeDate ? t("tradingViews.diary.idleDay") : t("tradingViews.diary.selectedEmpty")}
            </p>
          )}
        </article>
      </section>
    </ViewFrame>
  );
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block h-2.5 w-2.5 rounded-[3px] ${swatch}`} />
      {label}
    </span>
  );
}

function Detail({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-[13px]">
      <span className="text-ds-text-secondary">{label}</span>
      <span className="font-medium tabular-nums text-ds-text-primary" style={tone ? { color: tone } : undefined}>
        {value}
      </span>
    </div>
  );
}
