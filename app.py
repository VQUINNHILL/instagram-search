from flask import Flask, request, jsonify, render_template
from flask_apscheduler import APScheduler
from flask_cors import CORS
import requests
import os
import json
import logging
import base64
from dotenv import load_dotenv
from werkzeug.exceptions import BadRequest
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

# Flask app setup
app = Flask(__name__)

from flask import redirect

def _fetch_media_node(media_id: str):
    """Get a fresh media node from Instagram (media_url/thumbnail/children)."""
    params = {
        "fields": "id,media_type,media_url,thumbnail_url,children{media_type,media_url,id}",
        "access_token": ACCESS_TOKEN,
    }
    r = requests.get(f"https://graph.instagram.com/v21.0/{media_id}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()

@app.route("/media_url/<media_id>")
def media_url_resolver(media_id):
    """
    Redirect to a fresh media_url. If ?thumb=1 and the item is VIDEO, prefer thumbnail_url.
    Use <img src="/media_url/<id>?thumb=1"> for thumbnails,
    or <video src="/media_url/<id>"> for playback.
    """
    try:
        node = _fetch_media_node(media_id)
        mt = node.get("media_type")
        url = node.get("media_url")
        if request.args.get("thumb") == "1" and mt == "VIDEO":
            url = node.get("thumbnail_url") or url
        if not url:
            return jsonify({"error": "No media_url available"}), 404
        return redirect(url, code=302)
    except Exception as e:
        logging.error(f"/media_url error for {media_id}: {e}")
        return jsonify({"error": "Failed to resolve media_url"}), 500

@app.route("/media_children/<media_id>")
def media_children(media_id):
    """Return fresh children (for carousels) with non-expired media_url values."""
    try:
        node = _fetch_media_node(media_id)
        children = node.get("children", {}).get("data", [])
        # children already include media_type/media_url/id in the fields we requested
        return jsonify(children)
    except Exception as e:
        logging.error(f"/media_children error for {media_id}: {e}")
        return jsonify({"error": "Failed to resolve children"}), 500


# --- CORS via env var ---
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")  # set to your frontend origin in prod
CORS(app, origins=[ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else "*")

@app.after_request
def after_request(response):
    response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN if ALLOWED_ORIGIN != "*" else "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

# Environment configuration
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
USER_ID = os.getenv("USER_ID")
GITHUB_PAT = os.getenv("GITHUB_PAT")
GITHUB_REPO = "VQUINNHILL/instagram-search"
GITHUB_BRANCH = "main"
GITHUB_FILE_PATH = "instagram_posts.json"
INSTAGRAM_API_URL = f"https://graph.instagram.com/v21.0/{USER_ID}/media"

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Caching setup
CACHE = {
    "instagram_posts": None,
    "last_updated": None
}

# Helper: Validate environment variables
def validate_env_vars():
    if not all([ACCESS_TOKEN, USER_ID, GITHUB_PAT]):
        raise EnvironmentError("Missing critical environment variables (ACCESS_TOKEN, USER_ID, GITHUB_PAT).")
validate_env_vars()

# GitHub Functions
def fetch_github_file_sha():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_PAT}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("sha")
    elif response.status_code == 404:
        logging.info("File does not exist in the repository.")
        return None
    else:
        raise RuntimeError(f"Failed to fetch file SHA: {response.status_code} - {response.text}")

def save_to_github(data):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_PAT}"}
    file_sha = fetch_github_file_sha()
    payload = {
        "message": "Update Instagram index",
        "content": base64.b64encode(json.dumps(data).encode()).decode(),
        "branch": GITHUB_BRANCH,
    }
    logging.info("Saving index to GitHub...")
    if file_sha:
        payload["sha"] = file_sha
    response = requests.put(url, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        logging.info("Index successfully updated in GitHub.")
    else:
        logging.error(f"Failed to save index: {response.status_code} - {response.text}")

def load_index():
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{GITHUB_FILE_PATH}"
    response = requests.get(url)
    if response.status_code == 200:
        try:
            index = response.json()
            if not isinstance(index, list):
                raise ValueError("Invalid index format: Expected a list")
            return index
        except json.JSONDecodeError as e:
            raise ValueError("Error decoding JSON") from e
    elif response.status_code == 404:
        return []
    else:
        raise RuntimeError(f"Failed to fetch index from GitHub: {response.status_code} - {response.text}")

def filter_and_sort_posts(posts, keywords, sort_by):
    """
    Filter posts by keywords and sort them by the specified criteria.
    """
    keywords = [kw.lower() for kw in keywords]

    filtered_posts = [
        {
            "id": post.get("id"),
            "shortcode": post.get("shortcode"),
            "caption": post.get("caption", ""),
            "media_url": post.get("media_url"),
            "timestamp": post.get("timestamp"),
            "media_type": post.get("media_type"),
            "children": post.get("children", {}).get("data", []),
            "relevance": sum(1 for kw in keywords if kw in post.get("caption", "").lower()),
        }
        for post in posts
        if post.get("caption") and any(kw in post.get("caption", "").lower() for kw in keywords)
    ]
    logging.debug(f"Filtered posts before sorting: {filtered_posts}")

    if sort_by == "relevance":
        filtered_posts.sort(key=lambda x: x["relevance"], reverse=True)
    elif sort_by == "timestamp":
        filtered_posts.sort(key=lambda x: x["timestamp"], reverse=True)

    logging.debug(f"Filtered and sorted posts: {filtered_posts}")
    return filtered_posts

# Instagram API Functions
from datetime import datetime  # (kept as in your original file)

def fetch_posts_by_date_range(since_date, until_date=None):
    """Fetch posts from Instagram API within a date range."""
    since_timestamp = int(datetime.strptime(since_date, "%Y-%m-%d").timestamp())
    until_timestamp = None
    if until_date:
        until_timestamp = int(datetime.strptime(until_date, "%Y-%m-%d").timestamp())

    url = INSTAGRAM_API_URL
    posts = []
    page_limit = 100
    page_count = 0

    while url and page_count < page_limit:
        try:
            params = {
                'fields': 'id,shortcode,caption,media_url,timestamp,media_type,children{media_type,media_url}',
                'access_token': ACCESS_TOKEN,
                'since': since_timestamp,
            }
            if until_timestamp:
                params['until'] = until_timestamp

            logging.info(f"Fetching posts from {since_date} to {until_date or 'now'}...")
            response = requests.get(url, params=params, timeout=10)
            logging.info(f"Instagram API response status: {response.status_code}")
            response.raise_for_status()

            data = response.json()
            logging.debug(f"Fetched data: {json.dumps(data, indent=2)}")

            posts.extend(data.get("data", []))
            url = data.get("paging", {}).get("next")
            page_count += 1

        except requests.exceptions.Timeout:
            logging.error("Instagram API request timed out.")
            break
        except requests.exceptions.RequestException as e:
            logging.error(f"Error during Instagram API request: {e}")
            break

    logging.info(f"Fetched {len(posts)} posts from {since_date} to {until_date or 'now'}.")
    return posts

def fetch_historical_posts():
    """Fetch and index historical posts year-by-year since January 1, 2020."""
    start_date = datetime(2020, 1, 1)
    end_date = datetime.now()
    interval = timedelta(days=365)

    current_date = start_date
    while current_date < end_date:
        since_date = current_date.strftime("%Y-%m-%d")
        until_date = (current_date + interval).strftime("%Y-%m-%d")
        logging.info(f"Fetching posts from {since_date} to {until_date}...")

        try:
            update_instagram_index_for_range(since_date, until_date)
            logging.info(f"Successfully indexed posts from {since_date} to {until_date}.")
        except Exception as e:
            logging.error(f"Failed to index posts from {since_date} to {until_date}: {e}")
        
        current_date += interval

# --- wrapper used by scheduler & manual routes ---
def update_instagram_index_for_range(since_date, until_date=None):
    """Fetch and merge posts with the existing index."""
    try:
        older_posts = fetch_posts_by_date_range(since_date, until_date)
        if not older_posts:
            logging.info("No older posts fetched.")
            return

        current_index = load_index() or []
        logging.info(f"Current index contains {len(current_index)} posts.")

        post_ids = {post["id"] for post in current_index}
        new_posts = [post for post in older_posts if post["id"] not in post_ids]
        updated_index = current_index + new_posts

        save_to_github(updated_index)
        logging.info(f"Index successfully updated with {len(new_posts)} new posts.")
    except Exception as e:
        logging.error(f"Error updating Instagram index: {e}")

# Flask Routes
@app.route('/')
def index():
    """Serve the frontend homepage."""
    return render_template('index.html')

@app.route('/search', methods=["POST"])
def search():
    try:
        posts = load_index()
        keywords = request.json.get("keyword", "").split()
        sort_by = request.json.get("sort_by", "relevance")
        matching_posts = filter_and_sort_posts(posts, keywords, sort_by)

        # Pagination
        limit = int(request.args.get("limit", 20))
        offset = int(request.args.get("offset", 0))
        paginated_posts = matching_posts[offset:offset + limit]

        return jsonify(paginated_posts)
    except Exception as e:
        logging.error(f"Error processing search request: {e}")
        return jsonify({"error": "Search failed"}), 500

@app.route('/update_index', methods=["GET"])
def manual_update():
    since_date = request.args.get('since', '2020-01-01')
    until_date = request.args.get('until')
    logging.info(f"Manual update triggered for posts since {since_date} to {until_date or 'now'}.")

    try:
        update_instagram_index_for_range(since_date, until_date)
        return jsonify({"status": "Index updated successfully"}), 200
    except Exception as e:
        logging.error(f"Manual update failed: {e}")
        return jsonify({"error": "Manual update failed"}), 500

@app.route('/fetch_historical_posts', methods=["GET"])
def fetch_historical_posts_route():
    """Trigger historical post fetching."""
    logging.info("Historical post fetch triggered.")
    try:
        fetch_historical_posts()
        return jsonify({"status": "Historical posts indexed successfully."}), 200
    except Exception as e:
        logging.error(f"Failed to fetch historical posts: {e}")
        return jsonify({"error": "Failed to fetch historical posts."}), 500

current_index = load_index() or []
logging.info(f"Current index contains {len(current_index)} posts.")

# Scheduler
class Config:
    SCHEDULER_API_ENABLED = True

app.config.from_object(Config())
scheduler = APScheduler()
scheduler.init_app(app)

@scheduler.task('interval', id='update_instagram_index', hours=24)
def scheduled_update():
    # Example: refresh the last 30 days every 24 hours
    since = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    update_instagram_index_for_range(since)

scheduler.start()

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
