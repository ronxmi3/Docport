"use client";

import { Download, FileText, LoaderCircle, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { API_BASE, api } from "@/lib/api";
import { formatBytes, formatDate } from "@/lib/format";
import type { ReportStatus } from "@/lib/types";
import { ErrorState, LoadingState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";

export default function ReportsPage() {
  const [report, setReport] = useState<ReportStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const load = () => api.report().then((value) => { setReport(value); setError(null); }).catch((cause) => setError(cause instanceof Error ? cause.message : "Unable to reach the API"));
  useEffect(() => { load(); }, []);
  async function generate() { setGenerating(true); setError(null); try { setReport(await api.generateReport()); } catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to generate the report"); } finally { setGenerating(false); } }
  const downloadHref = report?.download_url ? `${API_BASE}${report.download_url}` : undefined;

  return <>
    <PageHeading eyebrow="Audit output" title="Decision audit report">The existing PDF report generator is reused directly. Generating a report presents stored pipeline decisions; it does not reclassify or change a decision.</PageHeading>
    {error ? <ErrorState message={error} /> : !report ? <section className="panel"><LoadingState rows={4} /></section> : <section className="panel overflow-hidden"><div className="grid gap-8 p-6 sm:p-8 lg:grid-cols-[auto_1fr_auto] lg:items-center"><span className={`flex h-14 w-14 items-center justify-center rounded-2xl border ${report.exists ? "border-success/30 bg-success/10 text-success" : "border-line bg-raised text-muted"}`}><FileText size={27} /></span><div><p className="text-lg font-semibold text-ink">{report.exists ? "Audit report available" : "No generated report yet"}</p><p className="mt-2 max-w-xl text-sm leading-6 text-muted">{report.exists ? `${report.filename} · ${formatBytes(report.size_bytes)} · generated ${formatDate(report.generated_at)}` : "Generate a printable audit trail from the latest pipeline snapshot."}</p><p className="mt-4 inline-flex items-center gap-2 text-xs text-muted"><ShieldCheck size={14} className="text-cyan" />Uses the pipeline&apos;s existing decision-report implementation.</p></div><div className="flex flex-wrap gap-3 lg:justify-end"><button onClick={generate} disabled={generating} className="inline-flex h-10 items-center gap-2 rounded-lg bg-cyan px-4 text-sm font-semibold text-[#062031] transition hover:bg-[#7adcf6] disabled:cursor-wait disabled:opacity-70">{generating ? <LoaderCircle size={16} className="animate-spin" /> : <RefreshCw size={16} />}{report.exists ? "Regenerate" : "Generate report"}</button>{downloadHref && <a href={downloadHref} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-lg border border-line px-4 text-sm font-semibold text-ink transition hover:border-cyan/50 hover:bg-raised"><Download size={16} />Open PDF</a>}</div></div></section>}
  </>;
}
