import type {
  ApprovalRequest,
  AuditStartResponse,
  AuditSummaryResponse,
} from "@/types/audit";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }

  return res.json() as Promise<T>;
}

export const api = {
  startAudit(sourceCode: string, filename: string, language: string) {
    return request<AuditStartResponse>("/api/v1/audit/start", {
      method: "POST",
      body: JSON.stringify({ source_code: sourceCode, filename, language }),
    });
  },

  approve(threadId: string, body: ApprovalRequest) {
    return request<AuditSummaryResponse>(`/api/v1/audit/${threadId}/approve`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  getAudit(threadId: string) {
    return request<AuditSummaryResponse>(`/api/v1/audit/${threadId}`);
  },

  // Returns a raw EventSource URL – the hook manages the connection lifecycle
  streamUrl(threadId: string, sourceCode: string, filename: string, language: string) {
    const params = new URLSearchParams({
      source_code: sourceCode,
      filename,
      language,
    });
    return `${BASE_URL}/api/v1/audit/${threadId}/stream?${params.toString()}`;
  },
};
