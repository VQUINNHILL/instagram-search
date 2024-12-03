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

# Load environment variables
load_dotenv()

# Flask app setup
app = Flask(__name__)
CORS(app, origins=["https://supreme-meme-7qp4794rq59f6x-5000.app.github.dev"])

@app.after_request
def after_request(response):
    response.headers["Access-Control-Allow-Origin"] = "https://supreme-meme-7qp4794rq59f6x-5000.app.github.dev"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

# Environment configuration
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
USER_ID = os.getenv("USER_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
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
    if not all([ACCESS_TOKEN, USER_ID, GITHUB_TOKEN]):
        raise EnvironmentError("Missing critical environment variables (ACCESS_TOKEN, USER_ID, GITHUB_TOKEN).")
validate_env_vars()

# GitHub Functions
def fetch_github_file_sha():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
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
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    file_sha = fetch_github_file_sha()
    payload = {
        "message": "Update Instagram index",
        "content": base64.b64encode(json.dumps(data).encode()).decode(),
        "branch": GITHUB_BRANCH,
    }
    if file_sha:
        payload["sha"] = file_sha
    response = requests.put(url, headers=headers, json=payload)
    if response.status_code not in [200, 201]:
        raise RuntimeError(f"Failed to update file in GitHub: {response.status_code} - {response.text}")

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

    Args:
        posts (list): List of posts from the index.
        keywords (list): List of keywords to filter posts.
        sort_by (str): Sorting criteria ('relevance' or 'timestamp').

    Returns:
        list: Filtered and sorted list of posts.
    """
    keywords = [kw.lower() for kw in keywords]  # Normalize keywords to lowercase

    # Filter posts containing any keyword
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

    # Sort posts
    if sort_by == "relevance":
        filtered_posts.sort(key=lambda x: x["relevance"], reverse=True)
    elif sort_by == "timestamp":
        filtered_posts.sort(key=lambda x: x["timestamp"], reverse=True)

    return filtered_posts

# Instagram API Functions
def fetch_all_posts():
    if CACHE["instagram_posts"]:
        return CACHE["instagram_posts"]  # Return cached posts

    url = INSTAGRAM_API_URL
    posts = []
    while url:
        response = requests.get(
            url,
            params={
                'fields': 'id,shortcode,caption,media_url,timestamp,media_type,children{media_type,media_url}',
                'access_token': ACCESS_TOKEN,
            },
            timeout=10
        )
        if response.status_code != 200:
            raise RuntimeError(f"Error fetching posts: {response.status_code} - {response.text}")

        data = response.json()
        logging.debug(f"Fetched data: {json.dumps(data, indent=2)}")  # Log full response

        posts.extend([
            {
                "id": post.get("id"),
                "caption": post.get("caption"),
                "media_url": post.get("media_url"),
                "timestamp": post.get("timestamp"),
                "media_type": post.get("media_type"),
                "children": post.get("children", {}).get("data", [])
            }
            for post in data.get("data", [])
        ])
        url = data.get("paging", {}).get("next")

    CACHE["instagram_posts"] = posts  # Cache the result
    return posts

def update_instagram_index():
    posts = fetch_all_posts()
    if posts:
        save_to_github(posts)
    else:
        logging.warning("No posts fetched from Instagram API.")

# Flask Routes
@app.route('/')
def index():
    """Serve the frontend homepage."""
    return render_template('index.html')

@app.route('/search', methods=["POST"])
def search():
    try:
        data = request.get_json()
        keywords = data.get("keyword", "").split()
        sort_by = data.get("sort_by", "relevance")
        if not keywords:
            raise BadRequest("No keywords provided.")

        posts = load_index()
        matching_posts = filter_and_sort_posts(posts, keywords, sort_by)
        return jsonify(matching_posts)
    except BadRequest as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logging.exception("Error processing search request.")
        return jsonify({"error": "Search failed"}), 500

@app.route('/update_index', methods=["GET"])
def manual_update():
    try:
        update_instagram_index()
        return jsonify({"status": "Index updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Scheduler
class Config:
    SCHEDULER_API_ENABLED = True

app.config.from_object(Config())
scheduler = APScheduler()
scheduler.init_app(app)

@scheduler.task('interval', id='update_instagram_index', hours=24)
def scheduled_update():
    update_instagram_index()

scheduler.start()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)