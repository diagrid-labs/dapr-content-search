# Dapr Community Content Search — Automation Plan

## Overview and Goals

This document describes the design and implementation plan for a Python automation
script that searches three social platforms for community content mentioning Dapr
(the CNCF distributed application runtime). The script is intended to replace the
current manual search workflow documented in `community-content.md`.

**Goals:**
- Automate discovery of Dapr-related posts on X (Twitter), LinkedIn, and Bluesky
- Support configurable keywords, date ranges, and per-platform exclusion terms
- Persist authenticated browser sessions so repeated headless runs require no manual login
- Emit results as a Markdown table that will be saved to a file named `YYYY-MM-DD-community-content.md` where YYYY-MM-DD is the current date.

**Non-goals:**
- YouTube and DEV.to/Medium are deliberately excluded from this automation; they are
  reachable without authentication and can be searched manually or in a follow-up script

---

## Dependencies and Installation

### Python version

Python 3.11 or higher is required.

### Runtime dependencies

| Package | Purpose |
|---|---|
| `playwright` | Browser automation for X and LinkedIn |
| `httpx` | Async HTTP client for the Bluesky AT Protocol REST API |
| `python-dateutil` | Flexible date parsing for `--since` / `--until` CLI flags |
| `tabulate` | Renders the Markdown table from a list of result dicts |

### Package manager

[uv](https://docs.astral.sh/uv/) is required. Install it with:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS / Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"  # Windows
```

### Installation steps

1. Initialise the project and sync dependencies (uv creates the virtualenv automatically):

   ```bash
   cd community-search
   uv sync
   ```

2. Install the Playwright browser binaries (Chromium is sufficient):

   ```bash
   uv run playwright install chromium
   ```

3. Run the script via uv so it always uses the managed environment:

   ```bash
   uv run search.py --platform bluesky
   ```

### `pyproject.toml` content

```toml
[project]
name = "community-search"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "playwright>=1.44",
    "httpx>=0.27",
    "python-dateutil>=2.9",
    "tabulate>=0.9",
]
```

---

## Project File Structure

```
community-search/
├── auth/                        # git-ignored; holds saved Playwright state files
│   ├── x_state.json             # created by: python search.py --auth x
│   └── linkedin_state.json      # created by: python search.py --auth linkedin
├── platforms/
│   ├── __init__.py
│   ├── x.py                     # X (Twitter) scraper
│   ├── linkedin.py              # LinkedIn scraper
│   └── bluesky.py               # Bluesky AT Protocol client
├── config.py                    # All configurable values
├── search.py                    # CLI entry point
└── pyproject.toml
```

Add the following line to the repository `.gitignore`:

```
community-search/auth/
```

---

## Config Schema (`config.py`)

`config.py` is the single authoritative source for all tunable values. No platform
module should hardcode any keyword, date, or URL.

### Full example with annotations

```python
# config.py

from datetime import date

# ---------------------------------------------------------------------------
# Date range
# ---------------------------------------------------------------------------
# Default values used when --since / --until are not supplied on the CLI.
SINCE_DATE: date = date(2026, 3, 2)
UNTIL_DATE: date = date(2026, 4, 2)

# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------
# Each entry becomes a separate search query; results are merged and
# deduplicated by URL.
SEARCH_KEYWORDS: list[str] = [
    "Dapr",
    "Dapr Workflow",
    "Dapr Agents",
    "dapr.io",
]

# ---------------------------------------------------------------------------
# Per-platform exclusion keywords
# ---------------------------------------------------------------------------
# X supports native query negation (e.g. -gamer). For LinkedIn and Bluesky,
# exclusions are applied as a post-processing filter on the result text.
EXCLUSIONS: dict[str, list[str]] = {
    "x": ["gamer", "gaming", "stream", "twitch", "streamer"],
    "linkedin": ["gamer", "gaming", "stream", "twitch"],
    "bluesky": ["gamer", "gaming", "stream", "twitch"],
}

# ---------------------------------------------------------------------------
# Platform-specific settings
# ---------------------------------------------------------------------------

