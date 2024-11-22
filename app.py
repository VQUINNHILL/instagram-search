from flask import Flask, request, jsonify, render_template
import requests

app = Flask(__name__)

ACCESS_TOKEN = 'your-instagram-access-token'
USER_ID = 'your-instagram-user-id'
INSTAGRAM_API_URL = f'https://graph.instagram.com/{USER_ID}/media'


def fetch_all_posts():
    """Fetch all posts from the Instagram API with pagination."""
    url = INSTAGRAM_API_URL
    posts = []

    while url:
        response = requests.get(
            url,
            params={
                'fields': 'id,caption,media_url,timestamp',
                'access_token': ACCESS_TOKEN,
            } if 'access_token' not in url else {}
        )
        if response.status_code != 200:
            break

        data = response.json()
        posts.extend(data.get('data', []))
        url = data.get('paging', {}).get('next')  # Next page URL

    return posts


def filter_and_sort_posts(posts, keywords, sort_by):
    """Filter posts by keywords and sort by the given criteria."""
    keywords = [kw.lower() for kw in keywords]

    # Filter posts by matching keywords in captions
    filtered_posts = [
        {
            'caption': post.get('caption', ''),
            'media_url': post.get('media_url'),
            'timestamp': post.get('timestamp'),
            'relevance': sum(1 for kw in keywords if kw in post.get('caption', '').lower())
        }
        for post in posts
        if post.get('caption') and any(kw in post.get('caption', '').lower() for kw in keywords)
    ]

    # Sort posts by relevance or timestamp
    if sort_by == 'relevance':
        filtered_posts.sort(key=lambda x: x['relevance'], reverse=True)
    elif sort_by == 'timestamp':
        filtered_posts.sort(key=lambda x: x['timestamp'], reverse=True)

    return filtered_posts


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/search', methods=['POST'])
def search():
    data = request.get_json()
    keywords = data.get('keyword', '').split()
    sort_by = data.get('sort_by', 'relevance')  # Default sorting by relevance

    if not keywords:
        return jsonify([])

    # Fetch all Instagram posts
    posts = fetch_all_posts()

    # Filter and sort posts
    matching_posts = filter_and_sort_posts(posts, keywords, sort_by)

    return jsonify(matching_posts)


if __name__ == '__main__':
    app.run(debug=True)
