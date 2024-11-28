from flask import Flask, request, jsonify, render_template
from flask_apscheduler import APScheduler
from flask_cors import CORS
import requests
import os
import json
import logging
import time
import base64

# App setup
app = Flask(__name__)
CORS(app)

# Environment configuration
ACCESS_TOKEN = 'YOUR_INSTAGRAM_ACCESS_TOKEN'
USER_ID = 'YOUR_USER_ID'
INDEX_FILE_PATH = "./instagram_posts.json"
INSTAGRAM_API_URL = f"https://graph.instagram.com/v21.0/{USER_ID}/media"
GITHUB_REPO = "your-username/your-repo"  # Replace with your repo (e.g., "username/project")
GITHUB_BRANCH = "main"  # Replace with your branch (e.g., "main" or "master")
GITHUB_FILE_PATH = "path/to/instagram_posts.json"  # Replace with the file path in your repo
GITHUB_TOKEN = os.getenv("GITHUB_PAT")  # Your PAT stored as an environment variable

# Logging setup
logging.basicConfig(level=logging.DEBUG)


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
        "content": base64.b64encode(json.dumps(data).encode()).decode(),  # Base64 encode the JSON content
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

def update_instagram_index():
    """Fetch posts and save the index to GitHub."""
    posts = fetch_all_posts()
    save_to_github(posts)


# Function to safely read and write the index file
def load_index_from_github():
    """Load the index from the GitHub repository."""
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{GITHUB_FILE_PATH}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        logging.error(f"Failed to fetch index from GitHub: {response.status_code} - {response.text}")
        raise Exception("Error loading index from GitHub")


def save_index(posts):
    """Save the Instagram index to a JSON file."""
    with open(INDEX_FILE_PATH, 'w') as file:
        json.dump(posts, file)

# Function to fetch posts from Instagram API
def fetch_all_posts():
    """Fetch all posts from Instagram API."""
    url = INSTAGRAM_API_URL
    posts = []
    page_limit = 5  # Limit the number of pages fetched
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

# Function to update the index
def update_instagram_index():
    """Fetch posts from Instagram API and update the local index."""
    logging.info("Updating Instagram index...")
    posts = fetch_all_posts()
    if posts:
        save_index(posts)
        logging.info("Index successfully updated.")
    else:
        logging.warning("No posts fetched from the API. Index not updated.")

# Function to filter and sort posts
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

    # Sort posts by relevance or timestamp
    if sort_by == "relevance":
        filtered_posts.sort(key=lambda x: x["relevance"], reverse=True)
    elif sort_by == "timestamp":
        filtered_posts.sort(key=lambda x: x["timestamp"], reverse=True)

    return filtered_posts

# Routes

@app.route('/update_index', methods=["GET"])
def manual_update():
    update_instagram_index()
    return jsonify({"status": "Index updated manually"}), 200


@app.route('/')
def index():
    """Render the homepage with posts."""
    posts = load_index()[:20]  # Limit to the 20 most recent posts
    return render_template('index.html', posts=posts)

@app.route("/search", methods=["POST"])
def search():
    """Search posts from the GitHub index."""
    data = request.get_json()
    keywords = data.get("keyword", "").split()
    sort_by = data.get("sort_by", "relevance")

    if not keywords:
        return jsonify([])

    try:
        # Load index from GitHub
        posts = load_index_from_github()

        # Filter and sort posts
        matching_posts = filter_and_sort_posts(posts, keywords, sort_by)

        logging.debug(f"Matching posts: {matching_posts}")
        return jsonify(matching_posts)
    except Exception as e:
        logging.error(f"Error searching posts: {e}")
        return jsonify({"error": "Failed to search posts"}), 500

# Scheduler configuration
class Config:
    SCHEDULER_API_ENABLED = True

app.config.from_object(Config())
scheduler = APScheduler()
scheduler.init_app(app)

# Schedule the update task
@scheduler.task('interval', id='update_instagram_index', hours=24)
def scheduled_update():
    """Schedule periodic updates to fetch posts and save to GitHub."""
    scheduler.add_job(func=update_instagram_index, trigger="interval", hours=24, id="update_index")
    logging.info("Scheduled job to update Instagram index every 24 hours.")

scheduler.start()

# Error handlers
@app.errorhandler(500)
def handle_500_error(e):
    return jsonify({"error": "Internal server error"}), 500

@app.errorhandler(404)
def handle_404_error(e):
    return jsonify({"error": "Endpoint not found"}), 404

if __name__ == "__main__":
    # Ensure index is populated on startup
    if not os.path.exists(INDEX_FILE_PATH):
        update_instagram_index()
    app.run(debug=True)
