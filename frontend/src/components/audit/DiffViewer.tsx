"use client";

// Pure inline diff viewer – no external diff library dependency.
// We parse the unified diff string from the backend rather than re-computing it
// client-side, which guarantees the view matches what the Critic actually saw.

import { cn } from "@/lib/utils";
import type { UnifiedDiff } from "@/types/audit";
import { Copy, FileCode } from "lucide-react";
import { useState } from "react";

interface Props {
  diff: UnifiedDiff;
  filename?: string;
}

type DiffLineType = "add" | "remove" | "context" | "header";

interface DiffLine {
  type: DiffLineType;
  content: string;
  newLineNo: number | null;
  oldLineNo: number | null;
}

function parseDiff(raw: string): DiffLine[] {
  const lines = raw.split("\n");
  const result: DiffLine[] = [];
  let oldLine = 0;
  let newLine = 0;

  for (const line of lines) {
    if (line.startsWith("@@")) {
      // Parse @@ -old,count +new,count @@ header
      const match = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (match) {
        oldLine = parseInt(match[1] ?? "1", 10);
        newLine = parseInt(match[2] ?? "1", 10);
      }
      result.push({ type: "header", content: line, newLineNo: null, oldLineNo: null });
    } else if (line.startsWith("+") && !line.startsWith("+++")) {
      result.push({ type: "add", content: line.slice(1), newLineNo: newLine++, oldLineNo: null });
    } else if (line.startsWith("-") && !line.startsWith("---")) {
      result.push({ type: "remove", content: line.slice(1), newLineNo: null, oldLineNo: oldLine++ });
    } else if (!line.startsWith("---") && !line.startsWith("+++")) {
      result.push({ type: "context", content: line.slice(1), newLineNo: newLine++, oldLineNo: oldLine++ });
    }
  }

  return result;
}

function LineNumber({ n }: { n: number | null }) {
  return (
    <span className="select-none w-10 inline-block text-right text-xs text-gray-600 pr-3 font-mono flex-shrink-0">
      {n ?? ""}
    </span>
  );
}

export function DiffViewer({ diff, filename }: Props) {
  const [copied, setCopied] = useState(false);
  const lines = parseDiff(diff.unified_diff);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(diff.patched_snippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-xl border border-surface-border overflow-hidden">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-surface-raised border-b border-surface-border">
        <div className="flex items-center gap-2">
          <FileCode className="w-4 h-4 text-gray-500" />
          <span className="text-xs font-mono text-gray-400">{filename ?? "patch.diff"}</span>
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          <Copy className="w-3.5 h-3.5" />
          {copied ? "Copied!" : "Copy patch"}
        </button>
      </div>

      {/* Diff legend */}
      <div className="flex items-center gap-4 px-4 py-1.5 bg-surface-overlay border-b border-surface-border">
        <span className="text-xs text-gray-600">
          <span className="text-green-400 font-mono">+</span> added
        </span>
        <span className="text-xs text-gray-600">
          <span className="text-red-400 font-mono">−</span> removed
        </span>
      </div>

      {/* Side-by-side view */}
      <div className="overflow-x-auto bg-surface-raised">
        <table className="w-full text-xs font-mono border-collapse">
          <thead className="sr-only">
            <tr>
              <th>Old line</th>
              <th>New line</th>
              <th>Change</th>
              <th>Code</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line, idx) => {
              if (line.type === "header") {
                return (
                  <tr key={idx} className="bg-surface-overlay">
                    <td colSpan={4} className="px-4 py-1 text-gray-500 select-none">
                      {line.content}
                    </td>
                  </tr>
                );
              }

              return (
                <tr
                  key={idx}
                  className={cn(
                    "group",
                    line.type === "add" && "bg-green-500/8 hover:bg-green-500/12",
                    line.type === "remove" && "bg-red-500/8 hover:bg-red-500/12",
                    line.type === "context" && "hover:bg-surface-overlay",
                  )}
                >
                  <td className="select-none w-10 text-right text-gray-600 pr-2 pl-3 border-r border-surface-border">
                    {line.oldLineNo}
                  </td>
                  <td className="select-none w-10 text-right text-gray-600 pr-2 border-r border-surface-border">
                    {line.newLineNo}
                  </td>
                  <td className="select-none w-5 text-center">
                    {line.type === "add" && (
                      <span className="text-green-400">+</span>
                    )}
                    {line.type === "remove" && (
                      <span className="text-red-400">−</span>
                    )}
                  </td>
                  <td className="pl-2 pr-4 py-0.5 whitespace-pre">
                    <span
                      className={cn(
                        line.type === "add" && "text-green-300",
                        line.type === "remove" && "text-red-300",
                        line.type === "context" && "text-gray-400",
                      )}
                    >
                      {line.content}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