X_LANGUAGE_FILTER: str = "en"          # appended as lang:en to every X query
X_EXCLUDE_RETWEETS: bool = True        # if True, append -filter:retweets
X_MAX_SCROLL_ATTEMPTS: int = 15        # how many infinite-scroll iterations
X_SCROLL_PAUSE_SECONDS: float = 2.5    # seconds to wait after each scroll

LINKEDIN_MAX_SCROLL_ATTEMPTS: int = 10
LINKEDIN_SCROLL_PAUSE_SECONDS: float = 3.0

BLUESKY_API_BASE: str = "https://public.api.bsky.app/xrpc"
BLUESKY_SEARCH_ENDPOINT: str = "app.bsky.feed.searchPosts"
BLUESKY_MAX_PAGES: int = 5             # maximum cursor-paginated pages to fetch
BLUESKY_PAGE_LIMIT: int = 25          # posts per page (API max is 25)

# ---------------------------------------------------------------------------
# Auth state file paths
# ---------------------------------------------------------------------------
AUTH_DIR: str = "auth"
X_AUTH_STATE_FILE: str = f"{AUTH_DIR}/x_state.json"
LINKEDIN_AUTH_STATE_FILE: str = f"{AUTH_DIR}/linkedin_state.json"
```

---

## Auth Setup Flow

Both X and LinkedIn require an authenticated browser session. Playwright supports
saving the full browser storage state (cookies, localStorage, sessionStorage) to a
JSON file and restoring it in later runs.

### How it works

On first run with `--auth <platform>`, Playwright launches a **visible** (non-headless)
Chromium window. The user logs in manually. When they close the browser or press
Enter in the terminal, Playwright serialises the browser context's storage state to
the JSON file. Subsequent `--platform` runs load that JSON file into a new headless
browser context — no login prompt appears.

### Step-by-step: X

1. Run: `uv run search.py --auth x`
2. Chromium opens to `https://x.com/login`
3. Complete the login form manually (username → password → 2FA if enabled)
4. Wait until the home timeline is visible (confirms login succeeded)
5. Close the browser window or press Enter in the terminal
6. The script calls `context.storage_state(path=X_AUTH_STATE_FILE)` and writes `auth/x_state.json`

### Step-by-step: LinkedIn

1. Run: `uv run search.py --auth linkedin`
2. Chromium opens to `https://www.linkedin.com/login`
3. Complete the login form (email → password → any 2FA challenge)
4. Wait until the LinkedIn feed is visible
5. Close the browser window or press Enter
6. The script writes `auth/linkedin_state.json`

### Re-authentication

Auth state files expire (X sessions typically last weeks; LinkedIn sessions can last
months). If a scraper run detects a redirect to a login page, it should:

1. Log a warning: `"Session expired for <platform>. Re-run: uv run search.py --auth <platform>"`
2. Return an empty results list for that platform rather than crashing

---

## Per-Platform Implementation Details

### 1. X (Twitter) — `platforms/x.py`

#### Authentication

Load `auth/x_state.json` into `browser.new_context(storage_state=...)`. If the file
does not exist, raise a `FileNotFoundError` with a helpful message directing the user
to run `--auth x`.

#### Search URL construction

For each keyword in `SEARCH_KEYWORDS`, build a URL of this form:

```
https://x.com/search?q=<encoded_query>&src=typed_query&f=live
```

The `f=live` parameter selects the "Latest" tab (chronological order), critical for
date-filtered results. Assemble the query string from config values:

- Base term: e.g. `Dapr`
- Language filter: `lang:en` (from `X_LANGUAGE_FILTER`)
- Date lower bound: `since:YYYY-MM-DD`
- Date upper bound: `until:YYYY-MM-DD`
- Retweet exclusion (if enabled): `-filter:retweets`
- Per-platform exclusions from `EXCLUSIONS["x"]`, each prefixed with `-`

Full assembled example:
```
Dapr lang:en since:2026-03-02 until:2026-04-02 -filter:retweets -gamer -gaming -stream -twitch
```

#### Pagination / infinite scroll

X results load dynamically as the user scrolls. The scraper must:

1. Navigate to the search URL and wait for `article[data-testid="tweet"]` to appear
2. Enter a scroll loop up to `X_MAX_SCROLL_ATTEMPTS` times:
   - Record the current tweet article count
   - Execute `window.scrollTo(0, document.body.scrollHeight)` via `page.evaluate(...)`
   - Wait `X_SCROLL_PAUSE_SECONDS` for new content to load
   - If the count is unchanged, the feed is exhausted — break
3. Collect all visible tweet articles

#### Data extraction per tweet

| Field | Selector / method |
|---|---|
| Author display name | `[data-testid="User-Name"] span:first-child` |
| Author handle | `[data-testid="User-Name"] a[href^="/"]` — extract path as `@handle` |
| Tweet text | `[data-testid="tweetText"]` — inner text |
| Timestamp | `time` element — read the `datetime` attribute (ISO 8601) |
| Tweet URL | `a[href*="/status/"]` — first match; prefix with `https://x.com` if relative |
| Type | `"Post"` by default; `"Post with link"` if a card/link embed is detected |

Post-processing: discard posts outside `[SINCE_DATE, UNTIL_DATE]` and posts whose
text matches any word in `EXCLUSIONS["x"]`. Deduplicate by URL across keyword queries.

---

### 2. LinkedIn — `platforms/linkedin.py`

#### Authentication

Load `auth/linkedin_state.json` into `browser.new_context(storage_state=...)`. Check
for redirect to `/login` after navigation; if detected, surface the re-auth warning
and return `[]`.

#### Search navigation

LinkedIn's post search URL:

```
https://www.linkedin.com/search/results/content/?keywords=<encoded_term>&datePosted=past-month&sortBy=date_posted
```

Key parameters:
- `keywords` — URL-encoded search term
- `datePosted` — use `past-month`; applies to the last 30 days
- `sortBy` — `date_posted` for newest-first ordering

If `SINCE_DATE` is older than 30 days from today, the `past-month` filter is
insufficient. In that case, interact with the LinkedIn UI filter:

1. Click "All filters"
2. Select the appropriate "Date posted" option
3. Apply the filter

#### Pagination / infinite scroll

1. Wait for `li.reusable-search__result-container` or `div[data-chameleon-result-urn]`
2. Scroll loop up to `LINKEDIN_MAX_SCROLL_ATTEMPTS`:
   - Record element count
   - Scroll to bottom
   - Wait `LINKEDIN_SCROLL_PAUSE_SECONDS` (keep at 3.0+ to avoid rate limiting)
   - Break if count is unchanged

#### Data extraction per post

| Field | Selector / approach |
|---|---|
| Author name | `.update-components-actor__name` |
| Post text | `.update-components-text` — truncated to 200 chars |
| Timestamp | `.update-components-actor__sub-description` — relative time string |
| Post URL | `a.app-aware-link[href*="/feed/update/"]` — extract `urn:li:activity:NNNN` |
| Type | `"Post"` default; `"Article share"` if `update-components-article` is present |

LinkedIn shows relative timestamps ("3 days ago", "1 week ago"). Convert to absolute
dates:
- `Xd ago` → `today - timedelta(days=X)`
- `Xw ago` → `today - timedelta(weeks=X)`
- `Xmo ago` → `today - timedelta(days=X*30)`

Discard posts whose resolved date falls outside `[SINCE_DATE, UNTIL_DATE]`. Apply
exclusion filter on post text. Deduplicate by URL.

---

### 3. Bluesky — `platforms/bluesky.py`

#### Endpoint

No browser automation needed. Uses the AT Protocol public API:

```
GET https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts
```

No authentication header required. Use `httpx.AsyncClient`.

#### Request parameters

| Parameter | Type | Notes |
|---|---|---|
| `q` | string | Search term (e.g. `"Dapr"`) |
| `limit` | integer | Results per page; max 25 — use `BLUESKY_PAGE_LIMIT` |
| `cursor` | string | Pagination cursor from previous response; omit for first page |
| `since` | string | ISO 8601: `SINCE_DATE.isoformat() + "T00:00:00Z"` |
| `until` | string | ISO 8601: `UNTIL_DATE.isoformat() + "T23:59:59Z"` |
| `lang` | string | `"en"` to filter by language |

#### Pagination

```json
{
  "posts": [ ... ],
  "cursor": "<opaque string or absent>"
}
```

