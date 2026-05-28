import type { CognitionFlowStep } from "../../types/visualCognition";

export function CognitionFlowPanel({ steps, interpretation }: { steps: CognitionFlowStep[]; interpretation?: string | null }) {
  return (
    <section className="rounded border border-slate-800 bg-slate-950 p-3">
      <h2 className="text-xs font-semibold tracking-wide text-cyan-300">STAGE 1 COGNITION FLOW</h2>
      <p className="mt-1 text-[10px] text-slate-500">Behavioral interpretation chain — not verdict labels</p>
      {interpretation ? <p className="mt-2 text-[11px] text-slate-300">{interpretation}</p> : null}
      <ol className="mt-3 space-y-2">
        {steps.map((step, index) => (
          <li key={`${step.step}-${step.label}`} className="relative pl-4">
            {index < steps.length - 1 ? (
              <span className="absolute left-[5px] top-4 h-[calc(100%+4px)] w-px bg-slate-700" aria-hidden />
            ) : null}
            <span className="absolute left-0 top-1 h-2.5 w-2.5 rounded-full border border-cyan-500 bg-slate-950" />
            <div className="text-[11px] font-semibold text-slate-200">{step.label}</div>
            <div className="text-[10px] text-slate-500">{step.detail}</div>
            {step.timeframe ? <div className="text-[9px] font-mono text-slate-600">{step.timeframe}</div> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
