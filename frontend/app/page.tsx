"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, ArrowUpRight, CheckCircle2, CircleHelp, Clock3, FileCheck2, FileWarning, Gauge, Mail } from "lucide-react";
import { api } from "@/lib/api";
import { formatDuration, formatNumber, humanize } from "@/lib/format";
import type { Distribution, Summary } from "@/lib/types";
import { DataState, ErrorState, LoadingState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { StatusBadge } from "@/components/status-badge";

const chartColors = ["#4cc9f0", "#46d8a3", "#f5b84b", "#a78bfa", "#ff7070"];
const tooltipStyle = { background: "#101c2d", border: "1px solid #253752", borderRadius: 12, color: "#edf5ff", fontSize: 12 };

export default function DashboardPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => { try { const value = await api.summary(); if (active) { setSummary(value); setError(null); } } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : "Unable to reach the API"); } };
    load(); window.addEventListener("averis:refreshed", load);
    return () => { active = false; window.removeEventListener("averis:refreshed", load); };
  }, []);

  return <>
    <PageHeading eyebrow="Verification operations" title="Shipping document intelligence">Live operational view of the latest verified pipeline run. Every card and chart is derived from the current source dataset.</PageHeading>
    {error ? <ErrorState message={error} /> : !summary ? <DashboardSkeleton /> : <Dashboard summary={summary} />}
  </>;
}

function Dashboard({ summary }: { summary: Summary }) {
  const metricCards = [
    ["Total emails", formatNumber(summary.metrics.total_emails), "All processed records", Mail, "text-cyan"],
    ["BL comparisons", formatNumber(summary.metrics.bl_comparisons), "Eligible verification requests", FileCheck2, "text-[#a78bfa]"],
    ["OK", formatNumber(summary.metrics.ok), "Verified without differences", CheckCircle2, "text-success"],
    ["MISMATCH", formatNumber(summary.metrics.mismatch), "Records with differing fields", FileWarning, "text-danger"],
    ["Needs review", formatNumber(summary.metrics.needs_review), "Evidence was not sufficient", CircleHelp, "text-warning"],
    ["Runtime", formatDuration(summary.metrics.runtime_seconds), `${formatNumber(summary.metrics.throughput)} emails / sec`, Clock3, "text-cyan"],
  ] as const;
  return <div className="space-y-6">
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {metricCards.map(([label, value, hint, Icon, accent]) => <article key={label} className="panel p-5"><div className="flex items-start justify-between"><p className="text-sm font-medium text-muted">{label}</p><Icon size={18} className={accent} /></div><p className="mt-5 text-3xl font-semibold tracking-tight text-ink">{value}</p><p className="mt-1 text-xs text-muted">{hint}</p></article>)}
    </section>
    <section className="grid gap-5 xl:grid-cols-2">
      <ChartPanel title="Email category distribution" subtitle="Classification output from the pipeline"><DonutChart data={summary.category_distribution} /></ChartPanel>
      <ChartPanel title="Verification outcomes" subtitle="BL comparison decisions only"><OutcomeChart data={summary.outcome_distribution} /></ChartPanel>
    </section>
    <section className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
      <div className="panel overflow-hidden"><div className="flex items-start justify-between border-b border-line p-5"><div><h2 className="font-semibold text-ink">Notable cases</h2><p className="mt-1 text-xs text-muted">Review and mismatch cases appear first.</p></div><Link href="/inbox" className="inline-flex items-center gap-1 text-xs font-medium text-cyan hover:text-[#7adcf6]">All inbox <ArrowUpRight size={14} /></Link></div><div className="overflow-x-auto"><table className="w-full min-w-[680px]"><thead><tr className="table-header"><th className="px-5 py-3">Email</th><th className="px-5 py-3">Subject</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Signal</th></tr></thead><tbody>{summary.notable_cases.map((item) => <tr className="table-row" key={item.email_id}><td className="px-5 py-3.5"><Link href={`/inbox/${item.email_id}`} className="font-mono text-xs text-cyan hover:underline">{item.email_id}</Link></td><td className="max-w-[290px] truncate px-5 py-3.5 text-sm text-ink" title={item.subject}>{item.subject || "No subject"}</td><td className="px-5 py-3.5"><StatusBadge status={item.status} /></td><td className="px-5 py-3.5 text-xs text-muted">{item.review_reason ? humanize(item.review_reason) : item.defect_count ? `${item.defect_count} differing field${item.defect_count === 1 ? "" : "s"}` : "No defect fields"}</td></tr>)}</tbody></table></div></div>
      <ChartPanel title="Review reason distribution" subtitle="The system stops when confidence is not supported by evidence."><ReviewChart data={summary.review_distribution} /></ChartPanel>
    </section>
    <section className="flex items-center gap-3 rounded-xl border border-line bg-raised/35 px-4 py-3 text-xs text-muted"><Gauge size={16} className="text-cyan" /><span>Source: <span className="font-medium text-ink">{summary.loader}</span></span><span className="hidden h-3 w-px bg-line sm:block" /><span className="hidden truncate sm:block" title={summary.source}>{summary.source}</span></section>
  </div>;
}

