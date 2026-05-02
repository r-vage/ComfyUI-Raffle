import json
import time
import configparser
import subprocess
import urllib.parse
from datetime import datetime
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "config.ini")
CONFIG_EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "config.ini.example")

def load_config():
    """
    Load settings from config.ini next to this script.
    If config.ini doesn't exist, it is created from config.ini.example automatically.
    """
    import shutil
    if not os.path.exists(CONFIG_FILE):
        if os.path.exists(CONFIG_EXAMPLE):
            shutil.copy(CONFIG_EXAMPLE, CONFIG_FILE)
            print(f"Created config.ini from config.ini.example — please fill in your username and api_key in:\n  {CONFIG_FILE}")
        else:
            raise FileNotFoundError(
                f"Neither config.ini nor config.ini.example found in:\n  {os.path.dirname(CONFIG_FILE)}"
            )
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    username = config.get("danbooru", "username", fallback="").strip()
    api_key = config.get("danbooru", "api_key", fallback="").strip()
    if not username or not api_key:
        raise ValueError(
            f"username and api_key must both be set in:\n  {CONFIG_FILE}"
        )
    score_min        = config.getint(  "scraper", "score_min",        fallback=100)
    score_max_start  = config.getint(  "scraper", "score_max_start",   fallback=2048)
    max_runs         = config.getint(  "scraper", "max_runs",          fallback=0)
    tags_per_request = config.getint(  "scraper", "tags_per_request",  fallback=200)
    pause_interval   = config.getfloat("scraper", "pause_interval",    fallback=1.0)
    return username, api_key, score_min, score_max_start, max_runs, tags_per_request, pause_interval

# Add this rating map before the functions
rating_map = {
    'g': 'general',
    's': 'sensitive',
    'q': 'questionable',
    'e': 'explicit'
}

