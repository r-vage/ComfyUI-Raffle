# dev/ — Raffle List Update Pipeline

This folder contains all tools for updating the two runtime list files used by the Raffle node:

| Runtime file | Purpose |
|---|---|
| `../lists/categorized_tags.txt` | Category lookup — maps each tag to a category |
| `../lists/taglists-*.txt` | Post taglists — one line per Danbooru post, all its tags |

---

## Shared Config

**`dev/config.ini`** — used by both scrapers.

```ini
[danbooru]
username = your_username
api_key  = your_api_key

[scraper]
score_min        = 1       # Floor — score range halves down to this
score_max_start  = 10000   # Starting ceiling (posts top out ~2730)
tags_per_request = 200     # Max per API call
pause_interval   = 1.0     # Seconds between requests
max_runs         = 0       # 0 = run forever until Ctrl+C
min_count        = 100     # tag-scraper only: min post count for a tag
```

Copy `config.ini.example` to `config.ini` and fill in your credentials (created automatically on first run if missing).

---

## Pipeline A — Update `categorized_tags.txt`

Updates the tag→category lookup used to filter the Raffle output.

### Step 1 — Scrape the Danbooru tag index

```bash
cd dev/tag-scraper
python3 tag-scraper.py
```

Calls `/tags.json` and writes one tag per line into `tag_lists/`:
- `general.txt`, `artist.txt`, `copyright.txt`, `character.txt`, `meta.txt`, `all_tags.txt`

### Step 2 — Clean the tag list

```bash
cd dev
python3 remove-numbers-at-end-of-each-line.py tag-scraper/tag_lists/general.txt
# Output: tag-scraper/tag_lists/all_tags_cleaned.txt (or similar)
```

Strips trailing post-count numbers Danbooru appends to tag names.

### Step 3 — Find new tags not yet in categorized_tags.txt

```bash
cd dev
python3 check-missing-tags.py
```

Produces a list of tags present in the scraped data but missing from `../lists/categorized_tags.txt`.

### Step 4 — Split into chunks for categorization

```bash
cd dev/categorizer/split_n_combine
python3 split_and_combine_script.py ../../copy_work/uncategorized_only.txt
# Creates: 1_uncategorized.txt, 2_uncategorized.txt, ... N_uncategorized.txt
```

### Step 5 — Categorize each chunk

Each `N_uncategorized.txt` chunk contains ~150 tags with `[UNCATEGORIZED]` prefix.
Manually or AI-assisted: replace `[UNCATEGORIZED]` with the correct `[category_name]`.
Save output as `N_categorized.txt` in the same folder.

Available categories are listed at the top of `categorized_tags.txt`.

### Step 6 — Combine categorized chunks

```bash
cd dev/categorizer/split_n_combine
python3 split_and_combine_script.py --combine
# Output: categorized_combined.txt
```

### Step 7 — Merge into the main file

```bash
cd dev
python3 swap-in-new-categories.py
# Merges categorized_combined.txt into copy_work/new-general-categorized-final.txt
```

### Step 8 — Ship

```bash
cp dev/copy_work/new-general-categorized-final.txt lists/categorized_tags.txt
```

---

## Pipeline B — Update `taglists-*.txt`

Updates the pool of actual Danbooru posts the Raffle node randomly selects from.

### Step 1 — Scrape posts

```bash
cd dev/taglist-scraper
python3 danbooru-taglist-scraper.py
```

- Calls `/posts.json` with `rating:g/s/q/e order:random` filters
- Fetches 200 posts per request, deduplicates by post ID
- Always fills the rating with the fewest entries first (keeps them balanced)
- Score range starts at `(score_max_start/2, score_max_start)` and halves down automatically when a band is exhausted
- Falls back to `order:score` when `order:random` returns 0 (happens on narrow high-score bands)
- Writes to `output_scraped/general.txt`, `sensitive.txt`, `questionable.txt`, `explicit.txt`
- Each line: `post_id, score, tag1, tag2, tag3, ...`

Press **Ctrl+C** to stop when you have enough posts (~18k per rating is plenty; original had 100k).

### Step 2 — Sort by score descending

```bash
cd dev/taglist-scraper
python3 rearranger.py output_scraped/general.txt output_scraped/general_sorted.txt
python3 rearranger.py output_scraped/sensitive.txt output_scraped/sensitive_sorted.txt
python3 rearranger.py output_scraped/questionable.txt output_scraped/questionable_sorted.txt
python3 rearranger.py output_scraped/explicit.txt output_scraped/explicit_sorted.txt
```

### Step 3 — Ship

```bash
cp dev/taglist-scraper/output_scraped/general_sorted.txt    lists/taglists-general.txt
cp dev/taglist-scraper/output_scraped/sensitive_sorted.txt  lists/taglists-sensitive.txt
cp dev/taglist-scraper/output_scraped/questionable_sorted.txt lists/taglists-questionable.txt
cp dev/taglist-scraper/output_scraped/explicit_sorted.txt   lists/taglists-explicit.txt
```

---

## Notes

- The scraper resumes automatically — existing posts in `output_scraped/*.txt` are loaded as known IDs on startup, so duplicates are skipped.
- `order:random` on Danbooru times out for very large or very small result sets. The fallback to `order:score` handles this automatically.
- Score ceiling: Danbooru posts top out around 2,700 score. Setting `score_max_start` above 3000 wastes a few API calls stepping down but is harmless.
