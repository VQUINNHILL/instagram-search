from flask import Flask, request, jsonify, render_template
from flask_apscheduler import APScheduler
from flask_cors import CORS
import requests
import os
import json
import logging
import base64
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env


# App setup
app = Flask(__name__)
CORS(app)

# Environment configuration
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")  # Store in Railway environment variables
USER_ID = os.getenv("USER_ID")  # Store in Railway environment variables
GITHUB_TOKEN =  os.getenv("GITHUB_TOKEN")  # Secure GitHub token in Railway
GITHUB_REPO = "VQUINNHILL/instagram-search"
GITHUB_BRANCH = "main"
GITHUB_FILE_PATH = "instagram_posts.json"

INSTAGRAM_API_URL = f"https://graph.instagram.com/v21.0/{USER_ID}/media"

# Logging setup
logging.basicConfig(level=logging.DEBUG)

# GitHub Functions
def fetch_github_file_sha():
    """Fetch the SHA of the file in the GitHub repository."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("sha")
    elif response.status_code == 404:
        logging.info("File does not exist in the repository.")
        return None
    else:
        logging.error(f"Failed to fetch file SHA: {response.status_code} - {response.text}")
        raise Exception("Error fetching file SHA")

def save_to_github(data):
    """Save the updated index to GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    file_sha = fetch_github_file_sha()

    payload = {
        "message": "Update Instagram index",
        "content": base64.b64encode(json.dumps(data).encode()).decode(),
        "branch": GITHUB_BRANCH,
    }

    if file_sha:
        payload["sha"] = file_sha  # Required for updates

    response = requests.put(url, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        logging.info("Index successfully updated in GitHub repository.")
    else:
        logging.error(f"Failed to update file in GitHub: {response.status_code} - {response.text}")
        raise Exception("Error saving file to GitHub")

def load_index():
    """Load the index from the GitHub repository."""
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{GITHUB_FILE_PATH}"
    logging.info(f"Fetching index from GitHub: {url}")
    response = requests.get(url)
    logging.info(f"GitHub response: {response.status_code} - {response.text[:200]}")  # Log a preview of the response
    if response.status_code == 200:
        try:
            return response.json()  # Attempt to parse the response
        except Exception as e:
            logging.error(f"Error parsing JSON: {e}")
            raise
    else:
        logging.error(f"Failed to fetch index from GitHub: {response.status_code} - {response.text}")
        raise Exception("Error loading index from GitHub")


# Instagram API Functions
def fetch_all_posts():
    """Fetch all posts from Instagram API."""
    url = INSTAGRAM_API_URL
    posts = []
    page_limit = 5
    page_count = 0

    while url and page_count < page_limit:
        try:
            response = requests.get(
                url,
                params={
                    'fields': 'id,caption,media_url,timestamp,media_type,children{media_type,media_url}',
                    'access_token': ACCESS_TOKEN,
                },
                timeout=10
            )
            response.raise_for_status()

            data = response.json()
            posts.extend(data.get('data', []))
            url = data.get('paging', {}).get('next')
            page_count += 1
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching posts: {e}")
            break

    return posts

def update_instagram_index():
    """Fetch posts from Instagram API and update GitHub index."""
    logging.info("Updating Instagram index...")
    posts = fetch_all_posts()
    if posts:
        save_to_github(posts)
        logging.info("Index successfully updated.")
    else:
        logging.warning("No posts fetched from the API. Index not updated.")

# Post Filtering and Sorting
def filter_and_sort_posts(posts, keywords, sort_by):
    """Filter posts by keywords and sort by the given criteria."""
    keywords = [kw.lower() for kw in keywords]

    filtered_posts = [
        {
            "caption": post.get("caption", ""),
            "media_url": post.get("media_url"),
            "timestamp": post.get("timestamp"),
            "media_type": post.get("media_type"),
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

# Flask Routes
@app.route('/')
def index():
    """Render the homepage."""
    try:
        posts = load_index()[:20]  # Most recent 20 posts
        return render_template('index.html', posts=posts)
    except Exception as e:
        logging.error(f"Failed to load homepage: {e}")
        return jsonify({"error": "Failed to load homepage"}), 500

@app.route('/search', methods=["POST"])
def search():
    """Search posts in the GitHub index."""
    data = request.get_json()
    keywords = data.get("keyword", "").split()
    sort_by = data.get("sort_by", "relevance")

    if not keywords:
        return jsonify([])

    try:
        posts = load_index()
        matching_posts = filter_and_sort_posts(posts, keywords, sort_by)
        return jsonify(matching_posts)
    except Exception as e:
        logging.error(f"Error searching posts: {e}")
        return jsonify({"error": "Search failed"}), 500

@app.route('/update_index', methods=["GET"])
def manual_update():
    """Manually update the Instagram index."""
    try:
        update_instagram_index()
        return jsonify({"status": "Index updated successfully"}), 200
    except Exception as e:
        logging.error(f"Manual update failed: {e}")
        return jsonify({"error": "Manual update failed"}), 500

# Scheduler Setup
class Config:
    SCHEDULER_API_ENABLED = True

app.config.from_object(Config())
scheduler = APScheduler()
scheduler.init_app(app)

@scheduler.task('interval', id='update_instagram_index', hours=24)
def scheduled_update():
    """Scheduled update every 24 hours."""
    update_instagram_index()

scheduler.start()

# Run the Flask App
if __name__ == '__main__':
    try:
        load_index()  # Ensure the index is loaded on startup
    except Exception as e:
        logging.warning(f"Index load failed: {e}")
    app.run(debug=True)