Loop: send request → collect posts → if `"cursor"` present and pages fetched <
`BLUESKY_MAX_PAGES`, send next request with `cursor=<value>` → stop when cursor
is absent.

#### Response fields to extract per post

| Field | JSON path | Notes |
|---|---|---|
| Author name | `post.author.displayName` | Fall back to handle if empty |
| Author handle | `post.author.handle` | e.g. `user.bsky.social` |
| Post text | `post.record.text` | Raw post text |
| Timestamp | `post.record.createdAt` | ISO 8601 string |
| Post URI | `post.uri` | AT URI: `at://did:plc:.../app.bsky.feed.post/<rkey>` |
| Post URL | Constructed | `https://bsky.app/profile/{handle}/post/{rkey}` |
| Type | `"Post"` default | `"Post with link"` if `post.embed.$type` is `app.bsky.embed.external#view` |

Construct the URL by splitting `post.uri` on `/` (last segment = `rkey`) and using
`post.author.handle`.

Apply date filter on `createdAt` and exclusion filter on post text. Deduplicate by URL.

---

## CLI Design (`search.py`)

```
usage: search.py [-h] [--all] [--platform {x,linkedin,bluesky}]
                 [--auth {x,linkedin}]
                 [--since SINCE] [--until UNTIL]
                 [--output OUTPUT]
```

### Flags

| Flag | Type | Description |
|---|---|---|
| `--all` | store_true | Run all three platforms and merge results |
| `--platform` | choices | Run a single platform: `x`, `linkedin`, or `bluesky` |
| `--auth` | choices | Auth setup mode for `x` or `linkedin`; launches visible browser |
| `--since` | string | Override `SINCE_DATE`; format `YYYY-MM-DD` |
| `--until` | string | Override `UNTIL_DATE`; format `YYYY-MM-DD` |
| `--output` | string | Append results in Markdown table format to this file |

### Mutual exclusivity

- `--all` and `--platform` are mutually exclusive
- `--auth` is mutually exclusive with `--all` and `--platform`
- If none of the three mode flags is provided, print usage and exit with code 1

### Runtime flow

```
parse args
→ if --since or --until supplied, parse with dateutil and override config values
→ if --auth:
    call auth_setup(platform)
    exit 0
→ determine platforms list:
    if --all:      ["x", "linkedin", "bluesky"]
    if --platform: [<value>]
→ for each platform:
    call run_<platform>(since, until)
    collect list of result dicts
→ merge results; deduplicate by URL across platforms
→ sort by date descending
→ render Markdown table with tabulate
→ print to stdout
→ if --output: append table to file
```

---

## Output Format and File Appending Behavior

### Result dict schema

All platform modules must return results with this exact shape:

```python
{
    "date": "YYYY-MM-DD",
    "author": "Display Name (@handle)",
    "text": "Truncated post text...",
    "url": "https://...",
    "type": "Post",
    "platform": "x" | "linkedin" | "bluesky"   # for diagnostics, not rendered
}
```

### Markdown table columns

| Column | Source field | Notes |
|---|---|---|
| Date | `date` | `YYYY-MM-DD` |
| Author | `author` | `Display Name (@handle)` |
| Title/Text | `text` | Truncated to 120 characters |
| URL | `url` | Full permalink |
| Type | `type` | `Post`, `Post with link`, `Article share`, etc. |

Use `tabulate(rows, headers=headers, tablefmt="github")` for GitHub-flavoured
Markdown output.

### File appending

When `--output <path>` is provided:

1. Open in append mode (`"a"`)
2. Write: `\n\n## Dapr Community Content — {SINCE_DATE} to {UNTIL_DATE}\n\n`
3. Write the Markdown table
4. Close the file

Always print the table to stdout regardless of `--output`.

---

## Implementation Steps (Ordered Checklist)

### Phase 1 — Scaffolding

- [ ] Create `community-search/` directory
- [ ] Create `community-search/auth/` directory
- [ ] Add `community-search/auth/` to `.gitignore`
- [ ] Create `community-search/platforms/__init__.py` (empty)
- [ ] Create `pyproject.toml` with content from the Dependencies section
- [ ] Run `uv sync` to create the virtualenv and install dependencies
- [ ] Create `config.py` with all values from the Config Schema section

