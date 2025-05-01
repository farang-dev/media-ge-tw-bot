import os
import requests
import json
import time
import hashlib
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from requests_oauthlib import OAuth1

# Load environment variables
load_dotenv()

# Configuration
GEORGIA_NEWS_URL = "https://www.georgia-news-japan.online/"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TWITTER_API_URL = "https://api.twitter.com/2/tweets"
MAX_TWEET_LENGTH = 280
POSTED_ARTICLES_FILE = "posted_articles_fixed.json"
ARTICLES_TO_TRACK = 50  # Track more articles to better detect duplicates
MINIMUM_HOURS_BETWEEN_POSTS = 3  # At least 3 hours between posts
SIMILARITY_THRESHOLD = 0.4  # Lower threshold to be more strict about similarity
MAX_SUMMARY_LENGTH = 200  # Maximum length for summary (to leave room for URL)

# Debug print function
def debug_print(message):
    """Print debug messages"""
    print(f"[DEBUG] {message}")

def get_content_hash(text):
    """Generate a hash of the content to detect similar articles"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def load_posted_articles():
    """Load the list of previously posted articles"""
    try:
        # First try to load from the main file
        if os.path.exists(POSTED_ARTICLES_FILE):
            with open(POSTED_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                debug_print(f"Loaded {len(data['posted'])} posted articles")
                return data

        # If file doesn't exist, create a new one
        debug_print("No posted articles file found, creating new record")
        new_data = {
            "posted": [],
            "content_hashes": [],
            "last_post_time": 0
        }

        with open(POSTED_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)

        return new_data
    except Exception as e:
        debug_print(f"Error loading posted articles: {str(e)}")
        return {
            "posted": [],
            "content_hashes": [],
            "last_post_time": 0
        }

def save_posted_articles(posted_data):
    """Save the list of posted articles"""
    try:
        with open(POSTED_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(posted_data, f, ensure_ascii=False, indent=2)
        debug_print(f"Saved {len(posted_data['posted'])} posted articles")
    except Exception as e:
        debug_print(f"Error saving posted articles: {str(e)}")

def get_articles():
    """Scrape articles from Georgia News Japan"""
    try:
        debug_print("Fetching articles...")
        response = requests.get(GEORGIA_NEWS_URL, timeout=10)
        debug_print(f"Website status code: {response.status_code}")

        soup = BeautifulSoup(response.text, 'html.parser')

        articles = []
        links = soup.find_all('a', href=True)
        debug_print(f"Found {len(links)} links on the page")

        for i, link in enumerate(links):
            url = link['href']
            title = link.get_text(strip=True)

            if not title or len(title) < 10:
                continue

            if not url.startswith('http'):
                url = f"{GEORGIA_NEWS_URL.rstrip('/')}{url}"

            if '/post/' in url:
                articles.append({'title': title, 'url': url})
                debug_print(f"Found article: {title[:50]}...")

        debug_print(f"Found {len(articles)} potential articles")
        return articles[:ARTICLES_TO_TRACK]

    except Exception as e:
        debug_print(f"Error fetching articles: {str(e)}")
        return []

def get_article_content(url):
    """Scrape the content of an article from georgia-news-japan.online"""
    try:
        debug_print(f"Fetching article content from: {url}")
        response = requests.get(url, timeout=15)

        if response.status_code != 200:
            debug_print(f"Failed to fetch article, status code: {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Try multiple approaches to extract content
        content = None

        # Try to find paragraphs
        paragraphs = soup.find_all('p')
        if paragraphs:
            # Filter out very short paragraphs (likely navigation or metadata)
            valid_paragraphs = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
            if valid_paragraphs:
                content = ' '.join(valid_paragraphs)
                debug_print(f"Found content using paragraphs: {len(valid_paragraphs)} paragraphs")

        # If no paragraphs found, try to find any div with substantial text
        if not content or len(content) < 50:
            divs = soup.find_all('div')
            div_texts = []
            for div in divs:
                text = div.get_text(strip=True)
                if len(text) > 100:  # Only consider divs with substantial text
                    div_texts.append(text)
            if div_texts:
                content = max(div_texts, key=len)  # Use the longest text
                debug_print(f"Found content using divs: {len(div_texts)} divs with substantial text")

        if content:
            debug_print(f"Successfully extracted content ({len(content)} chars)")
            debug_print(f"Content preview: {content[:100]}...")
            return content
        else:
            debug_print("Could not extract article content using any method")
            return None

    except Exception as e:
        debug_print(f"Error fetching article content: {str(e)}")
        return None

def ensure_complete_sentences(text, max_length=200):
    """Ensure text ends with complete sentences and doesn't exceed max_length"""
    if not text:
        return ""

    # If text is already short enough, return it
    if len(text) <= max_length:
        # Check if it ends with a sentence ending
        if text.endswith('。') or text.endswith('.') or text.endswith('？') or text.endswith('！'):
            return text
        else:
            # If it doesn't end with a sentence ending, add a period
            return text + '。'

    # Find the last sentence end within the max length
    truncated = text[:max_length]

    # Look for Japanese period
    last_jp_period = truncated.rfind('。')
    # Look for Western period
    last_en_period = truncated.rfind('.')
    # Look for other sentence endings
    last_question = truncated.rfind('？')
    last_exclamation = truncated.rfind('！')

    # Find the latest sentence end
    end_positions = [pos for pos in [last_jp_period, last_en_period, last_question, last_exclamation] if pos > 0]

    if end_positions:
        # Use the latest sentence end
        last_end = max(end_positions)
        return text[:last_end + 1]

    # If no sentence end found, look for a good breaking point
    last_comma = truncated.rfind('、')
    if last_comma > max_length * 0.7:  # Only use comma if it's far enough into the text
        return text[:last_comma + 1] + '。'  # Add a period to complete the sentence

    # If we get here, we couldn't find a good breaking point
    # Try to find the last complete word
    words = text[:max_length].split()
    if words:
        # Join all words except the last one (which might be cut off)
        complete_text = ' '.join(words[:-1])
        if len(complete_text) > max_length * 0.7:  # Only use if it's substantial
            return complete_text + '。'  # Add a period to complete the sentence

    # Last resort: truncate and add a period
    return truncated + '。'

