"use client";

import { cn } from "@/lib/utils";
import type { AgentNode, PipelineNodeStatus } from "@/types/audit";
import {
  Bot,
  CheckCircle2,
  CircleDashed,
  Clock,
  GitMerge,
  RefreshCw,
  ShieldAlert,
  Siren,
  XCircle,
} from "lucide-react";

interface Props {
  nodes: PipelineNodeStatus[];
  retryCount: number;
}

const NODE_META: Record<
  AgentNode,
  { label: string; description: string; Icon: React.ElementType }
> = {
  scanner: {
    label: "Scanner & Triage",
    description: "AST analysis + vulnerability detection",
    Icon: Siren,
  },
  patcher: {
    label: "Patch Generator",
    description: "Creates targeted code fixes",
    Icon: GitMerge,
  },
  critic: {
    label: "Critic & Verifier",
    description: "Validates patch correctness",
    Icon: Bot,
  },
  human_review: {
    label: "Human Review",
    description: "Your approval required",
    Icon: ShieldAlert,
  },
  done: {
    label: "Done",
    description: "",
    Icon: CheckCircle2,
  },
};

const ORDERED: AgentNode[] = ["scanner", "patcher", "critic", "human_review"];

function StateIcon({ state }: { state: PipelineNodeStatus["state"] }) {
  switch (state) {
    case "active":
      return <RefreshCw className="w-4 h-4 text-brand animate-spin" />;
    case "done":
      return <CheckCircle2 className="w-4 h-4 text-green-400" />;
    case "error":
      return <XCircle className="w-4 h-4 text-red-400" />;
    case "waiting":
      return <Clock className="w-4 h-4 text-yellow-400 animate-pulse" />;
    case "retrying":
      return <RefreshCw className="w-4 h-4 text-orange-400 animate-spin" />;
    default:
      return <CircleDashed className="w-4 h-4 text-gray-600" />;
  }
}

function nodeRingClass(state: PipelineNodeStatus["state"]): string {
  return cn(
    "rounded-xl border p-4 transition-all duration-500",
    state === "active" && "border-brand bg-brand-glow shadow-[0_0_20px_rgba(99,102,241,0.3)] animate-glow-in",
    state === "done" && "border-green-500/40 bg-green-500/5",
    state === "error" && "border-red-500/40 bg-red-500/5",
    state === "waiting" && "border-yellow-500/40 bg-yellow-500/5",
    state === "retrying" && "border-orange-500/40 bg-orange-500/5",
    state === "idle" && "border-surface-border bg-surface-raised",
  );
}

export function PipelineVisualizer({ nodes, retryCount }: Props) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-widest">
          Agent Pipeline
        </h2>
        {retryCount > 0 && (
          <span className="text-xs px-2 py-1 rounded-full bg-orange-500/10 border border-orange-500/30 text-orange-400">
            {retryCount} retry{retryCount > 1 ? "s" : ""}
          </span>
        )}
      </div>

      <div className="relative">
        {ORDERED.map((nodeId, idx) => {
          const nodeStatus = nodes.find((n) => n.node === nodeId);
          const state = nodeStatus?.state ?? "idle";
          const meta = NODE_META[nodeId];
          const Icon = meta.Icon;

          return (
            <div key={nodeId} className="relative">
              <div className={nodeRingClass(state)}>
                <div className="flex items-center gap-3">
                  <div
                    className={cn(
                      "flex-shrink-0 w-9 h-9 rounded-lg flex items-center justify-center transition-colors duration-300",
                      state === "active" && "bg-brand/20",
                      state === "done" && "bg-green-500/20",
                      state === "error" && "bg-red-500/20",
                      state === "waiting" && "bg-yellow-500/20",
                      state === "idle" && "bg-surface-overlay",
                    )}
                  >
                    <Icon
                      className={cn(
                        "w-5 h-5",
                        state === "active" && "text-brand",
                        state === "done" && "text-green-400",
                        state === "error" && "text-red-400",
                        state === "waiting" && "text-yellow-400",
                        state === "idle" && "text-gray-600",
                      )}
                    />
                  </div>

                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-200">{meta.label}</p>
                    <p className="text-xs text-gray-500 truncate">{meta.description}</p>
                  </div>

                  <StateIcon state={state} />
                </div>

                {/* Show retry badge on patcher when retrying */}
                {nodeId === "patcher" && nodeStatus && nodeStatus.retryCount > 0 && (
                  <div className="mt-2 ml-12 text-xs text-orange-400">
                    Attempt {nodeStatus.retryCount + 1} — incorporating critic feedback
                  </div>
                )}
              </div>

              {/* Connector line between nodes */}
              {idx < ORDERED.length - 1 && (
                <div className="ml-[1.125rem] w-px h-3 bg-surface-border" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
