import os
import requests
import json
import time
import random
import re
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from requests_oauthlib import OAuth1

# Load environment variables
load_dotenv()

# Configuration
GEORGIA_NEWS_URL = "https://www.georgia-news-japan.online/"
TWITTER_API_URL = "https://api.twitter.com/2/tweets"
# Constants
MAX_RETRIES = 2  # 3回から2回に減らす
MAX_TWEET_LENGTH = 200  # 短めに設定
URL_LENGTH = 23  # Twitterでの短縮URL長
ENABLE_URL_SHORTENING = True  # URL短縮機能の有効/無効
HOURS_BETWEEN_POSTS = 1  # 投稿間隔（時間）
POSTED_ARTICLES_FILE = "posted_articles_openrouter.json"
ENABLE_URL_SHORTENING = True  # URL短縮機能を有効化

# OpenRouter API settings
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')  # 環境変数から取得
OPENROUTER_MODEL = "mistralai/devstral-small:free"  # 無料枠で使用可能なモデル

# Debug print function
def debug_print(message):
    """Print debug messages and save to log file"""
    print(f"[DEBUG] {message}")
    # デバッグ出力をファイルにも保存
    with open("openrouter_debug.log", "a", encoding="utf-8") as log_file:
        log_file.write(f"[DEBUG] {message}\n")

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
            
            # Save raw HTML for debugging if needed
            # with open('debug_article_raw.html', 'w', encoding='utf-8') as f:
            #     f.write(response.text)

            # Try to find the article content
            # First look for article or main tags
            article_content = ""
            article_tag = soup.find('article') or soup.find('main')
            
            if article_tag:
                # Extract all paragraphs from the article
                paragraphs = article_tag.find_all('p')
                if paragraphs:
                    article_content = "\n".join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20])
            
            # If no article content found, try to find any div with substantial text
            if not article_content:
                # Try to find paragraphs
                paragraphs = soup.find_all('p')
                if paragraphs:
                    valid_paragraphs = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
                    if valid_paragraphs:
                        article_content = "\n".join(valid_paragraphs)
                        debug_print(f"Found content: {len(article_content)} chars")
                        return article_content

                # If no paragraphs found, try to find any div with substantial text
                divs = soup.find_all('div')
                div_texts = []
                for div in divs:
                    text = div.get_text(strip=True)
                    if len(text) > 100:
                        div_texts.append(text)
                if div_texts:
                    article_content = max(div_texts, key=len)
                    debug_print(f"Found content using divs: {len(article_content)} chars")
                    return article_content

            if article_content:
                debug_print(f"Found article content: {len(article_content)} chars")
                return article_content
            else:
                debug_print("Could not extract article content")
                time.sleep(2)

        except Exception as e:
            debug_print(f"Error fetching article content (attempt {attempt+1}): {str(e)}")
            time.sleep(2)

    debug_print("All attempts to fetch article content failed")
    return None

