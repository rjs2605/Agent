-- LeadPulse update: run this ONCE in Supabase -> SQL Editor -> New query -> Run
-- (only if you already ran the old schema.sql; a fresh setup just runs schema.sql)

alter table companies add column if not exists status_updated_at timestamptz default now();
alter table companies add column if not exists paused boolean default false;
alter table companies add column if not exists seq bigserial;

create table if not exists settings (
  key text primary key,
  value jsonb,
  updated_at timestamptz default now()
);

create table if not exists automation_runs (
  id uuid primary key default gen_random_uuid(),
  trigger text,
  started_at timestamptz default now(),
  finished_at timestamptz,
  queued int default 0,
  researched int default 0,
  failed int default 0,
  note text
);

alter table settings enable row level security;
alter table automation_runs enable row level security;

-- companies that stopped mid-research go back to the queue
update companies set status = 'queued' where status = 'researching';
