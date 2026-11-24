"use client";

import { useCallback, useRef, useState } from "react";
import { api } from "@/lib/api";
import type {
  AgentNode,
  AuditStatus,
  AuditSSEEvent,
  CriticOutput,
  PatcherOutput,
  PipelineNodeStatus,
  ScannerOutput,
  SecurityFinding,
} from "@/types/audit";

export interface AuditStreamState {
  threadId: string | null;
  status: AuditStatus;
  pipelineNodes: PipelineNodeStatus[];
  findings: SecurityFinding[];
  scannerOutput: ScannerOutput | null;
  patcherOutput: PatcherOutput | null;
  criticOutput: CriticOutput | null;
  error: string | null;
  isStreaming: boolean;
}

const ORDERED_NODES: AgentNode[] = ["scanner", "patcher", "critic", "human_review"];

function initialPipeline(): PipelineNodeStatus[] {
  return ORDERED_NODES.map((node) => ({
    node,
    state: "idle",
    retryCount: 0,
  }));
}

function updateNode(
  nodes: PipelineNodeStatus[],
  target: AgentNode,
  patch: Partial<PipelineNodeStatus>,
): PipelineNodeStatus[] {
  return nodes.map((n) => (n.node === target ? { ...n, ...patch } : n));
}

export function useAuditStream() {
  const [state, setState] = useState<AuditStreamState>({
    threadId: null,
    status: "pending",
    pipelineNodes: initialPipeline(),
    findings: [],
    scannerOutput: null,
    patcherOutput: null,
    criticOutput: null,
    error: null,
    isStreaming: false,
  });

  // Keep the EventSource ref so we can close it on unmount or new audit
  const esRef = useRef<EventSource | null>(null);

  const reset = useCallback(() => {
    esRef.current?.close();
    setState({
      threadId: null,
      status: "pending",
      pipelineNodes: initialPipeline(),
      findings: [],
      scannerOutput: null,
      patcherOutput: null,
      criticOutput: null,
      error: null,
      isStreaming: false,
    });
  }, []);

  const startAudit = useCallback(
    async (sourceCode: string, filename: string, language: string) => {
      reset();

      const { thread_id } = await api.startAudit(sourceCode, filename, language);
      setState((prev) => ({ ...prev, threadId: thread_id, status: "running", isStreaming: true }));

      // Activate the scanner node immediately so the UI feels responsive
      setState((prev) => ({
        ...prev,
        pipelineNodes: updateNode(prev.pipelineNodes, "scanner", { state: "active" }),
      }));

      const url = api.streamUrl(thread_id, sourceCode, filename, language);
      const es = new EventSource(url);
      esRef.current = es;

      es.onmessage = (e: MessageEvent<string>) => {
        handleSSEMessage(e.data);
      };

      // Named event handlers for each SSE event type the backend emits
      const eventTypes: AuditSSEEvent["event"][] = [
        "node_complete",
        "patch_ready",
        "critic_verdict",
        "awaiting_human",
        "completed",
        "error",
        "retry",
      ];

      eventTypes.forEach((type) => {
        es.addEventListener(type, (e: Event) => {
          if (e instanceof MessageEvent) {
            handleSSEMessage(e.data);
          }
        });
      });

      es.onerror = () => {
        setState((prev) => ({
          ...prev,
          error: "Connection to audit stream lost.",
          isStreaming: false,
          status: "failed",
        }));
        es.close();
      };
    },
    [reset],
  );

  function handleSSEMessage(raw: string) {
    let event: AuditSSEEvent;
    try {
      event = JSON.parse(raw) as AuditSSEEvent;
    } catch {
      return;
    }

    setState((prev) => {
      const next = { ...prev };

      switch (event.event) {
        case "node_complete": {
          if (event.node === "scanner" && "data" in event) {
            const data = event.data as { findings: SecurityFinding[]; summary: string; risk_score: number };
            next.scannerOutput = {
              findings: data.findings,
              summary: data.summary,
              risk_score: data.risk_score,
            };
            next.findings = data.findings;
            next.pipelineNodes = updateNode(
              updateNode(prev.pipelineNodes, "scanner", { state: "done" }),
              "patcher",
              { state: "active" },
            );
          }
          break;
        }

        case "patch_ready": {
          if ("data" in event) {
            const data = event.data as { patch: PatcherOutput["diff"]; rationale: string; retry_count: number };
            next.patcherOutput = {
              finding_id: prev.scannerOutput?.findings[0]?.id ?? "",
              rationale: data.rationale,
              diff: data.patch,
              is_breaking_change: false,
            };
            const isRetry = data.retry_count > 0;
            next.pipelineNodes = updateNode(
              updateNode(prev.pipelineNodes, "patcher", {
                state: isRetry ? "retrying" : "done",
                retryCount: data.retry_count,
              }),
              "critic",
              { state: "active" },
            );
          }
          break;
        }

        case "critic_verdict": {
          if ("data" in event) {
            const data = event.data as { verdict: string; feedback: string; syntax_valid: boolean };
            next.criticOutput = {
              verdict: data.verdict as "approved" | "rejected",
              feedback: data.feedback,
              syntax_valid: data.syntax_valid,
              potential_side_effects: [],
            };
            const approved = data.verdict === "approved";
            next.pipelineNodes = updateNode(prev.pipelineNodes, "critic", {
              state: approved ? "done" : "error",
            });
          }
          break;
        }

        case "awaiting_human": {
          next.status = "awaiting_approval";
          next.isStreaming = false;
          next.pipelineNodes = updateNode(prev.pipelineNodes, "human_review", {
            state: "waiting",
          });
          esRef.current?.close();
          break;
        }

        case "completed": {
          if ("data" in event) {
            const data = event.data as { status: AuditStatus; error: string | null };
            next.status = data.status;
            next.error = data.error;
            next.isStreaming = false;
          }
          esRef.current?.close();
          break;
        }

        case "error": {
          if ("data" in event) {
            const data = event.data as { error: string };
            next.error = data.error;
            next.status = "failed";
            next.isStreaming = false;
          }
          esRef.current?.close();
          break;
        }

        case "retry": {
          const currentRetries =
            prev.pipelineNodes.find((n) => n.node === "patcher")?.retryCount ?? 0;
          next.pipelineNodes = updateNode(prev.pipelineNodes, "patcher", {
            state: "active",
            retryCount: currentRetries + 1,
          });
          break;
        }
      }

      return next;
    });
  }

  return { state, startAudit, reset };
}
