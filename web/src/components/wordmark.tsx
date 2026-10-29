import Link from "next/link";

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <Link href="/" className={`inline-flex items-center gap-2 text-lead font-bold tracking-tight ${className}`}>
      <span className="cell" aria-hidden="true" />
      Atlas
    </Link>
  );
}