def danbooru_get(username, api_key, endpoint, params):
    """
    Make a GET request to Danbooru via curl to avoid Cloudflare TLS-fingerprint blocks.
    """
    params['login'] = username
    params['api_key'] = api_key
    url = f"https://danbooru.donmai.us{endpoint}?{urllib.parse.urlencode(params)}"
    result = subprocess.run(
        ['curl', '-s', '--max-time', '30', url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout)


def get_filtered_posts(username, api_key, rating, score_range, limit=200):
    """
    Fetch posts from Danbooru with specific filters using random ordering
    """
    min_score, max_score = score_range
    params = {
        'tags': f'score:>={min_score} score:<={max_score} rating:{rating} order:random -animated',
        'limit': limit
    }

    print(f"\nRequesting {limit} random posts from {rating_map[rating]}")
    print(f"Using score range: {min_score} to {max_score}")
    try:
        posts = danbooru_get(username, api_key, '/posts.json', params)
        if not isinstance(posts, list):
            print(f"Unexpected API response (not a list): {str(posts)[:200]}")
            return []
        # order:random fails on narrow/high-score bands — retry with order:score descending
        if len(posts) == 0:
            print(f"order:random returned 0 — retrying with order:score")
            params['tags'] = f'score:>={min_score} score:<={max_score} rating:{rating} order:score -animated'
            posts = danbooru_get(username, api_key, '/posts.json', params)
            if not isinstance(posts, list):
                print(f"Unexpected API response (not a list): {str(posts)[:200]}")
                return []
        print(f"API returned {len(posts)} posts")
        return posts
    except (RuntimeError, json.JSONDecodeError) as e:
        print(f"Error fetching filtered posts: {e}")
        return []

def get_existing_post_ids(rating):
    """
    Get set of existing post IDs for a rating
    """
    output_dir = "output_scraped"
    filename = os.path.join(output_dir, f"{rating_map[rating]}.txt")
    existing_ids = set()
    
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                post_id = line.split(',')[0].strip()
                existing_ids.add(post_id)
    
    return existing_ids

def save_new_posts(new_posts, rating):
    """
    Save batch of new posts to file
    """
    output_dir = "output_scraped"
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{rating_map[rating]}.txt")
    
    with open(filename, 'a', encoding='utf-8') as f:
        for post in new_posts:
            post_id = post['id']
            score = post['score']
            tags = sorted(post['tag_string'].split())
            new_line = f"{post_id}, {score}, {', '.join(tags)}\n"
            f.write(new_line)
    
    print(f"Successfully added {len(new_posts)} new posts to {rating_map[rating]}.txt")

def get_line_counts():
    """
    Get the current number of lines in each rating file
    """
    output_dir = "output_scraped"
    counts = {}
    for rating in ['g', 's', 'q', 'e']:
        filename = os.path.join(output_dir, f"{rating_map[rating]}.txt")
        try:
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    counts[rating] = sum(1 for _ in f)
            else:
                counts[rating] = 0
        except IOError:
            counts[rating] = 0
    return counts

def main():
    USERNAME, API_KEY, SCORE_MIN, SCORE_MAX_START, MAX_RUNS, TAGS_PER_REQUEST, PAUSE_INTERVAL = load_config()

    ratings = ['g', 's', 'q', 'e']
    # Start the lower bound at half of score_max_start so we begin with the highest
    # quality band (e.g. 5000-10000), then halve down through lower bands automatically.
    # Always floor at 100 to avoid full-table random queries that time out.
    SCORE_START_MIN = max(100, SCORE_MAX_START // 2)
    score_ranges = {rating: (SCORE_START_MIN, SCORE_MAX_START) for rating in ratings}

    start_time = datetime.now()
    run_count = 0
    stop_reason = "Ctrl+C"

    print("Starting to scrape images...")
    print(f"Score range: {SCORE_MIN} – {SCORE_MAX_START} | Tags/request: {TAGS_PER_REQUEST} | Max runs: {'unlimited' if MAX_RUNS == 0 else MAX_RUNS} | Pause: {PAUSE_INTERVAL}s")
    print("Press Ctrl+C to stop...")

    try:
        while True:
            if MAX_RUNS > 0 and run_count >= MAX_RUNS:
                stop_reason = f"reached max_runs ({MAX_RUNS})"
                break

            counts = get_line_counts()
            current_rating = min(counts.items(), key=lambda x: x[1])[0]
            print(f"\n[Run {run_count + 1}{f'/{MAX_RUNS}' if MAX_RUNS else ''}] Processing {rating_map[current_rating]} - currently has {counts[current_rating]} entries (lowest)")

            min_score, max_score = score_ranges[current_rating]

            # Stop if this rating has exhausted the allowed score floor
            if max_score <= SCORE_MIN:
                print(f"Score range for {rating_map[current_rating]} is at floor ({SCORE_MIN}), skipping.")
                run_count += 1
                time.sleep(PAUSE_INTERVAL)
                continue

            existing_ids = get_existing_post_ids(current_rating)

            # Fetch batch of random posts
            posts = get_filtered_posts(USERNAME, API_KEY, current_rating, score_ranges[current_rating], TAGS_PER_REQUEST)
            run_count += 1

            if posts:
                print("Checking for duplicates...")
                new_posts = [post for post in posts if str(post['id']) not in existing_ids]
                print(f"Found {len(new_posts)} new unique posts out of {len(posts)} total posts")

                if new_posts:
                    save_new_posts(new_posts, current_rating)
                    counts = get_line_counts()
                    print("\nUpdated file counts:")
                    for r in ratings:
                        print(f"{rating_map[r]}: {counts[r]} posts (score range: {score_ranges[r][0]} to {score_ranges[r][1]})")
                else:
                    # No new posts — lower the score range, but not below score_min
                    new_max = min_score
                    new_min = max(SCORE_MIN, new_max // 2)
                    score_ranges[current_rating] = (new_min, new_max)
                    print(f"All posts were duplicates. Lowering score range to {new_min} – {new_max}")
            else:
                # No posts returned at all — lower the score range
                new_max = min_score
                new_min = max(SCORE_MIN, new_max // 2)
                score_ranges[current_rating] = (new_min, new_max)
                print(f"No posts found in current range. Lowering score range to {new_min} – {new_max}")

            time.sleep(PAUSE_INTERVAL)
    except KeyboardInterrupt:
        stop_reason = "Ctrl+C"
        print("\n\nScraping stopped by user!")

    elapsed_time = datetime.now() - start_time
    print(f"\nStopped: {stop_reason}")
    print(f"Total runs: {run_count} | Time elapsed: {elapsed_time}")
    print("\nFinal counts:")
    counts = get_line_counts()
    for rating in ratings:
        print(f"{rating_map[rating]}: {counts[rating]}")

if __name__ == "__main__":
    main()
