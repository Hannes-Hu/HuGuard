// All types mirror the backend Pydantic schemas exactly.
// When the backend schema changes, this file is the first place to update.

export type Severity = "critical" | "high" | "medium" | "low" | "info";

export type AgentNode = "scanner" | "patcher" | "critic" | "human_review" | "done";

export type AuditStatus =
  | "pending"
  | "running"
  | "awaiting_approval"
  | "approved"
  | "rejected"
  | "completed"
  | "failed";

export type ApprovalDecision = "approve" | "reject";

export type CriticVerdict = "approved" | "rejected";

// ── Domain objects ────────────────────────────────────────────────────────────

export interface SecurityFinding {
  id: string;
  title: string;
  description: string;
  severity: Severity;
  category: string;
  affected_lines: number[];
  cwe_id: string | null;
}

export interface ScannerOutput {
  findings: SecurityFinding[];
  summary: string;
  risk_score: number;
}

export interface UnifiedDiff {
  original_snippet: string;
  patched_snippet: string;
  unified_diff: string;
  affected_lines: number[];
}

export interface PatcherOutput {
  finding_id: string;
  rationale: string;
  diff: UnifiedDiff;
  is_breaking_change: boolean;
}

export interface CriticOutput {
  verdict: CriticVerdict;
  feedback: string;
  syntax_valid: boolean;
  potential_side_effects: string[];
}

// ── API responses ─────────────────────────────────────────────────────────────

export interface AuditStartResponse {
  thread_id: string;
  status: AuditStatus;
  message: string;
}

export interface AuditSummaryResponse {
  thread_id: string;
  status: AuditStatus;
  scanner_output: ScannerOutput | null;
  patcher_output: PatcherOutput | null;
  critic_output: CriticOutput | null;
  patch_retry_count: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApprovalRequest {
  decision: ApprovalDecision;
  comment?: string;
}

// ── SSE Events ────────────────────────────────────────────────────────────────

export type SSEEventType =
  | "node_start"
  | "node_complete"
  | "finding"
  | "patch_ready"
  | "critic_verdict"
  | "awaiting_human"
  | "retry"
  | "completed"
  | "error"
  | "heartbeat";

export interface SSEEventBase {
  event: SSEEventType;
  thread_id: string;
  node: AgentNode | null;
  timestamp: string;
}

export interface ScannerCompleteEvent extends SSEEventBase {
  event: "node_complete";
  node: "scanner";
  data: {
    findings: SecurityFinding[];
    summary: string;
    risk_score: number;
  };
}

export interface PatchReadyEvent extends SSEEventBase {
  event: "patch_ready";
  node: "patcher";
  data: {
    patch: UnifiedDiff;
    rationale: string;
    retry_count: number;
  };
}

export interface CriticVerdictEvent extends SSEEventBase {
  event: "critic_verdict";
  node: "critic";
  data: {
    verdict: CriticVerdict;
    feedback: string;
    syntax_valid: boolean;
  };
}

export interface AwaitingHumanEvent extends SSEEventBase {
  event: "awaiting_human";
  node: "human_review";
  data: { message: string };
}

export interface CompletedEvent extends SSEEventBase {
  event: "completed";
  data: { status: AuditStatus; error: string | null };
}

export interface ErrorEvent extends SSEEventBase {
  event: "error";
  data: { error: string };
}

export type AuditSSEEvent =
  | ScannerCompleteEvent
  | PatchReadyEvent
  | CriticVerdictEvent
  | AwaitingHumanEvent
  | CompletedEvent
  | ErrorEvent
  | SSEEventBase;

// ── UI state ──────────────────────────────────────────────────────────────────

export type NodeState = "idle" | "active" | "done" | "error" | "retrying" | "waiting";

export interface PipelineNodeStatus {
  node: AgentNode;
  state: NodeState;
  retryCount: number;
}