### Phase 2 — Bluesky (no browser, simplest)

- [ ] Implement `platforms/bluesky.py`:
  - [ ] `async def search_bluesky(keyword, since, until) -> list[dict]`
    - Builds request params from config
    - Sends GET with `httpx.AsyncClient`
    - Paginates via cursor loop up to `BLUESKY_MAX_PAGES`
    - Extracts fields, constructs URL from handle + rkey
    - Applies date and exclusion filters
  - [ ] `async def run_bluesky(since, until) -> list[dict]`
    - Iterates `SEARCH_KEYWORDS`, merges and deduplicates by URL
- [ ] Test: `uv run search.py --platform bluesky`

### Phase 3 — Auth infrastructure (shared by X and LinkedIn)

- [ ] Implement `auth_setup(platform: str)` in `search.py`:
  - Launches Playwright in headed mode
  - Navigates to platform login URL
  - Waits for user to press Enter
  - Saves storage state to the appropriate auth file
  - Prints confirmation
- [ ] Test: `uv run search.py --auth x` → verify `auth/x_state.json` created
- [ ] Test: `uv run search.py --auth linkedin` → verify `auth/linkedin_state.json` created

### Phase 4 — X scraper

- [ ] Implement `platforms/x.py`:
  - [ ] `def build_x_query(keyword, since, until) -> str`
  - [ ] `async def scrape_x(keyword, since, until, playwright_instance) -> list[dict]`
    - Loads auth state; raises `FileNotFoundError` with helpful message if missing
    - Navigates to search URL; detects login redirect and returns `[]`
    - Runs scroll loop; extracts tweet data
    - Applies date and exclusion filters
  - [ ] `async def run_x(since, until) -> list[dict]`
- [ ] Test: `uv run search.py --platform x`

### Phase 5 — LinkedIn scraper

- [ ] Implement `platforms/linkedin.py`:
  - [ ] `def build_linkedin_url(keyword, since) -> str`
    - Uses `datePosted=past-month` if `since` is within last 30 days, otherwise flags for UI interaction
  - [ ] `async def scrape_linkedin(keyword, since, until, playwright_instance) -> list[dict]`
    - Loads auth state; raises `FileNotFoundError` with helpful message if missing
    - Navigates to search URL; applies UI filter if needed
    - Detects login redirect and returns `[]`
    - Runs scroll loop; extracts post data
    - Parses relative timestamps to absolute dates
    - Applies date and exclusion filters
  - [ ] `async def run_linkedin(since, until) -> list[dict]`
- [ ] Test: `uv run search.py --platform linkedin`

### Phase 6 — CLI wiring and output

- [ ] Implement full `search.py` with argparse
- [ ] `render_table(results) -> str` using `tabulate`
- [ ] `append_to_file(path, since, until, table_str)`
- [ ] Wire `--since` / `--until` to override config before passing to runners
- [ ] Test: `uv run search.py --all`
- [ ] Test: `uv run search.py --all --output community-content.md`
- [ ] Test: `uv run search.py --platform bluesky --since 2026-03-01 --until 2026-03-31`

### Phase 7 — Hardening

- [ ] Wrap each platform runner in `try/except` so one failure doesn't abort the others
- [ ] Validate `SINCE_DATE < UNTIL_DATE`; exit with error if not
- [ ] Handle Bluesky HTTP 4xx/5xx with informative error messages
- [ ] Handle Playwright `TimeoutError` during scroll with a logged warning (not a crash)
- [ ] Add `--verbose` flag for debug-level logging (navigation steps, element counts per scroll)

---

## Notes for the Implementer

- Playwright selectors for X and LinkedIn are fragile. Comment each selector
  explaining what it targets so future breakage is easy to diagnose.
- LinkedIn's anti-bot mitigations are more aggressive than X's. If sessions get
  blocked, increase `LINKEDIN_SCROLL_PAUSE_SECONDS` and consider adding random
  mouse movements between scrolls using `page.mouse.move(...)`.
- Implement Bluesky first to establish the result dict schema that all platform
  modules must conform to.
- The `platform` field in the result dict is for diagnostics only and is not
  rendered in the Markdown table output.
