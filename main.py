import os
import asyncio
import requests
import subprocess
import json
import feedparser
import tempfile
import random
import base64
import hashlib
import edge_tts
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

GROQ_API_KEY          = os.environ['GROQ_API_KEY']
PEXELS_API_KEY        = os.environ['PEXELS_API_KEY']
YOUTUBE_CLIENT_ID     = os.environ['YOUTUBE_CLIENT_ID']
YOUTUBE_CLIENT_SECRET = os.environ['YOUTUBE_CLIENT_SECRET']
YOUTUBE_REFRESH_TOKEN = os.environ['YOUTUBE_REFRESH_TOKEN']

VIDEOS_PER_RUN = 6

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ EXPANDED RSS FEEDS (8 sources!) ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
RSS_FEEDS = [
    'https://feeds.reuters.com/reuters/businessNews',
    'https://finance.yahoo.com/news/rssindex',
    'https://feeds.a.dj.com/rss/RSSMarketsMain.xml',
    'https://www.cnbc.com/id/10000664/device/rss/rss.html',
    'https://feeds.bloomberg.com/markets/news.rss',
    'https://www.marketwatch.com/rss/topstories',
    'https://www.investing.com/rss/news.rss',
    'https://feeds.feedburner.com/TheStreet-MarketNews',
]

PEXELS_QUERIES = [
    'stock market trading', 'financial charts', 'wall street',
    'business economy', 'investment money', 'cryptocurrency bitcoin',
    'real estate market', 'federal reserve bank'
]

SEEN_TITLES_FILE = '/tmp/seen_titles.json'

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 1. DUPLICATE DETECTION ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def load_seen_titles():
    """Load previously used article titles from GitHub Gist or temp file."""
    github_token = os.environ.get('GITHUB_TOKEN')
    if github_token:
        try:
            # Try to load from GitHub Gist for persistence across runs
            resp = requests.get(
                'https://api.github.com/gists',
                headers={'Authorization': f'token {github_token}'},
                params={'per_page': 10}
            )
            for gist in resp.json():
                if gist.get('description') == 'youtube-bot-seen-titles':
                    content = requests.get(
                        list(gist['files'].values())[0]['raw_url']
                    ).json()
                    return set(content.get('titles', []))
        except Exception as e:
            print(f'Could not load seen titles from Gist: {e}')
    return set()

def save_seen_titles(titles):
    """Save used titles to GitHub Gist for persistence."""
    github_token = os.environ.get('GITHUB_TOKEN')
    if not github_token:
        return
    try:
        data = {'titles': list(titles)[-200:]}  # keep last 200
        resp = requests.get(
            'https://api.github.com/gists',
            headers={'Authorization': f'token {github_token}'},
            params={'per_page': 10}
        )
        existing_gist = None
        for gist in resp.json():
            if gist.get('description') == 'youtube-bot-seen-titles':
                existing_gist = gist['id']
                break
        gist_data = {
            'description': 'youtube-bot-seen-titles',
            'public': False,
            'files': {'seen_titles.json': {'content': json.dumps(data)}}
        }
        if existing_gist:
            requests.patch(
                f'https://api.github.com/gists/{existing_gist}',
                headers={'Authorization': f'token {github_token}'},
                json=gist_data
            )
        else:
            requests.post(
                'https://api.github.com/gists',
                headers={'Authorization': f'token {github_token}'},
                json=gist_data
            )
        print(f'ÃÂ¢ÃÂÃÂ Saved {len(titles)} seen titles to Gist')
    except Exception as e:
        print(f'Could not save seen titles: {e}')