def summarize_article(title, content):
    """Generate summary using OpenRouter API with article content, with fallback"""
    try:
        debug_print(f"Summarizing article: {title[:50]}...")

        # Check if OpenRouter API key is available
        if not os.getenv('OPENROUTER_API_KEY'):
            debug_print("No OpenRouter API key found, using local summarization")
            return generate_summary_from_content(title, content)

        headers = {
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Georgia News Bot",
            "Content-Type": "application/json"
        }

        # Use content if available, otherwise just use the title
        if content:
            prompt = f"""この記事を簡潔に要約してください。以下の条件を守ってください：
1. 200文字以内で完結させる
2. 必ず完全な文で終わらせる（文の途中で切れないこと）
3. 「最新」や「【ジョージア最新情報】」などの接頭辞は絶対に付けないでください
4. 読者の興味を引く魅力的な文章で書いてください
5. ハッシュタグは使用しない
6. 記事の主要な情報を含める
7. 要約は「ジョージア」または記事の主題から始めてください
8. 文章は必ず完結させてください。途中で切れた文章は絶対に避けてください。

タイトル: {title}

内容: {content[:2000]}"""
        else:
            prompt = f"""この記事のタイトルから内容を推測して要約してください。以下の条件を守ってください：
1. 200文字以内で完結させる
2. 必ず完全な文で終わらせる（文の途中で切れないこと）
3. 「最新」や「【ジョージア最新情報】」などの接頭辞は絶対に付けないでください
4. 読者の興味を引く魅力的な文章で書いてください
5. ハッシュタグは使用しない
6. 要約は「ジョージア」または記事の主題から始めてください
7. 文章は必ず完結させてください。途中で切れた文章は絶対に避けてください。

タイトル: {title}"""

        payload = {
            "model": "anthropic/claude-3-haiku-20240307",
            "messages": [{
                "role": "user",
                "content": prompt
            }]
        }

        try:
            response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
            response.raise_for_status()

            data = response.json()
            debug_print(f"OpenRouter response: {data}")

            if 'choices' in data and data['choices']:
                summary = data['choices'][0]['message']['content']
                # Remove any prefixes that might have been added despite instructions
                summary = remove_prefixes(summary)
                # Ensure summary ends with complete sentences
                summary = ensure_complete_sentences(summary, MAX_SUMMARY_LENGTH)
                debug_print(f"Final summary: {summary}")
                return summary
        except Exception as e:
            debug_print(f"OpenRouter API error: {str(e)}")
            return generate_summary_from_content(title, content)

        return generate_summary_from_content(title, content)

    except Exception as e:
        debug_print(f"Summarization error: {str(e)}")

    return ensure_complete_sentences(title)

