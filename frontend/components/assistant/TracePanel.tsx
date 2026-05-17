'use client'
import { useEffect, useRef } from 'react'
import {
  Sparkles,
  Wrench,
  CheckCircle2,
  Loader2,
  AlertCircle,
  ListChecks,
  RotateCw,
  ChevronDown,
} from 'lucide-react'
import type { TraceStep } from './types'
import { toolMeta } from './style-helpers'

function TraceRow({ step, inFlight }: { step: TraceStep; inFlight: boolean }) {
  switch (step.kind) {
    case 'node_started':
      return (
        <div className="flex items-start gap-2 py-1.5 animate-in fade-in slide-in-from-left-2 duration-300">
          {inFlight ? (
            <Loader2 className="w-3.5 h-3.5 mt-0.5 text-blue-400 animate-spin shrink-0" />
          ) : (
            <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 text-emerald-400 shrink-0" />
          )}
          <div className="text-xs">
            <span className="text-foreground font-medium">{step.node}</span>
            <span className="text-muted-foreground ml-2">{step.label}</span>
          </div>
        </div>
      )
    case 'plan_ready':
      return (
        <div className="flex items-start gap-2 py-1.5 animate-in fade-in slide-in-from-left-2 duration-300">
          <ListChecks className="w-3.5 h-3.5 mt-0.5 text-purple-400 shrink-0" />
          <div className="text-xs space-y-0.5 min-w-0">
            <div className="text-muted-foreground">Plan ({step.query_type}):</div>
            <div className="flex flex-wrap gap-1">
              {step.plan.map((t, i) => {
                const meta = toolMeta(t)
                return (
                  <code
                    key={i}
                    className={`text-[10px] bg-background-secondary px-1.5 py-0.5 rounded font-mono border ${meta.bgClass} ${meta.colorClass}`}
                  >
                    {t}
                  </code>
                )
              })}
            </div>
          </div>
        </div>
      )
    case 'tool_call': {
      const meta = toolMeta(step.tool)
      const Icon = meta.icon
      return (
        <div className="flex items-start gap-2 py-1.5 animate-in fade-in slide-in-from-left-2 duration-300">
          <div
            className={`w-5 h-5 rounded border flex items-center justify-center shrink-0 mt-0 ${meta.bgClass}`}
          >
            <Icon className={`w-3 h-3 ${meta.colorClass}`} />
          </div>
          <div className="text-xs text-foreground flex-1 min-w-0">
            calling <code className={`font-mono ${meta.colorClass}`}>{step.tool}</code>
            {step.args && Object.keys(step.args).length > 0 && (
              <span className="text-muted-foreground ml-1 break-words">
                ({JSON.stringify(step.args).slice(0, 80)})
              </span>
            )}
          </div>
        </div>
      )
    }
    case 'tool_result': {
      const meta = toolMeta(step.tool)
      return (
        <details className="py-1.5 group animate-in fade-in slide-in-from-left-2 duration-300">
          <summary className="flex items-start gap-2 cursor-pointer list-none select-none">
            <div
              className={`w-5 h-5 rounded border flex items-center justify-center shrink-0 mt-0 ${meta.bgClass}`}
            >
              <CheckCircle2 className={`w-3 h-3 ${meta.colorClass}`} />
            </div>
            <div className="text-xs text-muted-foreground flex-1 min-w-0">
              <span className="text-foreground font-medium">{step.tool}</span> returned
              <ChevronDown className="w-3 h-3 inline ml-1 transition group-open:rotate-180" />
            </div>
          </summary>
          <div className="text-[11px] text-muted-foreground mt-1 ml-7 break-words whitespace-pre-wrap font-mono bg-background-secondary p-2 rounded border border-border">
            {step.preview}
          </div>
        </details>
      )
    }
    case 'executor_thought':
      return (
        <div className="flex items-start gap-2 py-1.5 pl-7 animate-in fade-in slide-in-from-left-2 duration-300">
          <div className="text-xs text-muted-foreground italic">{step.content}</div>
        </div>
      )
    case 'replan':
      return (
        <div className="flex items-start gap-2 py-1.5 animate-in fade-in slide-in-from-left-2 duration-300">
          <RotateCw className="w-3.5 h-3.5 mt-0.5 text-amber-400 shrink-0" />
          <div className="text-xs text-amber-300">Re-plan: {step.reason}</div>
        </div>
      )
    case 'error':
      return (
        <div className="flex items-start gap-2 py-1.5 animate-in fade-in slide-in-from-left-2 duration-300">
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 text-rose-400 shrink-0" />
          <div className="text-xs text-rose-300 break-all">{step.message}</div>
        </div>
      )
    case 'done':
      return (
        <div className="flex items-start gap-2 py-1.5 animate-in fade-in slide-in-from-left-2 duration-300">
          <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 text-emerald-400 shrink-0" />
          <div className="text-xs text-emerald-300 font-medium">Done</div>
        </div>
      )
  }
}

