export function PageHeading({ eyebrow, title, children }: { eyebrow: string; title: string; children: React.ReactNode }) {
  return <div className="mb-7"><p className="eyebrow">{eyebrow}</p><h1 className="page-title">{title}</h1><div className="page-copy">{children}</div></div>;
}