def generate_tweet_with_openrouter(title, content, url):
    """OpenRouter APIを使用してツイートを生成する"""
    try:
        # プロンプトの作成
        prompt = f"""以下の記事タイトルと内容から、Twitterに投稿する魅力的なツイートを日本語で作成してください。

記事タイトル: {title}
記事内容: {content}

要件:
- 最大全角130文字以内（URLは含めない）
- 記事の最も重要なポイントを簡潔に伝える
- 記事の背景情報や重要な詳細を含める
- 政治的な記事の場合は、関係者の立場や対立点を明確にする
- 関連する歴史的背景や地域情勢についても触れる
- 魅力的で興味を引く表現を使う
- 必ず文の最後は「。」で終わるようにする（途中で切れないこと、文章は必ず綺麗に完結させること）。
- ツイートの最後、文末は必ず「。」で終わるようにする。「。」で終わらないような文章はそもそもツイートに含めないように。
- 日本語で書く
- 「詳細はこちら」「続きを読む」などの表現は不要
- URLは含めない（別途追加されます）"""
        
        debug_print(f"OpenRouter API prompt: {prompt}")
        
        # OpenRouter APIへのリクエスト
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "mistralai/devstral-small:free",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 300,  # トークン数をさらに制限
            },
        )
        
        # レスポンスの処理
        response_json = response.json()
        debug_print(f"OpenRouter API response: {json.dumps(response_json, ensure_ascii=False)}")
        
        # 生成されたツイートの取得
        tweet = response_json["choices"][0]["message"]["content"]
        debug_print(f"Generated raw tweet: {tweet}")
        
        # 不適切なコンテンツのフィルタリング
        # 日本語、一部の英数字、句読点のみを保持
        filtered_tweet = ""
        
        # まず不要な単語を削除
        tweet = re.sub(r'\bGem\b', '', tweet)
        
        # 重要な英字を一時的に特殊文字に置換して保護
        tweet = re.sub(r'\bGDP\b', '<<GDP>>', tweet)
        tweet = re.sub(r'\bIT\b', '<<IT>>', tweet)
        tweet = re.sub(r'\bEU\b', '<<EU>>', tweet)
        
        for line in tweet.split('\n'):
            # 日本語の文字と基本的な句読点のみを保持
            # ひらがな、カタカナ、漢字、全角・半角の数字、句読点、括弧のみを許可
            japanese_content = re.findall(r'[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\u3400-\u4DBF\uFF10-\uFF19\s。、！？!?・：；()（）「」『』％%\d]|<<GDP>>|<<IT>>|<<EU>>', line)
            if japanese_content:
                filtered_tweet += ''.join(japanese_content)
        
        # 保護した英字を元に戻す
        filtered_tweet = filtered_tweet.replace('<<GDP>>', 'GDP')
        filtered_tweet = filtered_tweet.replace('<<IT>>', 'IT')
        filtered_tweet = filtered_tweet.replace('<<EU>>', 'EU')
        
        # 連続する空白の削除と整形
        filtered_tweet = re.sub(r'\s+', ' ', filtered_tweet).strip()
        
        # 不自然な記号の連続を削除
        filtered_tweet = re.sub(r'[\.,。、！？!?・：；]{2,}', '.', filtered_tweet)
        
        # フィルタリング結果のログ出力
        debug_print(f"Filtered tweet: {filtered_tweet}")
        
        # フィルタリング後のツイートが空の場合や短すぎる場合、タイトルを使用
        if not filtered_tweet or len(filtered_tweet) < 10:  # 10文字未満は意味のある内容とは考えにくい
            debug_print("Filtered tweet is too short or empty, using title instead")
            filtered_tweet = title
        
        # ツイートの長さを制限（MAX_TWEET_LENGTH - URL_LENGTH - 1の70%まで）
        max_content_length = int((MAX_TWEET_LENGTH - URL_LENGTH - 1) * 0.7)
        if len(filtered_tweet) > max_content_length:
            # 文末で切る（。、！？.!?）
            end_chars = ["。", "、", "！", "？", ".", "!", "?"]
            
            # 最大長の50%以降で最も近い文末を探す
            threshold = int(max_content_length * 0.5)
            last_end_pos = -1
            
            for i in range(threshold, max_content_length):
                if i < len(filtered_tweet) and filtered_tweet[i] in end_chars:
                    last_end_pos = i
            
            if last_end_pos != -1:
                filtered_tweet = filtered_tweet[:last_end_pos + 1]
            else:
                # 文末が見つからない場合は単純に切って「...」を追加
                filtered_tweet = filtered_tweet[:max_content_length - 3] + "..."
        
        tweet = filtered_tweet
        
        # 不要な表現の削除
        tweet = re.sub(r'(詳細はこちら|続きを読む|詳しくは下記リンクをご覧ください|詳細は以下のリンクから)[\s\S]*', '', tweet)
        
        # URLの削除（別途追加するため）
        tweet = re.sub(r'https?://[\w/:%#\$&\?\(\)~\.=\+\-]+', '', tweet)
        
        # 文字数の調整（MAX_TWEET_LENGTH - URLの長さ - スペース1文字）
        max_content_length = MAX_TWEET_LENGTH - URL_LENGTH - 1
        
        # 文章が途中で切れないように調整
        if len(tweet) > max_content_length:
            # 文末で切る（。、！？.!?）
            end_chars = ["。"]
            
            # 最大長の50%以降で最も近い文末を探す
            threshold = int(max_content_length * 0.5)
            last_end_pos = -1
            
            for i in range(threshold, max_content_length):
                if i < len(tweet) and tweet[i] in end_chars:
                    last_end_pos = i
            
            if last_end_pos != -1:
                tweet = tweet[:last_end_pos + 1]
            else:
                # 文末が見つからない場合は単純に切って「...」を追加
                tweet = tweet[:max_content_length - 3] + "..."
        
        # URLを短縮して追加
        debug_print(f"元のURL: {url}")
        shortened_url = shorten_url(url)
        debug_print(f"短縮後のURL: {shortened_url}")
        final_tweet = f"{tweet} {shortened_url}"
        debug_print(f"Final tweet: {final_tweet}")
        
        return final_tweet
    except Exception as e:
        debug_print(f"Error generating tweet with OpenRouter: {str(e)}")
        # エラーが発生した場合はシンプルなツイートを返す
        return f"{title[:100]}... {url}"