def title_hash(title):
    return hashlib.md5(title.lower().strip()[:50].encode()).hexdigest()

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 2. FETCH NEWS ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def fetch_news(seen_titles):
    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                title = entry.get('title', '')
                h = title_hash(title)
                if h in seen_titles:
                    continue  # skip duplicate!
                articles.append({
                    'title': title,
                    'summary': entry.get('summary', '')[:300],
                    'hash': h
                })
        except Exception as e:
            print(f'RSS error {url}: {e}')
    # Shuffle for variety
    random.shuffle(articles)
    print(f'Found {len(articles)} fresh articles (duplicates filtered)')
    return articles[:25]

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 3. GENERATE SCRIPTS ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def generate_scripts(articles):
    articles_text = '\n'.join([
        f"{i+1}. {a['title']}: {a['summary']}"
        for i, a in enumerate(articles[:20])
    ])
    prompt = f"""You are a viral YouTube Shorts script writer for a finance news channel with 1M+ subscribers.

Today's headlines:
{articles_text}

Pick the {VIDEOS_PER_RUN} most engaging, shocking, or surprising stories.
For each, write a YouTube Shorts script (max 150 words, ~55 seconds spoken).

Rules:
- Hook MUST start with a number, question, or shocking statement
- Use "YOU", "YOUR money", make it personal
- Include specific $ amounts or % changes when available
- Create FOMO (fear of missing out)
- End exactly with: "Follow for daily finance news!"
- Conversational, energetic, punchy â like a breaking news anchor

TITLE FORMULA: [EMOJI] [SUBJECT] [POWER WORD IN CAPS] [%/NUMBER] â [HOOK]
Examples: "ð¨ Nvidia CRASHES 16% â Whats Next?" / "â¡ Stock EXPLODED 57% Overnight!" / "ð° Buffetts Secret 6000000pct Gain!" / "ð WARNING Your Savings at Risk NOW"
Power words to use: CRASHES EXPLODES SOARS WARNING SHOCKING URGENT SKYROCKETS

Return ONLY valid JSON array, no markdown:
[{{"title":"emoji+title max 60 chars","script":"full script","tags":["finance","money","investing","stocks"],"search_query":"pexels video search 2-3 words","emoji":"ÃÂ°ÃÂÃÂÃÂ"}}]"""

    headers = {'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'}
    payload = json.dumps({
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.85
    })
    resp = requests.post('https://api.groq.com/openai/v1/chat/completions', headers=headers, data=payload)
    if resp.status_code != 200:
        raise Exception(f'Groq API error {resp.status_code}: {resp.text}')
    text = resp.json()['choices'][0]['message']['content'].strip()
    if '```' in text:
        parts = text.split('```')
        text = parts[1] if len(parts) > 1 else parts[0]
        if text.startswith('json'):
            text = text[4:]
    return json.loads(text.strip())

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 4. GENERATE AUDIO ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
async def generate_audio(script, output_path):
    communicate = edge_tts.Communicate(script, voice='en-US-GuyNeural', rate='+10%')
    await communicate.save(output_path)

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 5. DOWNLOAD PEXELS VIDEO ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def download_pexels_video(query, output_path):
    headers = {'Authorization': PEXELS_API_KEY}
    url = f'https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=15&size=medium'
    resp = requests.get(url, headers=headers)
    videos = resp.json().get('videos', [])
    if not videos:
        resp = requests.get(
            'https://api.pexels.com/videos/search?query=finance+business&orientation=portrait&per_page=15&size=medium',
            headers=headers
        )
        videos = resp.json().get('videos', [])
    if not videos:
        raise Exception(f'No Pexels videos for: {query}')
    video = random.choice(videos[:5])
    good_files = [f for f in video['video_files'] if f.get('width', 9999) <= 1080]
    video_files = sorted(good_files or video['video_files'], key=lambda x: x.get('width', 0), reverse=True)
    r = requests.get(video_files[0]['link'], stream=True)
    with open(output_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 6. CREATE THUMBNAIL ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def create_thumbnail(video_path, title, emoji, output_path):
    try:
        frame_path = output_path.replace('.jpg', '_frame.jpg')
        subprocess.run(
            ['ffmpeg', '-y', '-ss', '1', '-i', video_path, '-vframes', '1', '-vf', 'scale=1280:720', frame_path],
            check=True, capture_output=True
        )
        safe_title = title.replace("'", "\\'").replace(":", "\\:").replace("%", "\\%")[:40]
        subprocess.run([
            'ffmpeg', '-y', '-i', frame_path, '-vf',
            f"drawtext=text='{safe_title}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=h-100:box=1:boxcolor=black@0.6:boxborderw=10",
            output_path
        ], check=True, capture_output=True)
        os.remove(frame_path)
        return output_path
    except Exception as e:
        print(f'Thumbnail failed: {e}')
        return None

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 7. CREATE SHORTS VIDEO ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def create_shorts_video(video_path, audio_path, output_path, title='', emoji='Ã°ÂÂÂ'):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip())

    # Build visual overlay: dark gradient + title text + branding
    safe_title = title.replace("'", "").replace('"', '').replace(':', ' ').replace('%', 'pct')[:35]
    safe_title_upper = safe_title.upper()

    # Multi-line title: split into 2 lines if long
    words = safe_title_upper.split()
    mid = len(words) // 2
    line1 = ' '.join(words[:mid]) if len(words) > 3 else safe_title_upper
    line2 = ' '.join(words[mid:]) if len(words) > 3 else ''

    vf = (
        # Scale to shorts format
        'scale=1080:1920,'
        # Dark gradient overlay at top and bottom
        'drawbox=x=0:y=0:w=iw:h=300:color=black@0.7:t=fill,'
        'drawbox=x=0:y=1620:w=iw:h=300:color=black@0.7:t=fill,'
        # Red accent bar at top
        'drawbox=x=0:y=295:w=iw:h=8:color=0xff0000@0.9:t=fill,'
        # BREAKING NEWS label
        "drawtext=text='Ã°ÂÂÂ FINANCE NEWS':fontcolor=0xff4444:fontsize=36:x=(w-text_w)/2:y=30:box=0,"
        # Main title line 1
        f"drawtext=text='{line1}':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=100:box=0:fontweight=bold,"
    )
    if line2:
        vf += f"drawtext=text='{line2}':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=170:box=0:fontweight=bold,"

    vf += (
        # Bottom branding
        "drawtext=text='Follow for Daily Finance News!':fontcolor=0xffdd00:fontsize=38:x=(w-text_w)/2:y=1650:box=0,"
        # Watch time progress bar background
        'drawbox=x=0:y=1910:w=iw:h=10:color=white@0.3:t=fill'
    )

    cmd = [
        'ffmpeg', '-y',
        '-stream_loop', '-1', '-i', video_path,
        '-i', audio_path,
        '-map', '0:v:0', '-map', '1:a:0',
        '-vf', vf,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        '-t', str(duration),
        output_path
    ]
    subprocess.run(cmd, check=True)

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 8. AUTO SAVE REFRESH TOKEN ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def save_refresh_token_to_github(new_token):
    github_token = os.environ.get('GITHUB_TOKEN')
    github_repo = os.environ.get('GITHUB_REPO')
    if not github_token or not github_repo:
        return
    try:
        key_resp = requests.get(
            f'https://api.github.com/repos/{github_repo}/actions/secrets/public-key',
            headers={'Authorization': f'token {github_token}', 'Accept': 'application/vnd.github.v3+json'}
        )
        key_data = key_resp.json()
        from nacl import encoding, public
        pub_key = public.PublicKey(key_data['key'].encode(), encoding.Base64Encoder())
        encrypted = base64.b64encode(public.SealedBox(pub_key).encrypt(new_token.encode())).decode()
        requests.put(
            f'https://api.github.com/repos/{github_repo}/actions/secrets/YOUTUBE_REFRESH_TOKEN',
            headers={'Authorization': f'token {github_token}', 'Accept': 'application/vnd.github.v3+json'},
            json={'encrypted_value': encrypted, 'key_id': key_data['key_id']}
        )
        print('ÃÂ¢ÃÂÃÂ New refresh token saved to GitHub Secrets!')
    except Exception as e:
        print(f'WARNING: Could not save token: {e}')

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 9. GET YOUTUBE SERVICE ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def get_youtube_service():
    creds = Credentials(
        token=None, refresh_token=YOUTUBE_REFRESH_TOKEN,
        client_id=YOUTUBE_CLIENT_ID, client_secret=YOUTUBE_CLIENT_SECRET,
        token_uri='https://oauth2.googleapis.com/token'
    )
    try:
        creds.refresh(Request())
        if creds.refresh_token and creds.refresh_token != YOUTUBE_REFRESH_TOKEN:
            print('New refresh token received, saving...')
            save_refresh_token_to_github(creds.refresh_token)
    except Exception as e:
        print(f'Token refresh note: {e}')
    return build('youtube', 'v3', credentials=creds)

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 10. UPLOAD TO YOUTUBE ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def upload_to_youtube(youtube, video_path, title, tags, thumbnail_path=None):
    description = (
        f"{title}\n\n"
        "Stay ahead of the markets! We break down the biggest finance stories "
        "every day in 60 seconds — fast, clear, straight to the point.\n\n"
        "New videos every morning & evening — subscribe now!\n\n"
        "ÃÂ¢ÃÂÃÂ¡ Subscribe for daily finance news!\n"
        "ÃÂ°ÃÂÃÂÃÂ Stock market updates\n"
        "ÃÂ°ÃÂÃÂÃÂ° Investing insights\n"
        "ÃÂ°ÃÂÃÂÃÂ¦ Economic analysis\n\n"
        "#Shorts #Finance #Money #Investing #StockMarket #FinanceNews #WallStreet #Trading #DayTrading #FinancialNews #WealthBuilding #PassiveIncome #PersonalFinance #StockTips #MarketNews"
    )
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags + ['shorts', 'finance', 'money', 'investing', 'stockmarket', 'trading'],
            'categoryId': '25',
            'defaultLanguage': 'en',
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False,
            'madeForKids': False,
        }
    }
    media = MediaFileUpload(video_path, mimetype='video/mp4', resumable=True, chunksize=1024*1024)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f'  Upload {int(status.progress() * 100)}%')
    video_id = response['id']
    print(f'ÃÂ¢ÃÂÃÂ Uploaded: https://youtube.com/shorts/{video_id}')
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype='image/jpeg')
            ).execute()
            print('ÃÂ¢ÃÂÃÂ Thumbnail set!')
        except Exception as e:
            print(f'Thumbnail skipped: {e}')
    return video_id

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 11. MAIN ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
async def main():
    print('ÃÂ°ÃÂÃÂÃÂ Starting YouTube Finance Shorts Bot...')

    # Load seen titles for duplicate detection
    print('Loading seen titles for duplicate detection...')
    seen_titles = load_seen_titles()
    print(f'Loaded {len(seen_titles)} seen titles')

    print('Fetching fresh news...')
    articles = fetch_news(seen_titles)

    print('Generating viral scripts with Groq (Llama)...')
    scripts = generate_scripts(articles)
    print(f'Generated {len(scripts)} scripts')

    youtube = get_youtube_service()
    success = 0
    used_hashes = set()

    for i, item in enumerate(scripts):
        print(f'\n--- Video {i+1}/{len(scripts)}: {item["title"]} ---')
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                audio_path     = os.path.join(tmpdir, 'audio.mp3')
                video_raw      = os.path.join(tmpdir, 'raw.mp4')
                video_out      = os.path.join(tmpdir, 'output.mp4')
                thumbnail_path = os.path.join(tmpdir, 'thumb.jpg')

                print('  ÃÂ°ÃÂÃÂÃÂÃÂ¯ÃÂ¸ÃÂ  Generating audio...')
                await generate_audio(item['script'], audio_path)

                print('  ÃÂ°ÃÂÃÂÃÂ¬  Downloading Pexels video...')
                download_pexels_video(
                    item.get('search_query', random.choice(PEXELS_QUERIES)),
                    video_raw
                )

                print('  ÃÂ¢ÃÂÃÂÃÂ¯ÃÂ¸ÃÂ   Creating Shorts video...')
                create_shorts_video(video_raw, audio_path, video_out, title=item['title'], emoji=item.get('emoji','Ã°ÂÂÂ'))

                print('  ÃÂ°ÃÂÃÂÃÂ¼ÃÂ¯ÃÂ¸ÃÂ   Creating thumbnail...')
                thumb = create_thumbnail(video_out, item['title'], item.get('emoji', 'ÃÂ°ÃÂÃÂÃÂ'), thumbnail_path)

                print('  ÃÂ°ÃÂÃÂÃÂ¤  Uploading to YouTube...')
                upload_to_youtube(youtube, video_out, item['title'], item['tags'], thumb)
                success += 1

                # Mark as seen
                h = title_hash(item['title'])
                seen_titles.add(h)
                used_hashes.add(h)

        except Exception as e:
            print(f'  ÃÂ¢ÃÂÃÂ ERROR on video {i+1}: {e} ÃÂ¢ÃÂÃÂ skipping!')
            continue

    # Save updated seen titles
    if used_hashes:
        save_seen_titles(seen_titles)

    print(f'\nÃÂ°ÃÂÃÂÃÂ Done! {success}/{len(scripts)} videos uploaded.')

if __name__ == '__main__':
    asyncio.run(main())
