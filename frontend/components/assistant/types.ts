// Shared types for the assistant surfaces (/chat, /agent, /assistant).

export interface SourceItem {
  text: string
  rating: number | string
  sentiment: string
  score: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content?: string
  sources?: SourceItem[]
  recommendation?: Recommendation
  error?: string
}

export type EvidenceItem = { tool: string; snippet: string; relevance: number }

export type Recommendation = {
  decision: 'go' | 'no_go' | 'needs_more_data'
  confidence: number
  summary: string
  reasoning_steps: string[]
  evidence: EvidenceItem[]
  risks: string[]
  suggested_next_actions: string[]
}

export type TraceStep =
  | { kind: 'node_started'; node: string; label: string; ts: number }
  | { kind: 'plan_ready'; query_type: string; plan: string[]; ts: number }
  | { kind: 'tool_call'; tool: string; args: Record<string, unknown>; ts: number }
  | { kind: 'tool_result'; tool: string; preview: string; ts: number }
  | { kind: 'executor_thought'; content: string; ts: number }
  | { kind: 'replan'; reason: string; ts: number }
  | { kind: 'error'; message: string; ts: number }
  | { kind: 'done'; ts: number }
