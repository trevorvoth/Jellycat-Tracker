# Kristen's Jellycats

A phone-friendly website for logging Kristen's Jellycat collection with photos, plus a wishlist that friends and family can use to coordinate gifts.

- **Site:** plain HTML/CSS/JS (`index.html`, `styles.css`, `app.js`, `config.js`), no build step, hosted on GitHub Pages.
- **Data:** Supabase (free tier). The database schema, access rules and photo storage are all in `supabase/schema.sql`.

## Links

- **Kristen's link:** `https://trevorvoth.github.io/Jellycat-Tracker/`
- **Family link:** `https://trevorvoth.github.io/Jellycat-Tracker/?f=<family token>`

Anyone with either link can add and edit. Only the family link shows who has claimed which wishlist item; those claims are hidden from Kristen's link by the database itself, not just by the page. Keep the family link out of group chats she's in.

## Setup

1. Create a free Supabase project.
2. In Supabase → **SQL Editor** → **New query**, paste all of `supabase/schema.sql` and click **Run**.
3. Put the project URL and the anon (or publishable) key into `config.js`. The anon key is public by design: the access rules in the schema are what protect the data.
4. For the tests, copy `.env.example` to `.env` and fill it in. `.env` holds the service key and family token, is gitignored, and must never be committed.

### Re-running the schema

After changing `supabase/schema.sql`, paste the whole file into the SQL Editor again and run it. It is safe to re-run: tables, rows, photos and the family token are kept, while policies, functions and triggers are replaced. Supabase may warn about "destructive operations" because of the `drop policy` / `drop trigger` lines; that's expected.

## Family link: get it or change it

Get the current token (SQL Editor):

```sql
select family_token from settings;
```

If the family link leaks to Kristen, make a new token. The old link stops working immediately:

```sql
update settings
set family_token = replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '')
where id = 1
returning family_token;
```

Then update `FAMILY_TOKEN` in `.env` and send family the new link.

## Tests

Run these from the project folder. They need `.env`.

| Command | What it checks |
|---|---|
| `python tests/smoke_test.py` | Database rules, family functions, the "Got it!" trigger and photo upload limits (standard library only) |
| `python tests/seed.py` / `python tests/seed.py --clear` | Adds / removes about 8 sample Jellycats |
| `python tests/browser_test.py [screenshot_dir]` | Drives Microsoft Edge through the whole site (needs `pip install playwright pillow`) |

Every test cleans up its own `__test__` rows and photos.

To try the site locally: `python -m http.server 8000`, then open http://localhost:8000.

## Keep-alive

Free Supabase projects pause after about a week without traffic. `.github/workflows/keepalive.yml` reads one row every 3 days. It needs two repository secrets (GitHub → Settings → Secrets and variables → Actions): `SUPABASE_URL` and `SUPABASE_ANON_KEY`. You can run it by hand from the **Actions** tab.

## Known limits

- Anyone with a link can edit. Deleting only hides an item (`deleted_at`), so nothing is lost for good.
- If someone forwards Kristen the family link, she'll see claims. Change the token as shown above.
- Edits are last-write-wins.
