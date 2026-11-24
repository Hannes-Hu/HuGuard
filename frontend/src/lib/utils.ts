import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { Severity } from "@/types/audit";

// Tailwind-merge so component className overrides don't produce duplicate utilities
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function severityColor(severity: Severity): string {
  const map: Record<Severity, string> = {
    critical: "text-severity-critical",
    high: "text-severity-high",
    medium: "text-severity-medium",
    low: "text-severity-low",
    info: "text-severity-info",
  };
  return map[severity];
}

export function severityBg(severity: Severity): string {
  const map: Record<Severity, string> = {
    critical: "bg-red-500/10 border-red-500/30 text-red-400",
    high: "bg-orange-500/10 border-orange-500/30 text-orange-400",
    medium: "bg-yellow-500/10 border-yellow-500/30 text-yellow-400",
    low: "bg-blue-500/10 border-blue-500/30 text-blue-400",
    info: "bg-gray-500/10 border-gray-500/30 text-gray-400",
  };
  return map[severity];
}

export function riskScoreColor(score: number): string {
  if (score >= 75) return "text-red-400";
  if (score >= 50) return "text-orange-400";
  if (score >= 25) return "text-yellow-400";
  return "text-green-400";
}