def remove_prefixes(text):
    """Remove common prefixes from the summary"""
    prefixes = [
        "最新: ", "最新：", "最新 ", "最新",
        "【ジョージア最新情報】", "【最新情報】", "【速報】",
        "ジョージア最新: ", "ジョージア: ", "ジョージア："
    ]

    for prefix in prefixes:
        if text.startswith(prefix):
            debug_print(f"Removing prefix: '{prefix}'")
            return text[len(prefix):]

    return text

def generate_summary_from_content(title, content=None):
    """Generate a summary without using external APIs"""
    try:
        debug_print(f"Generating summary from content (length: {len(content) if content else 0})")

        # If no content or very short content, just use the title with a period
        if not content or len(content) < 20:
            debug_print("Content too short, using title")
            # Add a period if the title doesn't end with one
            if not title.endswith('。') and not title.endswith('.'):
                return f"{title}。"
            return title

        # Extract complete sentences from the content
        content = content.strip()

        # Split content into paragraphs if it contains newlines
        paragraphs = content.split('\n')
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        # Get the first few paragraphs to work with
        working_paragraphs = []
        total_length = 0
        for p in paragraphs:
            if total_length < 500:  # Get enough content to work with
                working_paragraphs.append(p)
                total_length += len(p)
            else:
                break

        if not working_paragraphs:
            debug_print("No valid paragraphs found, using title")
            if not title.endswith('。') and not title.endswith('.'):
                return f"{title}。"
            return title

        # Join the working paragraphs
        working_text = ' '.join(working_paragraphs)
        debug_print(f"Working with text: {working_text[:100]}...")

        # Find complete sentences
        sentences = []
        start = 0

        # Extract sentences until we have enough for a good summary
        while start < len(working_text) and len(''.join(sentences)) < MAX_SUMMARY_LENGTH:
            # Find the next sentence end (Japanese period)
            jp_end = working_text.find('。', start)
            # Find the next western period
            en_end = working_text.find('.', start)
            # Find other sentence endings
            question_end = working_text.find('？', start)
            exclamation_end = working_text.find('！', start)

            # Find the earliest sentence end
            end_positions = []
            if jp_end != -1: end_positions.append(jp_end)
            if en_end != -1: end_positions.append(en_end)
            if question_end != -1: end_positions.append(question_end)
            if exclamation_end != -1: end_positions.append(exclamation_end)

            if not end_positions:
                # No more sentence endings
                break

            next_end = min(end_positions)

            # Extract the sentence (including the period)
            sentence = working_text[start:next_end+1]

            if len(sentence) > 10:  # Only add if it's a substantial sentence
                sentences.append(sentence)

            # Move to the next sentence
            start = next_end + 1

        if sentences:
            # Join the sentences into a summary
            summary = ''.join(sentences)

            # Ensure it's not too long and ends with complete sentences
            summary = ensure_complete_sentences(summary, MAX_SUMMARY_LENGTH)

            debug_print(f"Generated summary: {summary}")
            return summary
        else:
            # If no complete sentences found, use the title with a period
            debug_print("No complete sentences found, using title")
            if not title.endswith('。') and not title.endswith('.'):
                return f"{title}。"
            return title
    except Exception as e:
        debug_print(f"Local summarization error: {str(e)}")
        # Return title with a period
        if not title.endswith('。') and not title.endswith('.'):
            return f"{title}。"
        return title

def post_to_twitter(tweet_text):
    """Post a tweet using Twitter API v2"""
    try:
        debug_print("Authenticating with Twitter...")

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
            json=payload
        )

        debug_print(f"Twitter response: {response.status_code} - {response.text}")

        # Check for duplicate content error
        if response.status_code == 403 and "duplicate content" in response.text.lower():
            debug_print("Twitter rejected tweet as duplicate content")
            return False, "duplicate"

        return response.status_code == 201, None

    except Exception as e:
        debug_print(f"Twitter posting error: {str(e)}")
        return False, "error"

def is_similar_to_posted(article, posted_data):
    """Check if an article is similar to any recently posted articles"""
    title = article['title']
    url = article['url']

    # 1. Check if URL has been posted before
    if url in posted_data['posted']:
        debug_print(f"URL already posted: {url}")
        return True

    # 2. Extract content and generate hash
    content = get_article_content(url)
    if not content:
        debug_print("Could not extract content, using title only for similarity check")
        content = title

    content_hash = get_content_hash(content)

    # 3. Check if content hash matches any previously posted article
    if content_hash in posted_data['content_hashes']:
        debug_print(f"Content hash match found: {content_hash}")
        return True

    # Not similar to any recently posted articles
    return False

