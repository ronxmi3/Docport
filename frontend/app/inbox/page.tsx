"use client";

import Link from "next/link";
import { Search, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { EmailListItem } from "@/lib/types";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { StatusBadge } from "@/components/status-badge";

export default function InboxPage() {
  const [items, setItems] = useState<EmailListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [reviewReason, setReviewReason] = useState("");

  const categories = useMemo(() => [...new Set(items?.map((item) => item.category) ?? [])].sort(), [items]);
  const reasons = useMemo(() => [...new Set(items?.flatMap((item) => item.review_reason ? [item.review_reason] : []) ?? [])].sort(), [items]);

  useEffect(() => {
    let active = true;
    const load = async () => { try { const response = await api.emails({ query, category, status, review_reason: reviewReason }); if (active) { setItems(response.items); setError(null); } } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : "Unable to reach the API"); } };
    const timer = window.setTimeout(load, query ? 180 : 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [query, category, status, reviewReason]);

  return <>
    <PageHeading eyebrow="Processed email records" title="Inbox inspection">Search real pipeline results by email ID or subject, then narrow the queue by the pipeline&apos;s own category, decision, and review reason.</PageHeading>
    <section className="panel overflow-hidden">
      <div className="grid gap-3 border-b border-line p-4 xl:grid-cols-[minmax(260px,1fr)_repeat(3,180px)]">
        <label className="relative"><Search className="pointer-events-none absolute left-3 top-3 text-muted" size={16} /><input className="control w-full pl-9" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search email ID or subject" aria-label="Search email ID or subject" /></label>
        <Filter label="All categories" value={category} onChange={setCategory} values={categories} />
        <Filter label="All decisions" value={status} onChange={setStatus} values={["OK", "MISMATCH", "NEEDS_REVIEW"]} />
        <Filter label="All review reasons" value={reviewReason} onChange={setReviewReason} values={reasons} />
      </div>
      <div className="flex items-center justify-between px-5 py-3 text-xs text-muted"><span className="inline-flex items-center gap-2"><SlidersHorizontal size={14} />{items ? `${items.length} record${items.length === 1 ? "" : "s"}` : "Loading records"}</span><span>Click a record to inspect its evidence.</span></div>
      {error ? <div className="p-5"><ErrorState message={error} /></div> : items === null ? <LoadingState rows={8} /> : items.length === 0 ? <EmptyState title="No records match these filters" copy="Try clearing a filter or searching a different email ID or subject." /> : <InboxTable items={items} />}
    </section>
  </>;
}

function Filter({ label, value, onChange, values }: { label: string; value: string; onChange: (value: string) => void; values: string[] }) {
  return <select className="control w-full" value={value} onChange={(event) => onChange(event.target.value)} aria-label={label}><option value="">{label}</option>{values.map((item) => <option value={item} key={item}>{humanize(item)}</option>)}</select>;
}

function InboxTable({ items }: { items: EmailListItem[] }) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[900px]"><thead><tr className="table-header"><th className="px-5 py-3">Email ID</th><th className="px-5 py-3">Subject</th><th className="px-5 py-3">Category</th><th className="px-5 py-3">Final status</th><th className="px-5 py-3 text-center">Defects</th><th className="px-5 py-3">Review reason</th></tr></thead><tbody>{items.map((item) => <tr key={item.email_id} className="table-row cursor-pointer"><td className="px-5 py-3.5"><Link href={`/inbox/${item.email_id}`} className="font-mono text-xs text-cyan hover:underline">{item.email_id}</Link></td><td className="max-w-[400px] truncate px-5 py-3.5 text-sm text-ink" title={item.subject}>{item.subject || "No subject"}</td><td className="px-5 py-3.5 text-xs font-medium text-muted">{humanize(item.category)}</td><td className="px-5 py-3.5"><StatusBadge status={item.status} /></td><td className="px-5 py-3.5 text-center text-sm text-ink">{item.defect_count}</td><td className="px-5 py-3.5 text-xs text-muted">{humanize(item.review_reason)}</td></tr>)}</tbody></table></div>;
}
