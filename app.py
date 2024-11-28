from flask import Flask, request, jsonify, render_template
from flask_apscheduler import APScheduler
from flask_cors import CORS
import requests
import os
import json
import logging
import time

# App setup
app = Flask(__name__)
CORS(app)

# Environment configuration
ACCESS_TOKEN = 'YOUR_INSTAGRAM_ACCESS_TOKEN'
USER_ID = 'YOUR_USER_ID'
INDEX_FILE_PATH = "./instagram_posts.json"
INSTAGRAM_API_URL = f"https://graph.instagram.com/v21.0/{USER_ID}/media"

# Logging setup
logging.basicConfig(level=logging.DEBUG)

# Function to safely read and write the index file
def load_index():
    """Load the Instagram index from a JSON file."""
    if not os.path.exists(INDEX_FILE_PATH):
        logging.info("Index file not found, creating an empty one.")
        with open(INDEX_FILE_PATH, 'w') as file:
            json.dump([], file)
    with open(INDEX_FILE_PATH, 'r') as file:
        return json.load(file)

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
@app.route('/')
def index():
    """Render the homepage with posts."""
    posts = load_index()[:20]  # Limit to the 20 most recent posts
    return render_template('index.html', posts=posts)

@app.route("/search", methods=["POST"])
def search():
    """Search for posts by keyword."""
    data = request.get_json()
    keywords = data.get("keyword", "").split()
    sort_by = data.get("sort_by", "relevance")

    if not keywords:
        return jsonify([])

    posts = load_index()
    matching_posts = filter_and_sort_posts(posts, keywords, sort_by)
    return jsonify(matching_posts)

# Scheduler configuration
class Config:
    SCHEDULER_API_ENABLED = True

app.config.from_object(Config())
scheduler = APScheduler()
scheduler.init_app(app)

# Schedule the update task
@scheduler.task('interval', id='update_instagram_index', hours=24)
def scheduled_update():
    """Scheduled task to update the index every 24 hours."""
    update_instagram_index()

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
