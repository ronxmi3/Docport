"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { BarChart3, FileBarChart2, Inbox, Menu, ShieldCheck, X } from "lucide-react";
import { useState } from "react";
import { RunVerificationButton } from "@/components/run-verification-button";

const navigation = [
  { href: "/", label: "Overview", icon: BarChart3 },
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/review", label: "Review queue", icon: ShieldCheck },
  { href: "/reports", label: "Reports", icon: FileBarChart2 },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const active = navigation.find((item) => item.href === "/" ? pathname === "/" : pathname.startsWith(item.href))?.label ?? "Averis";

  return (
    <div className="min-h-screen bg-canvas">
      {open && <button className="fixed inset-0 z-30 bg-black/60 lg:hidden" aria-label="Close navigation" onClick={() => setOpen(false)} />}
      <aside className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-line bg-[#0c1727] px-4 py-5 transition-transform lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="flex items-center justify-between px-2">
          <Link href="/" className="flex items-center gap-3" onClick={() => setOpen(false)}>
            <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-cyan/30 bg-cyan/10 text-cyan"><ShieldCheck size={21} /></span>
            <span><span className="block text-sm font-semibold tracking-wide text-ink">AVERIS</span><span className="block text-[10px] uppercase tracking-[0.18em] text-muted">Shipping intelligence</span></span>
          </Link>
          <button className="icon-button lg:hidden" onClick={() => setOpen(false)} aria-label="Close navigation"><X size={18} /></button>
        </div>
        <nav className="mt-10 space-y-1" aria-label="Main navigation">
          {navigation.map(({ href, label, icon: Icon }) => {
            const selected = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return <Link key={href} href={href} onClick={() => setOpen(false)} className={`flex items-center gap-3 rounded-xl px-3 py-3 text-sm transition ${selected ? "bg-cyan/10 text-cyan" : "text-muted hover:bg-raised hover:text-ink"}`}><Icon size={18} />{label}</Link>;
          })}
        </nav>
        <div className="mt-auto rounded-xl border border-line bg-panel p-4">
          <p className="text-xs font-semibold text-ink">Verification principle</p>
          <p className="mt-2 text-xs leading-5 text-muted">Clear mismatches are flagged. Uncertain evidence is routed to review.</p>
        </div>
      </aside>
      <div className="min-h-screen lg:pl-72">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-line bg-canvas/95 px-4 backdrop-blur sm:px-7">
          <div className="flex items-center gap-3"><button className="icon-button lg:hidden" onClick={() => setOpen(true)} aria-label="Open navigation"><Menu size={19} /></button><span className="text-sm font-medium text-muted">{active}</span></div>
          <RunVerificationButton />
        </header>
        <motion.main initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className="mx-auto max-w-[1600px] px-4 py-7 sm:px-7 sm:py-9">{children}</motion.main>
      </div>
    </div>
  );
}
