"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, ChevronDown, FileText, Info, Paperclip, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { EmailDetail } from "@/lib/types";
import { ErrorState, LoadingState } from "@/components/data-state";
import { StatusBadge } from "@/components/status-badge";

export default function EmailDetailPage() {
  const params = useParams<{ emailId: string }>();
  const emailId = Array.isArray(params.emailId) ? params.emailId[0] : params.emailId;
  const [detail, setDetail] = useState<EmailDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (!emailId) return; let active = true; api.email(emailId).then((value) => { if (active) { setDetail(value); setError(null); } }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Unable to reach the API"); }); return () => { active = false; }; }, [emailId]);

  if (error) return <><BackLink /><ErrorState message={error} /></>;
  if (!detail) return <><BackLink /><div className="panel"><LoadingState rows={8} /></div></>;
  return <Detail detail={detail} />;
}

function BackLink() { return <Link href="/inbox" className="mb-6 inline-flex items-center gap-2 text-sm text-muted transition hover:text-cyan"><ArrowLeft size={16} />Back to inbox</Link>; }

function Detail({ detail }: { detail: EmailDetail }) {
  return <div className="space-y-6">
    <BackLink />
    <section className="panel overflow-hidden"><div className="border-b border-line p-5 sm:p-7"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="eyebrow">Email inspection</p><h1 className="mt-2 font-mono text-xl font-semibold text-ink sm:text-2xl">{detail.email_id}</h1><p className="mt-2 max-w-4xl text-sm leading-6 text-muted">{detail.subject || "No subject"}</p></div><StatusBadge status={detail.status} /></div></div><div className="grid divide-y divide-line sm:grid-cols-3 sm:divide-x sm:divide-y-0"><InfoCell label="Classification" value={humanize(detail.category)} /><InfoCell label="Extraction" value={humanize(detail.extraction_status)} /><InfoCell label="Final decision" value={detail.status ?? "Not applicable"} /></div></section>
    <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
      <section className="panel p-5 sm:p-6"><div className="flex items-center gap-2"><ShieldAlert size={18} className="text-cyan" /><h2 className="font-semibold text-ink">Classification evidence</h2></div><div className="mt-4 space-y-2">{detail.classification_reasons.length ? detail.classification_reasons.map((reason) => <div key={reason} className="rounded-lg border border-line bg-raised/35 px-3 py-2 text-sm text-muted">{reason}</div>) : <p className="text-sm text-muted">No category-specific evidence was stored for this record.</p>}</div></section>
      <section className="panel p-5 sm:p-6"><div className="flex items-center gap-2"><AlertTriangle size={18} className={detail.status === "NEEDS_REVIEW" ? "text-warning" : "text-muted"} /><h2 className="font-semibold text-ink">Decision context</h2></div><dl className="mt-4 grid gap-3 text-sm"><Definition label="Review reason" value={humanize(detail.review_reason)} /><Definition label="Differing fields" value={detail.defect_fields.length ? detail.defect_fields.map(humanize).join(", ") : "—"} />{detail.error && <Definition label="Safe processing note" value={detail.error} />}</dl></section>
    </div>
    <section className="panel overflow-hidden"><div className="border-b border-line p-5 sm:p-6"><div className="flex items-center gap-2"><Paperclip size={18} className="text-cyan" /><h2 className="font-semibold text-ink">Attachments and document identification</h2></div><p className="mt-1 text-xs text-muted">Attachment format, extraction method, and detection evidence stored by the pipeline.</p></div>{detail.attachments.length ? <div className="divide-y divide-line">{detail.attachments.map((attachment) => <div className="p-5" key={attachment.filename}><div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-raised text-cyan"><FileText size={17} /></span><div><p className="text-sm font-medium text-ink">{attachment.filename}</p><p className="mt-0.5 text-xs text-muted">{attachment.source_format ?? "Unknown format"} · {attachment.extraction ?? "Extraction unavailable"}</p></div></div><span className="rounded-full border border-line bg-raised px-2.5 py-1 text-[11px] font-semibold text-muted">{attachment.detected_type ?? "Not evaluated"}</span></div>{attachment.read_error && <p className="mt-3 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">{attachment.read_error}</p>}{attachment.evidence.length > 0 && <ul className="mt-3 space-y-1 pl-4 text-xs text-muted">{attachment.evidence.map((evidence) => <li key={evidence} className="list-disc">{evidence}</li>)}</ul>}</div>)}</div> : <p className="p-6 text-sm text-muted">This email has no attachments.</p>}</section>
    {detail.comparison_fields.length > 0 && <Comparison detail={detail} />}
  </div>;
}

function InfoCell({ label, value }: { label: string; value: string }) { return <div className="p-5"><p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{label}</p><p className="mt-2 text-sm font-medium text-ink">{value}</p></div>; }
function Definition({ label, value }: { label: string; value: string }) { return <div className="grid grid-cols-[130px_1fr] gap-3"><dt className="text-muted">{label}</dt><dd className="text-ink">{value}</dd></div>; }

function Comparison({ detail }: { detail: EmailDetail }) {
  return <section className="panel overflow-hidden"><div className="flex flex-wrap items-start justify-between gap-4 border-b border-line p-5 sm:p-6"><div><p className="eyebrow">SI against draft BL</p><h2 className="mt-2 font-semibold text-ink">Required field comparison</h2><p className="mt-1 text-xs text-muted">Only fields with a true pipeline mismatch are highlighted.</p></div><div className="text-right text-xs text-muted"><p>Selected SI: <span className="text-ink">{detail.selected_documents.si ?? "—"}</span></p><p className="mt-1">Selected BL: <span className="text-ink">{detail.selected_documents.bl ?? "—"}</span></p></div></div><div className="overflow-x-auto"><table className="w-full min-w-[760px]"><thead><tr className="table-header"><th className="px-5 py-3">Field</th><th className="px-5 py-3">SI value</th><th className="px-5 py-3">BL value</th><th className="px-5 py-3">Result</th></tr></thead><tbody>{detail.comparison_fields.map((field) => <tr key={field.field} className={`border-b border-line last:border-0 ${field.result === "MISMATCH" ? "bg-danger/10" : ""}`}><td className="px-5 py-4 text-sm font-medium text-ink">{humanize(field.field)}</td><td className="max-w-xs px-5 py-4 text-sm text-muted">{field.si_value ?? "—"}</td><td className="max-w-xs px-5 py-4 text-sm text-muted">{field.bl_value ?? "—"}</td><td className="px-5 py-4"><Result result={field.result} /></td></tr>)}</tbody></table></div><details className="border-t border-line"><summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 text-sm font-medium text-muted hover:text-ink">Normalized values used by the comparison <ChevronDown size={16} /></summary><div className="overflow-x-auto border-t border-line"><table className="w-full min-w-[760px]"><thead><tr className="table-header"><th className="px-5 py-3">Field</th><th className="px-5 py-3">Normalized SI</th><th className="px-5 py-3">Normalized BL</th></tr></thead><tbody>{detail.comparison_fields.map((field) => <tr key={field.field} className="table-row"><td className="px-5 py-3 text-sm text-ink">{humanize(field.field)}</td><td className="px-5 py-3 text-sm text-muted">{field.si_normalized ?? "—"}</td><td className="px-5 py-3 text-sm text-muted">{field.bl_normalized ?? "—"}</td></tr>)}</tbody></table></div></details></section>;
}

function Result({ result }: { result: string }) { const style = result === "MATCH" ? "border-success/30 bg-success/10 text-success" : result === "MISMATCH" ? "border-danger/30 bg-danger/10 text-danger" : "border-line bg-raised text-muted"; return <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${style}`}>{result}</span>; }
