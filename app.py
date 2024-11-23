from flask import Flask, request, jsonify, render_template
import requests
import os
import logging
import time
from flask_cors import CORS

# App setup
app = Flask(__name__)
CORS(app, origins=["https://supreme-meme-7qp4794rq59f6x-5000.app.github.dev"])

# Environment configuration
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "YOUR_DEFAULT_ACCESS_TOKEN")
USER_ID = os.getenv("USER_ID", "YOUR_USER_ID")
INSTAGRAM_API_URL = f"https://graph.instagram.com/v21.0/{USER_ID}/media"

# Logging setup
logging.basicConfig(level=logging.DEBUG)


def fetch_with_retries(url, params, retries=3):
    """Fetch data from the Instagram API with retry logic."""
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logging.error("All retry attempts failed.")
                raise


def fetch_all_posts():
    """Fetch all posts from the Instagram API with pagination."""
    params = {
        "fields": "id,caption,media_url,timestamp",
        "access_token": ACCESS_TOKEN,
        "limit": 25,
    }
    url = INSTAGRAM_API_URL
    posts = []

    while url:
        try:
            data = fetch_with_retries(url, params)
            posts.extend(data.get("data", []))
            url = data.get("paging", {}).get("next")
        except Exception as e:
            logging.error(f"Error fetching posts: {e}")
            break

    return posts


def filter_and_sort_posts(posts, keywords, sort_by):
    """Filter posts by keywords and sort by the given criteria."""
    keywords = [kw.lower() for kw in keywords]

    # Filter posts by matching keywords in captions
    filtered_posts = [
        {
            "caption": post.get("caption", ""),
            "media_url": post.get("media_url"),
            "timestamp": post.get("timestamp"),
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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search", methods=["POST"])
def search():
    data = request.get_json()
    keywords = data.get("keyword", "").split()
    sort_by = data.get("sort_by", "relevance")  # Default sorting by relevance

    if not keywords:
        return jsonify([])

    # Fetch all Instagram posts
    posts = fetch_all_posts()

    # Filter and sort posts
    matching_posts = filter_and_sort_posts(posts, keywords, sort_by)

    logging.debug(f"Matching posts: {matching_posts}")
    return jsonify(matching_posts)


@app.errorhandler(500)
def handle_500_error(e):
    return jsonify({"error": "Internal server error"}), 500


@app.errorhandler(404)
def handle_404_error(e):
    return jsonify({"error": "Endpoint not found"}), 404


if __name__ == "__main__":
    app.run(debug=True)
