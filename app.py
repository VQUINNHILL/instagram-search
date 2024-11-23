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
ACCESS_TOKEN = 'IGQWRPQ0VfaVFwYjNrbW9xUGhmb0hnbE4ySGU0X2JXdGtCTk1RaUdLc0xjNXpqb3UtTGNqSWZApU2NCQnVXLUFHNTItZADY0RTgtcHBuUjNYbElMaHp2eGdCM3ZAfQ0c4OExfTzdxVjFoOEUtWFA0VXBvejRBOGVzaTAZD'
USER_ID = '17841400682839492'
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
    """Fetch the first 5 pages of posts from the Instagram API with timeouts."""
    url = f"https://graph.instagram.com/v21.0/{USER_ID}/media"
    posts = []
    page_limit = 5  # Limit to the first 5 pages
    page_count = 0  # Counter for the number of pages fetched

    while url and page_count < page_limit:
        try:
            response = requests.get(
                url,
                params={
                    'fields': 'id,caption,media_url,timestamp,media_type,children{media_type,media_url}',
                    'access_token': ACCESS_TOKEN,
                },
                timeout=10  # Set timeout to 10 seconds
            )
            logging.debug(f"API Response: {response.json()}")  # Log the full response

            if response.status_code != 200:
                logging.error(f"Error fetching posts: {response.status_code} {response.text}")
                break

            data = response.json()
            posts.extend(data.get('data', []))
            url = data.get('paging', {}).get('next')  # Get the next page URL
            page_count += 1  # Increment page counter

        except requests.exceptions.Timeout:
            logging.error("Request timed out while fetching posts")
            break
        except requests.exceptions.RequestException as e:
            logging.error(f"An error occurred: {e}")
            break

    logging.debug(f"Fetched posts: {posts}")  # Log the complete post list
    return posts





def filter_and_sort_posts(posts, keywords, sort_by):
    logging.debug(f"Posts before filtering: {posts}")
    """Filter posts by keywords and sort by the given criteria."""
    keywords = [kw.lower() for kw in keywords]

    # Filter posts by matching keywords in captions
    filtered_posts = [
        {
            "caption": post.get("caption", ""),
            "media_url": post.get("media_url", ""),
            "timestamp": post.get("timestamp", ""),
            "media_type": post.get("media_type", ""),  # Default to "UNKNOWN"
            "children": post.get("children", {}),
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
    logging.debug(f"Filtered posts: {filtered_posts}")

    return filtered_posts




@app.route('/')
def index():
    # Fetch posts to display in the grid
    posts = fetch_all_posts()
    # Limit to the most recent 20 posts for performance
    posts = posts[:20]
    return render_template('index.html', posts=posts)



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

    logging.debug(f"Final matching posts sent to frontend: {matching_posts}")
    return jsonify(matching_posts)


@app.errorhandler(500)
def handle_500_error(e):
    return jsonify({"error": "Internal server error"}), 500


@app.errorhandler(404)
def handle_404_error(e):
    return jsonify({"error": "Endpoint not found"}), 404


if __name__ == "__main__":
    app.run(debug=True)
