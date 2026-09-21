"use client";

import Link from "next/link";
import { ArrowUpRight, FileWarning, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { ReviewItem } from "@/lib/types";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";

export default function ReviewPage() {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { let active = true; const load = () => api.review().then((response) => { if (active) { setItems(response.items); setError(null); } }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Unable to reach the API"); }); load(); window.addEventListener("averis:refreshed", load); return () => { active = false; window.removeEventListener("averis:refreshed", load); }; }, []);

  return <>
    <PageHeading eyebrow="Human review queue" title="The system knows when not to guess">Only verification requests without enough reliable evidence are shown here. No approval workflow is simulated; this view surfaces the exact existing review reason and evidence.</PageHeading>
    {error ? <ErrorState message={error} /> : !items ? <section className="panel"><LoadingState rows={6} /></section> : items.length === 0 ? <section className="panel"><EmptyState title="No cases require review" copy="The current pipeline run did not route any comparison requests to human review." /></section> : <div className="grid gap-4 xl:grid-cols-2">{items.map((item) => <ReviewCard key={item.email_id} item={item} />)}</div>}
  </>;
}

function ReviewCard({ item }: { item: ReviewItem }) {
  const documentIssue = item.attachments.map((attachment) => attachment.read_error ? `${attachment.filename}: ${attachment.read_error}` : `${attachment.filename}: ${attachment.extraction ?? "extraction unavailable"}`).join(" · ");
  return <article className="panel p-5 transition hover:border-warning/40"><div className="flex items-start justify-between gap-4"><div><p className="font-mono text-xs text-cyan">{item.email_id}</p><h2 className="mt-2 line-clamp-2 text-sm font-semibold leading-6 text-ink">{item.subject || "No subject"}</h2></div><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-warning/30 bg-warning/10 text-warning"><FileWarning size={18} /></span></div><div className="mt-5 grid gap-4 border-y border-line py-4 text-sm"><Info label="Review reason" value={humanize(item.review_reason)} emphasis /><Info label="Attachment / document issue" value={documentIssue || "No attachments were available"} /></div><div className="mt-4"><p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">Available evidence</p>{item.evidence.length ? <ul className="mt-2 space-y-1.5 text-xs leading-5 text-muted">{item.evidence.slice(0, 4).map((evidence, index) => <li className="flex gap-2" key={`${evidence}-${index}`}><ShieldCheck size={14} className="mt-0.5 shrink-0 text-cyan" />{evidence}</li>)}</ul> : <p className="mt-2 text-xs text-muted">No additional evidence was recorded.</p>}</div><Link href={`/inbox/${item.email_id}`} className="mt-5 inline-flex items-center gap-1 text-xs font-semibold text-cyan hover:text-[#7adcf6]">Inspect full evidence <ArrowUpRight size={14} /></Link></article>;
}

function Info({ label, value, emphasis = false }: { label: string; value: string; emphasis?: boolean }) { return <div><p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{label}</p><p className={`mt-1 break-words ${emphasis ? "font-medium text-warning" : "text-muted"}`}>{value}</p></div>; }