def shorten_url(url):
    """Shorten a URL using shrtco.de API with fallback to tinyurl"""
    # Skip URL shortening if disabled
    if not ENABLE_URL_SHORTENING:
        debug_print("URL shortening is disabled")
        return url

    debug_print(f"URL短縮を開始: {url}")
    
    # Try shrtco.de first
    try:
        debug_print("shrtco.deでURL短縮を試みます...")
        response = requests.get(f"https://api.shrtco.de/v2/shorten?url={url}", timeout=10)
        response.raise_for_status()

        data = response.json()
        debug_print(f"shrtco.de API response: {json.dumps(data, ensure_ascii=False)}")
        
        if data.get('ok'):
            short_url = data['result']['full_short_link']
            debug_print(f"shrtco.deでURL短縮成功: {short_url}")
            return short_url
        else:
            debug_print(f"shrtco.de API error: {data.get('error', 'Unknown error')}")
    except requests.exceptions.RequestException as e:
        debug_print(f"shrtco.de request error: {str(e)}")
    except ValueError as e:
        debug_print(f"shrtco.de JSON parse error: {str(e)}")
    except Exception as e:
        debug_print(f"shrtco.de unexpected error: {str(e)}")
    
    debug_print("tinyurlでURL短縮を試みます...")
    
    # Fallback to tinyurl
    try:
        response = requests.get(f"https://tinyurl.com/api-create.php?url={url}", timeout=10)
        debug_print(f"tinyurl API status code: {response.status_code}")
        
        if response.status_code == 200:
            short_url = response.text
            debug_print(f"tinyurlでURL短縮成功: {short_url}")
            return short_url
        else:
            debug_print(f"tinyurl API error: Status code {response.status_code}, Response: {response.text}")
    except requests.exceptions.RequestException as e:
        debug_print(f"tinyurl request error: {str(e)}")
    except Exception as e:
        debug_print(f"tinyurl unexpected error: {str(e)}")

    debug_print("すべてのURL短縮サービスが失敗しました。元のURLを使用します。")
    return url

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
                # Twitter APIのレート制限は15分間のウィンドウなので、より長く待機
                wait_time = 900 + (attempt * 300)  # 15分 + 追加待機時間
                debug_print(f"Twitter rate limit reached, waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
                continue

            # 成功した場合
            if response.status_code == 201:
                return True, None
            
            # その他のエラーの場合、最後の試行でなければ短い待機
            if attempt < MAX_RETRIES - 1:
                debug_print(f"Request failed with status {response.status_code}, waiting before retry...")
                time.sleep(30)

        except Exception as e:
            debug_print(f"Twitter posting error (attempt {attempt+1}): {str(e)}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(30)

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
    debug_print("Starting Georgia News Bot with OpenRouter LLM...")
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

    if not content or len(content) < 50:
        debug_print("Article content too short or not found. Using title only.")
        content = selected_article['title']

    # Generate tweet with LLM
    tweet_text = generate_tweet_with_openrouter(selected_article['title'], content, selected_article['url'])

    # Post to Twitter
    success, error_type = post_to_twitter(tweet_text)

    if success:
        debug_print("Successfully posted to Twitter!")
        update_posted_data(selected_article, posted_data)
    else:
        if error_type == "duplicate":
            debug_print("Twitter rejected as duplicate content. Trying with a modified tweet...")
            
            # Try with a slightly modified prompt
            modified_tweet = generate_tweet_with_openrouter(selected_article['title'], content, selected_article['url'])
            
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