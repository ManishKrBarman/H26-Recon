import './globals.css';
import Link from 'next/link';

export const metadata = {
  title: 'ReconAI — Intelligent Tax Reconciliation & Investigation',
  description: 'AI-powered financial reconciliation, anomaly detection, pattern intelligence and human-in-the-loop review platform.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <header className="topbar">
            <Link href="/" className="brand">
              Recon<span>AI</span>
            </Link>
            <nav className="nav">
              <Link href="/">Dashboard</Link>
              <Link href="/cases">Investigations</Link>
              <Link href="/patterns">Patterns</Link>
            </nav>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