function ChartPanel({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) { return <section className="panel p-5"><h2 className="font-semibold text-ink">{title}</h2><p className="mt-1 text-xs text-muted">{subtitle}</p><div className="mt-4 h-64">{children}</div></section>; }

function DonutChart({ data }: { data: Distribution[] }) { return <ResponsiveContainer width="100%" height="100%"><PieChart><Tooltip contentStyle={tooltipStyle} formatter={(value, name) => [formatNumber(Number(value)), humanize(String(name))]} /><Pie data={data} dataKey="value" nameKey="name" innerRadius={65} outerRadius={95} paddingAngle={3}>{data.map((item, index) => <Cell key={item.name} fill={chartColors[index % chartColors.length]} />)}</Pie></PieChart></ResponsiveContainer>; }
function OutcomeChart({ data }: { data: Distribution[] }) { return <ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{ top: 10, right: 6, left: -14, bottom: 0 }}><XAxis dataKey="name" tickFormatter={humanize} tick={{ fill: "#91a4bf", fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis allowDecimals={false} tick={{ fill: "#91a4bf", fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip cursor={{ fill: "rgba(76,201,240,.06)" }} contentStyle={tooltipStyle} formatter={(value) => [formatNumber(Number(value)), "Emails"]} /><Bar dataKey="value" radius={[6, 6, 0, 0]}>{data.map((entry) => <Cell key={entry.name} fill={entry.name === "OK" ? "#46d8a3" : entry.name === "MISMATCH" ? "#ff7070" : "#f5b84b"} />)}</Bar></BarChart></ResponsiveContainer>; }
function ReviewChart({ data }: { data: Distribution[] }) { return data.length ? <ResponsiveContainer width="100%" height="100%"><BarChart data={data} layout="vertical" margin={{ top: 4, right: 20, left: 12, bottom: 4 }}><XAxis type="number" allowDecimals={false} tick={{ fill: "#91a4bf", fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis type="category" dataKey="name" tickFormatter={humanize} width={118} tick={{ fill: "#91a4bf", fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip cursor={{ fill: "rgba(76,201,240,.06)" }} contentStyle={tooltipStyle} formatter={(value) => [formatNumber(Number(value)), "Cases"]} labelFormatter={humanize} /><Bar dataKey="value" fill="#f5b84b" radius={[0, 6, 6, 0]} /></BarChart></ResponsiveContainer> : <DataState />; }
function DashboardSkeleton() { return <div className="space-y-5"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }, (_, index) => <div key={index} className="panel p-5"><div className="skeleton h-4 w-28" /><div className="skeleton mt-5 h-9 w-20" /><div className="skeleton mt-2 h-3 w-36" /></div>)}</div><div className="grid gap-5 xl:grid-cols-2"><div className="panel"><LoadingState rows={5} /></div><div className="panel"><LoadingState rows={5} /></div></div></div>; }
