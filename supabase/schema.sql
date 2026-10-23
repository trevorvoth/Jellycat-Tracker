-- Jellycat Tracker schema. Paste into Supabase → SQL Editor → Run.
-- Safe to re-run: tables/rows are kept, policies and functions are replaced.

-- ───────────── Tables ─────────────

create table if not exists public.jellycats (
  id            uuid primary key default gen_random_uuid(),
  name          text not null check (length(trim(name)) between 1 and 120),
  nickname      text check (length(nickname) <= 120),
  size          text check (length(size) <= 40),
  category      text check (length(category) <= 60),
  status        text not null default 'owned' check (status in ('owned', 'wishlist')),
  acquired_date date,
  acquired_from text check (length(acquired_from) <= 120),
  notes         text check (length(notes) <= 2000),
  photo_path    text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  deleted_at    timestamptz  -- soft delete: set to hide, clear to undo
);

-- One claim per wishlist item. Never readable directly; only via the token-checked functions below.
create table if not exists public.claims (
  id          uuid primary key default gen_random_uuid(),
  jellycat_id uuid not null unique references public.jellycats(id) on delete cascade,
  claimed_by  text not null check (length(trim(claimed_by)) between 1 and 60),
  created_at  timestamptz not null default now()
);

-- Single row holding the secret that unlocks family view.
create table if not exists public.settings (
  id           int primary key default 1 check (id = 1),
  family_token text not null default replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '')
);
insert into public.settings (id) values (1) on conflict (id) do nothing;

-- ───────────── Row Level Security ─────────────

alter table public.jellycats enable row level security;
alter table public.claims    enable row level security;
alter table public.settings  enable row level security;

-- Anyone with the link can view, add and edit. No delete policy: deleting = setting deleted_at.
drop policy if exists "anyone can read jellycats"   on public.jellycats;
drop policy if exists "anyone can add jellycats"    on public.jellycats;
drop policy if exists "anyone can edit jellycats"   on public.jellycats;
create policy "anyone can read jellycats" on public.jellycats for select to anon, authenticated using (true);
create policy "anyone can add jellycats"  on public.jellycats for insert to anon, authenticated with check (true);
create policy "anyone can edit jellycats" on public.jellycats for update to anon, authenticated using (true) with check (true);

-- claims and settings: RLS on with no policies, plus no table privileges → fully closed to the public API.
revoke all on public.claims   from anon, authenticated;
revoke all on public.settings from anon, authenticated;

-- ───────────── Triggers ─────────────

create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists jellycats_touch_updated_at on public.jellycats;
create trigger jellycats_touch_updated_at before update on public.jellycats
  for each row execute function public.touch_updated_at();

-- "Got it!" — once an item is owned, its gift claim is no longer needed.
-- The claimer's name is kept as "Gift from <name>" in acquired_from (unless that's already filled in).
create or replace function public.clear_claims_when_owned() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  giver text;
begin
  if new.status = 'owned' and old.status <> 'owned' then
    delete from claims where jellycat_id = new.id returning claimed_by into giver;
    if giver is not null and coalesce(trim(new.acquired_from), '') = '' then
      new.acquired_from := 'Gift from ' || giver;
    end if;
  end if;
  return new;
end $$;

drop trigger if exists jellycats_clear_claims_when_owned on public.jellycats;
create trigger jellycats_clear_claims_when_owned before update of status on public.jellycats
  for each row execute function public.clear_claims_when_owned();

-- ───────────── Family functions (token-checked) ─────────────
-- security definer = runs with owner rights, so it can read claims/settings that the public API can't.

create or replace function public.check_family_token(p_token text) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from settings where family_token = p_token);
$$;

create or replace function public.get_claims(p_token text)
returns table (jellycat_id uuid, claimed_by text, created_at timestamptz)
language plpgsql stable security definer set search_path = public as $$
#variable_conflict use_column
begin
  if not check_family_token(p_token) then
    raise exception 'invalid family token' using errcode = '28000';
  end if;
  return query select c.jellycat_id, c.claimed_by, c.created_at from claims c;
end $$;

create or replace function public.claim_item(p_token text, p_jellycat_id uuid, p_name text) returns void
language plpgsql security definer set search_path = public as $$
declare
  inserted int;
begin
  if not check_family_token(p_token) then
    raise exception 'invalid family token' using errcode = '28000';
  end if;
  if not exists (select 1 from jellycats
                 where id = p_jellycat_id and status = 'wishlist' and deleted_at is null) then
    raise exception 'not a wishlist item' using errcode = 'P0002';
  end if;
  insert into claims (jellycat_id, claimed_by) values (p_jellycat_id, trim(p_name))
    on conflict (jellycat_id) do nothing;
  get diagnostics inserted = row_count;
  if inserted = 0 then
    raise exception 'already claimed' using errcode = '23505';
  end if;
end $$;

create or replace function public.unclaim_item(p_token text, p_jellycat_id uuid) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not check_family_token(p_token) then
    raise exception 'invalid family token' using errcode = '28000';
  end if;
  delete from claims where jellycat_id = p_jellycat_id;
end $$;

grant execute on function public.check_family_token(text)            to anon, authenticated;
grant execute on function public.get_claims(text)                    to anon, authenticated;
grant execute on function public.claim_item(text, uuid, text)        to anon, authenticated;
grant execute on function public.unclaim_item(text, uuid)            to anon, authenticated;

-- ───────────── Photo storage ─────────────
-- Public bucket: anyone can view photos by URL. Uploads limited to 2 MB images.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('photos', 'photos', true, 2097152, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "anyone can upload photos" on storage.objects;
create policy "anyone can upload photos" on storage.objects for insert to anon, authenticated
  with check (bucket_id = 'photos');

-- Your family link token (copy into .env as FAMILY_TOKEN):
select family_token from public.settings;
