"use client";

import { ApprovalPanel } from "@/components/audit/ApprovalPanel";
import { CodeUpload } from "@/components/audit/CodeUpload";
import { DiffViewer } from "@/components/audit/DiffViewer";
import { FindingsList } from "@/components/audit/FindingsList";
import { PipelineVisualizer } from "@/components/audit/PipelineVisualizer";
import { useAuditStream } from "@/hooks/useAuditStream";
import { cn } from "@/lib/utils";
import { CheckCircle2, Github, Shield, XCircle } from "lucide-react";
import { useState } from "react";

export default function HomePage() {
  const { state, startAudit, reset } = useAuditStream();
  const [approvalResult, setApprovalResult] = useState<boolean | null>(null);

  const totalRetries = state.pipelineNodes.reduce((n, p) => n + p.retryCount, 0);
  const hasResults = state.findings.length > 0 || state.patcherOutput !== null;
  const showApproval =
    state.status === "awaiting_approval" &&
    state.patcherOutput !== null &&
    state.criticOutput !== null &&
    approvalResult === null;

  function handleApprovalDecision(approved: boolean) {
    setApprovalResult(approved);
  }

  function handleNewAudit() {
    reset();
    setApprovalResult(null);
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Nav */}
      <header className="border-b border-surface-border bg-surface-raised/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-brand flex items-center justify-center">
              <Shield className="w-4 h-4 text-white" />
            </div>
            <div>
              <span className="font-bold text-gray-100">HuGuard</span>
              <span className="text-brand font-bold"> AI</span>
              <span className="ml-2 text-xs text-gray-600 font-mono">v1.0</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-xs text-gray-600 hidden sm:block">
              Powered by LangGraph + Ollama · 100% local
            </span>
            <a
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              className="text-gray-500 hover:text-gray-300 transition-colors"
              aria-label="GitHub"
            >
              <Github className="w-5 h-5" />
            </a>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-7xl mx-auto w-full px-6 py-8">
        {/* Hero – shown only before first audit */}
        {!state.threadId && (
          <div className="text-center mb-10">
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-brand/10 border border-brand/20 text-brand text-xs mb-6">
              <span className="w-1.5 h-1.5 rounded-full bg-brand animate-pulse" />
              Multi-Agent · Human-in-the-Loop · Zero Cloud Dependencies
            </div>
            <h1 className="text-4xl font-bold text-gray-100 mb-3 tracking-tight">
              Autonomous Code Security Auditor
            </h1>
            <p className="text-gray-500 max-w-xl mx-auto leading-relaxed">
              Upload your code. HuGuard&apos;s LangGraph agent pipeline scans for
              vulnerabilities, generates patches, critiques them, and asks for your approval
              — entirely on-device.
            </p>
          </div>
        )}

        <div
          className={cn(
            "grid gap-6",
            hasResults ? "grid-cols-1 lg:grid-cols-[340px_1fr]" : "max-w-2xl mx-auto",
          )}
        >
          {/* Left column */}
          <div className="space-y-6">
            <div className="rounded-xl border border-surface-border bg-surface-raised p-5">
              {!state.threadId ? (
                <CodeUpload onSubmit={startAudit} isLoading={state.isStreaming} />
              ) : (
                <div className="space-y-5">
                  <PipelineVisualizer
                    nodes={state.pipelineNodes}
                    retryCount={totalRetries}
                  />
                  {state.threadId && !state.isStreaming && (
                    <button
                      onClick={handleNewAudit}
                      className="w-full py-2.5 text-sm text-gray-500 hover:text-gray-300 border border-surface-border rounded-lg hover:border-gray-600 transition-all"
                    >
                      Start new audit
                    </button>
                  )}
                </div>
              )}
            </div>

            {/* Status banner */}
            {approvalResult === true && (
              <div className="flex items-center gap-3 p-4 rounded-xl bg-green-500/10 border border-green-500/30">
                <CheckCircle2 className="w-5 h-5 text-green-400 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium text-green-300">Patch Applied</p>
                  <p className="text-xs text-green-500/70">Your approval has been recorded.</p>
                </div>
              </div>
            )}

            {approvalResult === false && (
              <div className="flex items-center gap-3 p-4 rounded-xl bg-red-500/10 border border-red-500/30">
                <XCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium text-red-300">Patch Rejected</p>
                  <p className="text-xs text-red-500/70">The proposed fix has been discarded.</p>
                </div>
              </div>
            )}

            {state.status === "failed" && state.error && (
              <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30">
                <p className="text-sm font-medium text-red-300 mb-1">Audit Failed</p>
                <p className="text-xs text-red-400 font-mono break-all">{state.error}</p>
              </div>
            )}
          </div>

          {/* Right column – results */}
          {hasResults && (
            <div className="space-y-6">
              <FindingsList
                findings={state.findings}
                riskScore={state.scannerOutput?.risk_score ?? null}
                summary={state.scannerOutput?.summary ?? null}
              />

              {state.patcherOutput && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-widest">
                      AI-Generated Patch
                    </h2>
                    {state.patcherOutput.is_breaking_change && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-orange-500/10 border border-orange-500/30 text-orange-400">
                        Breaking change
                      </span>
                    )}
                  </div>
                  <DiffViewer
                    diff={state.patcherOutput.diff}
                    filename={state.patcherOutput.diff.original_snippet.includes(".ts")
                      ? "patch.ts"
                      : "patch.py"}
                  />
                </div>
              )}

              {showApproval && state.threadId && state.patcherOutput && state.criticOutput && (
                <ApprovalPanel
                  threadId={state.threadId}
                  patcherOutput={state.patcherOutput}
                  criticOutput={state.criticOutput}
                  onDecision={handleApprovalDecision}
                />
              )}
            </div>
          )}
        </div>
      </main>

      <footer className="border-t border-surface-border py-4">
        <div className="max-w-7xl mx-auto px-6 flex items-center justify-between text-xs text-gray-700">
          <span>HuGuard AI · LangGraph + FastAPI + Next.js 14</span>
          <span>All processing is local · No data leaves your machine</span>
        </div>
      </footer>
    </div>
  );
}