def update_posted_data(article, posted_data):
    """Update the posted data with a new article"""
    url = article['url']

    # Get content and hash
    content = get_article_content(url)
    if not content:
        content = article['title']

    content_hash = get_content_hash(content)

    # Add URL to posted list
    if len(posted_data['posted']) >= ARTICLES_TO_TRACK:
        posted_data['posted'].pop(0)  # Remove oldest
    posted_data['posted'].append(url)

    # Add content hash
    if len(posted_data['content_hashes']) >= ARTICLES_TO_TRACK:
        posted_data['content_hashes'].pop(0)  # Remove oldest
    posted_data['content_hashes'].append(content_hash)

    # Update last post time
    posted_data['last_post_time'] = time.time()

    # Save updated data
    save_posted_articles(posted_data)

def main():
    debug_print("=" * 50)
    debug_print("Starting Georgia News Bot (FIXED VERSION)...")
    debug_print("=" * 50)

    # Verify environment variables
    required_vars = ['X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_SECRET']

    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        debug_print(f"Missing required environment variables: {', '.join(missing_vars)}")
        return

    if not os.getenv('OPENROUTER_API_KEY'):
        debug_print("OpenRouter API key not found, will use local summarization")
    else:
        debug_print("OpenRouter API key found, will use AI summarization")

    # Load previously posted articles
    posted_data = load_posted_articles()

    # Check if enough time has passed since the last post
    current_time = time.time()
    time_since_last_post = current_time - posted_data.get('last_post_time', 0)
    hours_since_last_post = time_since_last_post / 3600

    if hours_since_last_post < MINIMUM_HOURS_BETWEEN_POSTS:
        debug_print(f"Only {hours_since_last_post:.1f} hours since last post. Minimum is {MINIMUM_HOURS_BETWEEN_POSTS} hours. Skipping.")
        return

    # Get latest articles
    articles = get_articles()
    if not articles:
        debug_print("No articles found.")
        return

    # Find the first article that's not similar to any recently posted articles
    selected_article = None
    for article in articles:
        if not is_similar_to_posted(article, posted_data):
            selected_article = article
            debug_print(f"Selected article: {article['title']}")
            break

    if not selected_article:
        debug_print("No suitable article found to post (all are similar to recent posts).")
        return

    # Get article content
    content = get_article_content(selected_article['url'])

    # Generate summary
    summary = summarize_article(selected_article['title'], content)
    debug_print(f"Generated summary: {summary}")

    # Calculate available characters for summary
    available_chars = MAX_TWEET_LENGTH - len(selected_article['url']) - 5  # 5 for "\n\n" and some buffer

    # Always ensure summary ends with complete sentences and fits within available chars
    summary = ensure_complete_sentences(summary, available_chars)

    # Double-check that the summary is not truncated
    if not (summary.endswith('。') or summary.endswith('.') or summary.endswith('？') or summary.endswith('！')):
        debug_print("Warning: Summary does not end with a sentence ending, adding one")
        summary = summary + '。'

    # Prepare tweet text
    tweet_text = f"{summary}\n\n{selected_article['url']}"

    # Final check to ensure tweet is within character limit
    if len(tweet_text) > MAX_TWEET_LENGTH:
        debug_print(f"Warning: Tweet still too long ({len(tweet_text)} chars), truncating further")
        # Recalculate with more buffer
        available_chars = MAX_TWEET_LENGTH - len(selected_article['url']) - 10
        summary = ensure_complete_sentences(summary, available_chars)
        tweet_text = f"{summary}\n\n{selected_article['url']}"

    debug_print("Final tweet content:")
    debug_print(tweet_text)

    # Post to Twitter
    success, error_type = post_to_twitter(tweet_text)

    if success:
        debug_print("Successfully posted to Twitter!")

        # Update posted articles data
        update_posted_data(selected_article, posted_data)
    else:
        if error_type == "duplicate":
            debug_print("Twitter rejected as duplicate content. Trying with a modified summary...")

            # Try to modify the summary to make it unique
            current_time = time.strftime("%H:%M")
            modified_summary = f"{summary} (更新: {current_time})"

            # Ensure it still fits in a tweet
            if len(modified_summary) + len(selected_article['url']) + 5 > MAX_TWEET_LENGTH:
                modified_summary = ensure_complete_sentences(summary, MAX_SUMMARY_LENGTH - 15) + f" (更新: {current_time})"

            modified_tweet = f"{modified_summary}\n\n{selected_article['url']}"
            debug_print(f"Modified tweet:\n{modified_tweet}")

            # Try posting again with the modified tweet
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
