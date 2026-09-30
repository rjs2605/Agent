-- LeadPulse : run this once in Supabase -> SQL Editor -> New query -> Run.
-- Same tables as the build guide, plus: settings + automation_runs tables, and small columns:
--   companies.paused / companies.seq (pause + research in CSV order)
--   companies.last_error  (why a research run failed)
--   companies.status_updated_at (finds runs cut off by a timeout)
--   signals.event_date    (when the event happened; timing uses it)

create extension if not exists pgcrypto;

create table companies (
  id uuid primary key default gen_random_uuid(),
  name text,
  website text not null unique,
  status text default 'new',          -- new | queued | researching | researched | failed
  last_error text,
  status_updated_at timestamptz default now(),
  paused boolean default false,
  seq bigserial,
  created_at timestamptz default now()
);

create table snapshots (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies(id) on delete cascade,
  raw_pages jsonb,
  news jsonb,
  facts jsonb,
  created_at timestamptz default now()
);

create table briefs (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies(id) on delete cascade,
  snapshot_id uuid references snapshots(id) on delete cascade,
  brief jsonb,
  created_at timestamptz default now()
);

create table signals (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies(id) on delete cascade,
  type text,                           -- funding, hiring, leader, product, expansion, customer_win, pricing, other
  is_signal boolean,
  description text,
  source_url text,
  event_date date,
  detected_at timestamptz default now()
);

create table scores (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies(id) on delete cascade,
  fit int, timing int, reachability int, total numeric,
  reasons jsonb,
  created_at timestamptz default now()
);

create table contacts (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies(id) on delete cascade,
  name text, title text, profile_url text,
  rank int,
  reason text,
  confidence text,
  created_at timestamptz default now()
);

create table messages (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies(id) on delete cascade,
  contact_id uuid references contacts(id) on delete set null,
  subject text, body text,
  trigger_used text,
  created_at timestamptz default now()
);

create table actions (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies(id) on delete cascade,
  action text,                         -- done | snooze | not_relevant
  snooze_until date,
  created_at timestamptz default now()
);

create table settings (
  key text primary key,
  value jsonb,
  updated_at timestamptz default now()
);

create table automation_runs (
  id uuid primary key default gen_random_uuid(),
  trigger text,
  started_at timestamptz default now(),
  finished_at timestamptz,
  queued int default 0,
  researched int default 0,
  failed int default 0,
  note text
);

alter table companies enable row level security;
alter table settings  enable row level security;
alter table automation_runs enable row level security;
alter table snapshots enable row level security;
alter table briefs    enable row level security;
alter table signals   enable row level security;
alter table scores    enable row level security;
alter table contacts  enable row level security;
alter table messages  enable row level security;
alter table actions   enable row level security;
