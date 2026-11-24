"use client";

import { cn, severityBg } from "@/lib/utils";
import type { SecurityFinding, Severity } from "@/types/audit";
import { AlertTriangle, ChevronDown, ChevronRight, Shield } from "lucide-react";
import { useState } from "react";

interface Props {
  findings: SecurityFinding[];
  riskScore: number | null;
  summary: string | null;
}

const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border uppercase tracking-wide",
        severityBg(severity),
      )}
    >
      {severity}
    </span>
  );
}

function FindingRow({ finding }: { finding: SecurityFinding }) {
  const [expanded, setExpanded] = useState(false);
  const ChevronIcon = expanded ? ChevronDown : ChevronRight;

  return (
    <div className="border border-surface-border rounded-lg overflow-hidden">
      <button
        className="w-full flex items-start gap-3 p-3 text-left hover:bg-surface-overlay transition-colors"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <ChevronIcon className="w-4 h-4 text-gray-500 mt-0.5 flex-shrink-0" />
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <SeverityBadge severity={finding.severity} />
            {finding.cwe_id && (
              <span className="text-xs text-gray-500 font-mono">{finding.cwe_id}</span>
            )}
            <span className="text-sm font-medium text-gray-200">{finding.title}</span>
          </div>
          {finding.affected_lines.length > 0 && (
            <p className="text-xs text-gray-500 font-mono">
              Lines: {finding.affected_lines.join(", ")}
            </p>
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-surface-border bg-surface-raised animate-fade-up">
          <p className="text-sm text-gray-300 leading-relaxed">{finding.description}</p>
          <div className="mt-2 flex items-center gap-2">
            <span className="text-xs text-gray-600">Category:</span>
            <span className="text-xs font-mono text-gray-400">{finding.category}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function RiskGauge({ score }: { score: number }) {
  const color =
    score >= 75 ? "bg-red-500" : score >= 50 ? "bg-orange-500" : score >= 25 ? "bg-yellow-500" : "bg-green-500";
  const textColor =
    score >= 75 ? "text-red-400" : score >= 50 ? "text-orange-400" : score >= 25 ? "text-yellow-400" : "text-green-400";

  return (
    <div className="space-y-1">
      <div className="flex justify-between items-center">
        <span className="text-xs text-gray-500">Risk Score</span>
        <span className={cn("text-sm font-bold font-mono", textColor)}>{score}/100</span>
      </div>
      <div className="h-1.5 bg-surface-border rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-700", color)}
          style={{ width: `${score}%` }}
        />
      </div>
    </div>
  );
}

export function FindingsList({ findings, riskScore, summary }: Props) {
  const sortedFindings = [...findings].sort(
    (a, b) =>
      SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
  );

  const counts = SEVERITY_ORDER.reduce<Record<Severity, number>>(
    (acc, s) => {
      acc[s] = findings.filter((f) => f.severity === s).length;
      return acc;
    },
    { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
  );

  if (findings.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <Shield className="w-10 h-10 text-gray-700 mb-3" />
        <p className="text-sm text-gray-500">No findings yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-widest">
          Findings
        </h2>
        <span className="text-xs text-gray-500">{findings.length} total</span>
      </div>

      {/* Severity breakdown pills */}
      <div className="flex flex-wrap gap-2">
        {SEVERITY_ORDER.map((s) =>
          counts[s] > 0 ? (
            <span
              key={s}
              className={cn(
                "text-xs px-2 py-0.5 rounded-full border",
                severityBg(s),
              )}
            >
              {counts[s]} {s}
            </span>
          ) : null,
        )}
      </div>

      {riskScore !== null && <RiskGauge score={riskScore} />}

      {summary && (
        <div className="p-3 rounded-lg bg-surface-raised border border-surface-border text-sm text-gray-400 leading-relaxed">
          <AlertTriangle className="w-4 h-4 text-yellow-500 inline mr-2 -mt-0.5" />
          {summary}
        </div>
      )}

      <div className="space-y-2">
        {sortedFindings.map((f) => (
          <FindingRow key={f.id} finding={f} />
        ))}
      </div>
    </div>
  );
}
