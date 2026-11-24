"use client";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { CriticOutput, PatcherOutput } from "@/types/audit";
import { CheckCircle2, MessageSquare, XCircle } from "lucide-react";
import { useState } from "react";

interface Props {
  threadId: string;
  patcherOutput: PatcherOutput;
  criticOutput: CriticOutput;
  onDecision: (approved: boolean) => void;
}

export function ApprovalPanel({ threadId, patcherOutput, criticOutput, onDecision }: Props) {
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState<"approve" | "reject" | null>(null);

  async function handleDecision(decision: "approve" | "reject") {
    setSubmitting(decision);
    try {
      await api.approve(threadId, comment ? { decision, comment } : { decision });
      onDecision(decision === "approve");
    } catch (err) {
      console.error("Approval request failed:", err);
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <div className="rounded-xl border border-yellow-500/30 bg-yellow-500/5 overflow-hidden animate-fade-up">
      {/* Header */}
      <div className="px-5 py-4 border-b border-yellow-500/20 flex items-center gap-3">
        <div className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
        <h3 className="text-sm font-semibold text-yellow-300">Human Review Required</h3>
      </div>

      <div className="p-5 space-y-5">
        {/* Critic summary */}
        <div
          className={cn(
            "flex items-start gap-3 p-3 rounded-lg border text-sm",
            criticOutput.verdict === "approved"
              ? "bg-green-500/10 border-green-500/30 text-green-300"
              : "bg-red-500/10 border-red-500/30 text-red-300",
          )}
        >
          {criticOutput.verdict === "approved" ? (
            <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0 text-green-400" />
          ) : (
            <XCircle className="w-4 h-4 mt-0.5 flex-shrink-0 text-red-400" />
          )}
          <div>
            <p className="font-medium mb-0.5">
              Critic {criticOutput.verdict === "approved" ? "approved" : "flagged"} this patch
            </p>
            <p className="text-xs opacity-80">{criticOutput.feedback}</p>
          </div>
        </div>

        {/* Patcher rationale */}
        <div>
          <p className="text-xs text-gray-500 mb-2 uppercase tracking-widest">Patch Rationale</p>
          <p className="text-sm text-gray-300 leading-relaxed">{patcherOutput.rationale}</p>
          {patcherOutput.is_breaking_change && (
            <div className="mt-2 text-xs text-orange-400 flex items-center gap-1.5">
              <span>⚠</span>
              <span>This patch may introduce breaking API changes</span>
            </div>
          )}
        </div>

        {/* Potential side effects */}
        {criticOutput.potential_side_effects.length > 0 && (
          <div>
            <p className="text-xs text-gray-500 mb-2 uppercase tracking-widest">Potential Side Effects</p>
            <ul className="space-y-1">
              {criticOutput.potential_side_effects.map((effect, i) => (
                <li key={i} className="text-xs text-gray-400 flex items-start gap-2">
                  <span className="text-yellow-500 mt-0.5">•</span>
                  {effect}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Comment field */}
        <div>
          <label className="flex items-center gap-2 text-xs text-gray-500 mb-2">
            <MessageSquare className="w-3.5 h-3.5" />
            Comment (optional)
          </label>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            placeholder="Add a note about your decision..."
            className="w-full bg-surface-raised border border-surface-border rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-brand resize-none placeholder:text-gray-700"
          />
        </div>

        {/* Action buttons */}
        <div className="flex gap-3">
          <button
            onClick={() => handleDecision("approve")}
            disabled={submitting !== null}
            className={cn(
              "flex-1 py-2.5 rounded-lg text-sm font-semibold transition-all",
              submitting === null
                ? "bg-green-600 hover:bg-green-500 text-white shadow-lg shadow-green-900/30"
                : "bg-surface-border text-gray-600 cursor-not-allowed",
            )}
          >
            {submitting === "approve" ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Applying…
              </span>
            ) : (
              <span className="flex items-center justify-center gap-2">
                <CheckCircle2 className="w-4 h-4" />
                Approve & Apply Patch
              </span>
            )}
          </button>

          <button
            onClick={() => handleDecision("reject")}
            disabled={submitting !== null}
            className={cn(
              "flex-1 py-2.5 rounded-lg text-sm font-semibold transition-all border",
              submitting === null
                ? "border-red-500/40 text-red-400 hover:bg-red-500/10"
                : "border-surface-border text-gray-600 cursor-not-allowed",
            )}
          >
            {submitting === "reject" ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 border-2 border-red-500/30 border-t-red-500 rounded-full animate-spin" />
                Rejecting…
              </span>
            ) : (
              <span className="flex items-center justify-center gap-2">
                <XCircle className="w-4 h-4" />
                Reject
              </span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
