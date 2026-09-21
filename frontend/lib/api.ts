import type { EmailDetail, EmailListItem, ReportStatus, ReviewItem, Summary } from "@/lib/types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers: { "Content-Type": "application/json", ...init?.headers }, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  summary: () => request<Summary>("/api/summary"),
  emails: (params: Record<string, string | undefined> = {}) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => value && search.set(key, value));
    return request<{ items: EmailListItem[]; total: number }>(`/api/emails${search.size ? `?${search}` : ""}`);
  },
  email: (emailId: string) => request<EmailDetail>(`/api/emails/${encodeURIComponent(emailId)}`),
  review: () => request<{ items: ReviewItem[]; total: number }>("/api/review"),
  run: () => request<{ message: string; summary: Summary }>("/api/run", { method: "POST" }),
  report: () => request<ReportStatus>("/api/report"),
  generateReport: () => request<ReportStatus & { download_url: string }>("/api/report", { method: "POST" }),
};