function TracePreview() {
  return (
    <div className="space-y-3 opacity-50">
      <div className="flex items-start gap-2">
        <ListChecks className="w-3.5 h-3.5 mt-0.5 text-purple-400 shrink-0" />
        <div className="text-xs">
          <span className="text-foreground font-medium">Planner</span>
          <span className="text-muted-foreground ml-2">picks the research tools</span>
        </div>
      </div>
      <div className="flex items-start gap-2">
        <Wrench className="w-3.5 h-3.5 mt-0.5 text-blue-400 shrink-0" />
        <div className="text-xs">
          <span className="text-foreground font-medium">Executor</span>
          <span className="text-muted-foreground ml-2">runs the tools</span>
        </div>
      </div>
      <div className="flex items-start gap-2">
        <Sparkles className="w-3.5 h-3.5 mt-0.5 text-emerald-400 shrink-0" />
        <div className="text-xs">
          <span className="text-foreground font-medium">Synthesizer</span>
          <span className="text-muted-foreground ml-2">writes the recommendation</span>
        </div>
      </div>
      <div className="pt-2 text-[10px] text-muted-foreground italic">
        Each step streams in live as the agent runs.
      </div>
    </div>
  )
}

export function TracePanel({
  steps,
  isStreaming,
  hideHeader = false,
}: {
  steps: TraceStep[]
  isStreaming: boolean
  // Mobile uses an outer <details> summary as the header, so this lets the
  // panel render headerless inside it without duplicating the title row.
  hideHeader?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' })
  }, [steps.length])

  const lastIdx = steps.length - 1
  const elapsedMs =
    steps.length >= 2 ? steps[steps.length - 1].ts - steps[0].ts : 0
  const elapsedSec = (elapsedMs / 1000).toFixed(1)

  return (
    <div className={`flex flex-col min-h-0 h-full ${hideHeader ? '' : 'bg-card border border-border rounded-xl'}`}>
      {!hideHeader && (
        <div className="px-4 py-3 border-b border-border flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-purple-400" />
          <span className="text-sm font-medium text-foreground">Agent trace</span>
          {steps.length > 0 && (
            <span className="text-xs text-muted-foreground ml-auto">{steps.length} events</span>
          )}
        </div>
      )}
      <div ref={ref} className="flex-1 min-h-0 overflow-y-auto px-4 py-3">
        {steps.length === 0 ? (
          <TracePreview />
        ) : (
          <div className="divide-y divide-border/40">
            {steps.map((s, i) => (
              <div key={i} id={`trace-row-${i}`} className="transition rounded">
                <TraceRow step={s} inFlight={isStreaming && i === lastIdx} />
              </div>
            ))}
          </div>
        )}
      </div>
      {steps.length > 0 && (
        <div className="px-4 py-2 border-t border-border text-[10px] text-muted-foreground flex items-center justify-between font-mono">
          <span>{steps.length} events</span>
          <span>{elapsedSec}s elapsed</span>
        </div>
      )}
    </div>
  )
}
