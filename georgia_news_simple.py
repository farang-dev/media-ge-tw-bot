import os
import requests
import json
import time
import random
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from requests_oauthlib import OAuth1

# Load environment variables
load_dotenv()

# Configuration
GEORGIA_NEWS_URL = "https://www.georgia-news-japan.online/"
TWITTER_API_URL = "https://api.twitter.com/2/tweets"
MAX_TWEET_LENGTH = 280
POSTED_ARTICLES_FILE = "posted_articles_simple.json"
MAX_RETRIES = 3
HOURS_BETWEEN_POSTS = 1  # Post every hour

# Debug print function
def debug_print(message):
    """Print debug messages"""
    print(f"[DEBUG] {message}")

def load_posted_articles():
    """Load the list of previously posted articles"""
    try:
        if os.path.exists(POSTED_ARTICLES_FILE):
            with open(POSTED_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                debug_print(f"Loaded {len(data['posted_urls'])} posted articles")
                return data

        # If file doesn't exist, create a new one
        debug_print("No posted articles file found, creating new record")
        new_data = {
            "posted_urls": [],
            "posted_titles": [],
            "last_post_time": 0
        }

        with open(POSTED_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)

        return new_data
    except Exception as e:
        debug_print(f"Error loading posted articles: {str(e)}")
        return {
            "posted_urls": [],
            "posted_titles": [],
            "last_post_time": 0
        }

def save_posted_articles(posted_data):
    """Save the list of posted articles"""
    try:
        with open(POSTED_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(posted_data, f, ensure_ascii=False, indent=2)
        debug_print(f"Saved {len(posted_data['posted_urls'])} posted articles")
    except Exception as e:
        debug_print(f"Error saving posted articles: {str(e)}")

def get_articles():
    """Scrape articles from Georgia News Japan with retry logic"""
    for attempt in range(MAX_RETRIES):
        try:
            debug_print(f"Fetching articles (attempt {attempt+1}/{MAX_RETRIES})...")
            response = requests.get(GEORGIA_NEWS_URL, timeout=15)

            if response.status_code != 200:
                debug_print(f"Failed to fetch articles, status code: {response.status_code}")
                time.sleep(2)
                continue

            soup = BeautifulSoup(response.text, 'html.parser')

            articles = []
            links = soup.find_all('a', href=True)
            debug_print(f"Found {len(links)} links on the page")

            for link in links:
                url = link['href']
                title = link.get_text(strip=True)

                if not title or len(title) < 10:
                    continue

                if not url.startswith('http'):
                    url = f"{GEORGIA_NEWS_URL.rstrip('/')}{url}"

                if '/post/' in url:
                    articles.append({'title': title, 'url': url})

            debug_print(f"Found {len(articles)} potential articles")
            return articles

        except Exception as e:
            debug_print(f"Error fetching articles (attempt {attempt+1}): {str(e)}")
            time.sleep(2)

    debug_print("All attempts to fetch articles failed")
    return []

def get_article_content(url):
    """Scrape the content of an article with retry logic"""
    for attempt in range(MAX_RETRIES):
        try:
            debug_print(f"Fetching article content (attempt {attempt+1}/{MAX_RETRIES}): {url}")
            response = requests.get(url, timeout=15)

            if response.status_code != 200:
                debug_print(f"Failed to fetch article, status code: {response.status_code}")
                time.sleep(2)
                continue

            soup = BeautifulSoup(response.text, 'html.parser')

            # Try to find paragraphs
            paragraphs = soup.find_all('p')
            if paragraphs:
                valid_paragraphs = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
                if valid_paragraphs:
                    content = ' '.join(valid_paragraphs)
                    debug_print(f"Found content: {len(content)} chars")
                    return content

            # If no paragraphs found, try to find any div with substantial text
            divs = soup.find_all('div')
            div_texts = []
            for div in divs:
                text = div.get_text(strip=True)
                if len(text) > 100:
                    div_texts.append(text)
            if div_texts:
                content = max(div_texts, key=len)
                debug_print(f"Found content using divs: {len(content)} chars")
                return content

            debug_print("Could not extract article content")
            time.sleep(2)

        except Exception as e:
            debug_print(f"Error fetching article content (attempt {attempt+1}): {str(e)}")
            time.sleep(2)

    debug_print("All attempts to fetch article content failed")
    return None

def create_engaging_summary(title, content=None, max_length=200):
    """Create an engaging summary from the article content"""
    # If no content, just use the title
    if not content or len(content) < 50:
        # Make sure the title ends with a proper sentence ending
        if not (title.endswith('。') or title.endswith('.') or
                title.endswith('!') or title.endswith('?') or
                title.endswith('！') or title.endswith('？')):
            return title + '。'
        return title

    # Extract key sentences from content
    sentences = []
    current_sentence = ""

    # Split content into sentences
    for char in content:
        current_sentence += char
        if char in ['。', '.', '？', '！', '?', '!']:
            if len(current_sentence.strip()) > 10:  # Only consider substantial sentences
                sentences.append(current_sentence.strip())
            current_sentence = ""

    # If we couldn't extract sentences, use the title
    if not sentences:
        if not (title.endswith('。') or title.endswith('.') or
                title.endswith('!') or title.endswith('?') or
                title.endswith('！') or title.endswith('？')):
            return title + '。'
        return title

    # Create an engaging summary
    # Start with the title
    if not (title.endswith('。') or title.endswith('.') or
            title.endswith('!') or title.endswith('?') or
            title.endswith('！') or title.endswith('？')):
        summary = title + '。 '
    else:
        summary = title + ' '

    # Add a hook from the content
    # Find the most interesting sentence from the first few sentences
    interesting_sentences = []
    for sentence in sentences[:3]:
        # Look for sentences with interesting keywords
        keywords = ['重要', '注目', '懸念', '問題', '批判', '発表', '決定', '合意', '反対', '支持',
                   '要求', '主張', '警告', '非難', '提案', '協力', '対立', '交渉', '会談', '声明']

        for keyword in keywords:
            if keyword in sentence:
                interesting_sentences.append(sentence)
                break

    # If we found interesting sentences, use the first one
    if interesting_sentences:
        if len(summary) + len(interesting_sentences[0]) <= max_length:
            summary += interesting_sentences[0] + ' '
    # Otherwise use the first sentence from content
    elif sentences and len(summary) + len(sentences[0]) <= max_length:
        summary += sentences[0] + ' '

    # Add a call to action or engaging question
    engaging_endings = [
        "詳細はリンクから。",
        "詳しくはこちら。",
        "続きを読む。",
        "全文はリンクから。"
    ]

    # Choose a random ending
    ending = random.choice(engaging_endings)

    # Add the ending if there's room
    if len(summary) + len(ending) <= max_length:
        summary += ending

    # Ensure the summary ends with a proper sentence ending
    summary = summary.strip()
    if not (summary.endswith('。') or summary.endswith('.') or
            summary.endswith('!') or summary.endswith('?') or
            summary.endswith('！') or summary.endswith('？')):
        summary += '。'

    return summary

def create_tweet(title, content, url):
    """Create a tweet with an engaging summary and URL"""
    # Calculate maximum summary length (leave room for URL and newlines)
    max_summary_length = MAX_TWEET_LENGTH - len(url) - 5

    # Create an engaging summary
    summary = create_engaging_summary(title, content, max_summary_length)
    debug_print(f"Generated summary: {summary}")

    # If the summary is just the title, try to make it more engaging
    if summary == title or summary == title + '。':
        # Try to extract a sentence from content
        if content and len(content) > 50:
            # Find the first sentence ending
            first_jp_period = content.find('。')
            first_en_period = content.find('.')
            first_question = content.find('？')
            first_exclamation = content.find('！')
            first_q_mark = content.find('?')
            first_excl_mark = content.find('!')

            end_positions = [pos for pos in [first_jp_period, first_en_period, first_question,
                                            first_exclamation, first_q_mark, first_excl_mark] if pos > 0]

            if end_positions:
                # Use the first sentence ending
                first_end = min(end_positions)
                first_sentence = content[:first_end + 1]

                # If the first sentence is not too long, add it to the summary
                if len(title) + len(first_sentence) + 5 <= max_summary_length:
                    if not title.endswith('。') and not title.endswith('.'):
                        summary = title + '。 ' + first_sentence
                    else:
                        summary = title + ' ' + first_sentence

                    # Add a call to action
                    engaging_endings = [
                        "詳細はリンクから。",
                        "詳しくはこちら。",
                        "続きを読む。",
                        "全文はリンクから。"
                    ]
                    ending = random.choice(engaging_endings)

                    if len(summary) + len(ending) + 1 <= max_summary_length:
                        summary = summary.strip() + ' ' + ending

    # Ensure the summary is not too long
    if len(summary) > max_summary_length:
        # Find the last sentence ending within the limit
        truncated = summary[:max_summary_length]

        # Look for sentence endings
        last_jp_period = truncated.rfind('。')
        last_en_period = truncated.rfind('.')
        last_question = truncated.rfind('？')
        last_exclamation = truncated.rfind('！')
        last_q_mark = truncated.rfind('?')
        last_excl_mark = truncated.rfind('!')

        end_positions = [pos for pos in [last_jp_period, last_en_period, last_question,
                                        last_exclamation, last_q_mark, last_excl_mark] if pos > 0]

        if end_positions:
            # Use the latest sentence ending
            last_end = max(end_positions)
            summary = summary[:last_end + 1]
        else:
            # If no sentence ending found, just truncate and add a period
            summary = truncated.strip() + '。'

    # Create the tweet
    tweet_text = f"{summary}\n\n{url}"
    return tweet_text

def post_to_twitter(tweet_text):
    """Post a tweet using Twitter API v2 with improved error handling"""
    for attempt in range(MAX_RETRIES):
        try:
            debug_print(f"Authenticating with Twitter (attempt {attempt+1}/{MAX_RETRIES})...")

            auth = OAuth1(
                os.getenv('X_API_KEY'),
                os.getenv('X_API_SECRET'),
                os.getenv('X_ACCESS_TOKEN'),
                os.getenv('X_ACCESS_SECRET')
            )

            debug_print("Posting tweet...")
            debug_print(f"Tweet length: {len(tweet_text)} characters")
            debug_print(f"Full tweet content:\n{tweet_text}")

            payload = {
                "text": tweet_text
            }

            response = requests.post(
                TWITTER_API_URL,
                auth=auth,
                json=payload,
                timeout=20
            )

            debug_print(f"Twitter response: {response.status_code} - {response.text}")

            # Check for duplicate content error
            if response.status_code == 403 and "duplicate content" in response.text.lower():
                debug_print("Twitter rejected tweet as duplicate content")
                return False, "duplicate"

            # Check for rate limit error
            if response.status_code == 429:
                debug_print("Twitter rate limit reached, waiting before retry...")
                time.sleep(60)
                continue

            return response.status_code == 201, None

        except Exception as e:
            debug_print(f"Twitter posting error (attempt {attempt+1}): {str(e)}")
            time.sleep(5)

    debug_print("All attempts to post to Twitter failed")
    return False, "error"

def update_posted_data(article, posted_data):
    """Update the posted data with a new article"""
    url = article['url']
    title = article['title']

    # Add URL to posted list (keep last 100)
    if len(posted_data['posted_urls']) >= 100:
        posted_data['posted_urls'].pop(0)
    posted_data['posted_urls'].append(url)

    # Add title to posted list (keep last 100)
    if len(posted_data['posted_titles']) >= 100:
        posted_data['posted_titles'].pop(0)
    posted_data['posted_titles'].append(title)

    # Update last post time
    posted_data['last_post_time'] = time.time()

    # Save updated data
    save_posted_articles(posted_data)

def main():
    debug_print("=" * 50)
    debug_print("Starting Georgia News Bot (SIMPLE VERSION)...")
    debug_print("=" * 50)

    # Verify environment variables
    required_vars = ['X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_SECRET']

    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        debug_print(f"Missing required environment variables: {', '.join(missing_vars)}")
        return

    # Load previously posted articles
    posted_data = load_posted_articles()

    # Check if enough time has passed since the last post
    current_time = time.time()
    time_since_last_post = current_time - posted_data.get('last_post_time', 0)
    hours_since_last_post = time_since_last_post / 3600

    if hours_since_last_post < HOURS_BETWEEN_POSTS:
        debug_print(f"Only {hours_since_last_post:.1f} hours since last post. Minimum is {HOURS_BETWEEN_POSTS} hours. Skipping.")
        return

    # Get latest articles
    articles = get_articles()
    if not articles:
        debug_print("No articles found.")
        return

    # Filter out articles that have already been posted
    new_articles = []
    for article in articles:
        if article['url'] not in posted_data['posted_urls'] and article['title'] not in posted_data['posted_titles']:
            new_articles.append(article)

    if not new_articles:
        debug_print("No new articles to post.")
        return

    # Randomly select an article to post (to avoid always posting the same one)
    selected_article = random.choice(new_articles)
    debug_print(f"Selected article: {selected_article['title']}")

    # Get article content
    content = get_article_content(selected_article['url'])
    debug_print(f"Article content length: {len(content) if content else 0} chars")

    # Create tweet with engaging summary
    tweet_text = create_tweet(selected_article['title'], content, selected_article['url'])

    debug_print("Final tweet content:")
    debug_print(tweet_text)

    # Post to Twitter
    success, error_type = post_to_twitter(tweet_text)

    if success:
        debug_print("Successfully posted to Twitter!")
        update_posted_data(selected_article, posted_data)
    else:
        if error_type == "duplicate":
            debug_print("Twitter rejected as duplicate content. Trying with a modified tweet...")

            # Try with a slightly modified summary
            if content:
                # Add an engaging question or statement to make the content unique
                engaging_additions = [
                    "詳細はこちらをご覧ください。",
                    "この展開にどう思いますか？",
                    "重要な情報です。",
                    "最新の展開をお知らせします。",
                    "注目すべき状況です。"
                ]

                # Choose a random addition
                addition = random.choice(engaging_additions)

                # Create a new summary with the addition
                if not content.endswith('。'):
                    content += '。'
                content += ' ' + addition

                modified_tweet = create_tweet(selected_article['title'], content, selected_article['url'])
            else:
                # If no content, just modify the title
                modified_title = selected_article['title'] + "について詳しくはこちら。"
                modified_tweet = create_tweet(modified_title, None, selected_article['url'])

            debug_print(f"Modified tweet:\n{modified_tweet}")

            # Try posting again
            retry_success, _ = post_to_twitter(modified_tweet)
            if retry_success:
                debug_print("Successfully posted modified tweet!")
                update_posted_data(selected_article, posted_data)
            else:
                debug_print("Failed to post modified tweet. Skipping this article.")
        else:
            debug_print(f"Failed to post about: {selected_article['title']}")

if __name__ == "__main__":
    main()
