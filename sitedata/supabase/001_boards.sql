-- Published subnt.dev boards (change: supabase-data-layer). One row per
-- board, replaced whole by the Pi publisher. Public read, no public write:
-- row-level security is on, the only policy allows SELECT, and the
-- publisher writes with the secret key, which bypasses RLS.

create table if not exists public.boards (
  name text primary key
    check (name in ('mining', 'fleet', 'network', 'upgrades')),
  generated_at timestamptz not null,
  data jsonb not null,
  content_hash text not null,
  published_at timestamptz not null default now()
);

alter table public.boards enable row level security;

drop policy if exists "boards are public" on public.boards;
create policy "boards are public" on public.boards
  for select to anon, authenticated using (true);

-- Belt and braces: the public roles hold no write privilege at all.
revoke insert, update, delete, truncate on public.boards from anon, authenticated;
grant select on public.boards to anon, authenticated;
