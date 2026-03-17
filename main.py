import os
import re
import time
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
from datetime import datetime
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

VOICES = [
    ('en-US-GuyNeural',    '+10%', '+0Hz'),
    ('en-US-AndrewNeural', '+8%',  '+0Hz'),
    ('en-US-EricNeural',   '+10%', '+2Hz'),
    ('en-US-BrianNeural',  '+8%',  '+0Hz'),
]
_voice_idx = [0]

FONT = '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 1. DUPLICATE DETECTION ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def title_hash(title):
    return hashlib.md5(title.lower().strip()[:50].encode()).hexdigest()

def load_seen_titles():
    tok = os.environ.get('GITHUB_TOKEN')
    if tok:
        try:
            repo = os.environ.get('GITHUB_REPO', '')
            desc = 'seen-titles-' + repo.replace('/', '-')
            r = requests.get('https://api.github.com/gists',
                headers={'Authorization': 'token ' + tok}, params={'per_page': 10})
            for g in r.json():
                if g.get('description') == desc:
                    c = requests.get(list(g['files'].values())[0]['raw_url']).json()
                    return set(c.get('titles', []))
        except Exception as e:
            print(f'load_seen error: {e}')
    return set()

def save_seen_titles(titles):
    tok = os.environ.get('GITHUB_TOKEN')
    if not tok:
        return
    try:
        repo = os.environ.get('GITHUB_REPO', '')
        desc = 'seen-titles-' + repo.replace('/', '-')
        data = {'titles': list(titles)[-200:]}
        r = requests.get('https://api.github.com/gists',
            headers={'Authorization': 'token ' + tok}, params={'per_page': 10})
        gid = next((g['id'] for g in r.json() if g.get('description') == desc), None)
        gd = {'description': desc, 'public': False,
              'files': {'seen.json': {'content': json.dumps(data)}}}
        if gid:
            requests.patch(f'https://api.github.com/gists/{gid}',
                headers={'Authorization': 'token ' + tok}, json=gd)
        else:
            requests.post('https://api.github.com/gists',
                headers={'Authorization': 'token ' + tok}, json=gd)
        print(f'Saved {len(titles)} seen titles')
    except Exception as e:
        print(f'save_seen error: {e}')

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 2. FETCH NEWS ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def fetch_news(seen_titles):
    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                t = entry.get('title', '')
                h = title_hash(t)
                if h not in seen_titles:
                    articles.append({
                        'title': t,
                        'summary': entry.get('summary', '')[:300],
                        'hash': h
                    })
        except Exception as e:
            print(f'RSS error {url}: {e}')
    random.shuffle(articles)
    print(f'Found {len(articles)} fresh articles')
    return articles[:25]

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 3. GENERATE SCRIPTS ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def generate_scripts(articles):
    txt = '\n'.join([f"{i+1}. {a['title']}: {a['summary']}"
                     for i, a in enumerate(articles[:20])])
    prompt = f"""You are a viral YouTube Shorts script writer for a finance news channel with 1M+ subscribers.

Today's headlines:
{txt}

Pick the {VIDEOS_PER_RUN} most engaging, shocking, or surprising stories.
Write a YouTube Shorts script (max 150 words, ~55 seconds spoken).

Rules:
- Hook MUST grab attention in FIRST 2 SECONDS ÃÂ¢ÃÂÃÂ shocking number, bold claim, or urgent question
- Use "YOU", "YOUR money", make it personal
- Include specific $ amounts or % changes when available
- Create FOMO (fear of missing out)
- End EXACTLY with this phrase word-for-word: "Follow for daily finance news!"
- Conversational, energetic, punchy tone

TITLE FORMULA: [EMOJI] [SUBJECT] [POWER WORD IN CAPS] [%/NUMBER] ÃÂ¢ÃÂÃÂ [HOOK]
Examples: "ÃÂ°ÃÂÃÂÃÂ¨ Nvidia CRASHES 16% ÃÂ¢ÃÂÃÂ What's Next?" / "ÃÂ¢ÃÂÃÂ¡ Stock EXPLODED 57% Overnight!" / "ÃÂ°ÃÂÃÂÃÂ° Buffett Secret: 6000000% Gain!" / "ÃÂ°ÃÂÃÂÃÂ WARNING: Your Savings at Risk NOW"
Power words: CRASHES EXPLODES SOARS WARNING SHOCKING URGENT SKYROCKETS

Return ONLY valid JSON array, no markdown:
[{{"title":"emoji+title max 60 chars","script":"full script","tags":["finance","money","investing","stocks"],"search_query":"pexels 2-3 words","emoji":"ÃÂ°ÃÂÃÂÃÂ"}}]"""

    headers = {'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'}
    models = ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant']
    last_error = None

    for attempt in range(3):
        model = models[0] if attempt < 2 else models[1]
        try:
            payload = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.85
            })
            resp = requests.post('https://api.groq.com/openai/v1/chat/completions',
                headers=headers, data=payload, timeout=30)
            if resp.status_code == 200:
                text = resp.json()['choices'][0]['message']['content'].strip()
                if '```' in text:
                    parts = text.split('```')
                    text = parts[1] if len(parts) > 1 else parts[0]
                    if text.startswith('json'):
                        text = text[4:]
                try:
                    scripts = json.loads(text.strip())
                    print(f'Generated with {model} (attempt {attempt+1})')
                    return scripts
                except json.JSONDecodeError as je:
                    last_error = f'JSONDecodeError: {je}'
                    print(f'JSON parse error attempt {attempt+1}: {je}')
            else:
                last_error = f'HTTP {resp.status_code}'
                print(f'Groq attempt {attempt+1} failed: {last_error}')
        except Exception as e:
            last_error = str(e)
            print(f'Groq attempt {attempt+1} error: {e}')
        time.sleep(2)

    raise Exception(f'Groq failed after 3 attempts: {last_error}')

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 4. CLEAN SCRIPT FOR TTS ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def clean_script_for_tts(script):
    script = re.sub(r'[\U00010000-\U0010ffff]', '', script, flags=re.UNICODE)
    script = re.sub(r'[\U00002600-\U000027BF]', '', script, flags=re.UNICODE)
    script = re.sub(r'[\U0001F300-\U0001F9FF]', '', script, flags=re.UNICODE)
    script = re.sub(r'[*_#~|]', '', script)
    script = re.sub(r'http\S+', '', script)
    script = script.replace('#', '')
    script = re.sub(r'\s+', ' ', script).strip()
    return script

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 5. GENERATE AUDIO ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
async def generate_audio(script, output_path):
    voice, rate, pitch = VOICES[_voice_idx[0] % len(VOICES)]
    _voice_idx[0] += 1
    print(f'    Voice: {voice}')
    communicate = edge_tts.Communicate(script, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(output_path)

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 6. DOWNLOAD PEXELS VIDEO ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def _fetch_one_pexels_video(query, output_path, used_ids=None):
    """Download a single Pexels portrait video, avoiding already-used IDs."""
    headers = {'Authorization': PEXELS_API_KEY}
    used_ids = used_ids or set()
    for q in [query, 'business finance', 'stock market trading']:
        try:
            url = f'https://api.pexels.com/videos/search?query={q}&orientation=portrait&per_page=15&size=medium'
            resp = requests.get(url, headers=headers, timeout=15)
            videos = resp.json().get('videos', [])
            # Filter: min 10s, not already used
            candidates = [v for v in videos
                          if v.get('duration', 0) >= 10 and v['id'] not in used_ids]
            if candidates:
                video = random.choice(candidates[:5])
                good = [f for f in video['video_files'] if f.get('width', 9999) <= 1080]
                files = sorted(good or video['video_files'], key=lambda x: x.get('width', 0), reverse=True)
                r = requests.get(files[0]['link'], stream=True, timeout=30)
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                return video['id']
        except Exception as e:
            print(f'    Pexels fetch error ({q}): {e}')
    raise Exception(f'Could not fetch Pexels video for: {query}')

def download_pexels_video(query, output_path):
    """Download a single Pexels video (kept for compatibility)."""
    _fetch_one_pexels_video(query, output_path)

def download_pexels_multi(query, tmpdir, count=3):
    """Download multiple different Pexels videos and concat them into one."""
    import tempfile as _tf
    paths = []
    used_ids = set()
    # Use varied queries for visual diversity
    base_queries = [query, random.choice(PEXELS_QUERIES), random.choice(PEXELS_QUERIES)]
    for i in range(count):
        q = base_queries[i % len(base_queries)]
        p = os.path.join(tmpdir, f'clip_{i}.mp4')
        try:
            vid_id = _fetch_one_pexels_video(q, p, used_ids)
            used_ids.add(vid_id)
            paths.append(p)
            print(f'    Clip {i+1}/{count} downloaded')
        except Exception as e:
            print(f'    Clip {i+1} failed: {e}')
    if not paths:
        raise Exception('No Pexels clips downloaded!')
    return paths

def concat_videos(clip_paths, output_path, target_duration):
    """Concat multiple clips using FFmpeg, loop to fill target duration."""
    if len(clip_paths) == 1:
        # Single clip â just copy it
        import shutil
        shutil.copy(clip_paths[0], output_path)
        return
    # Write concat list
    list_file = output_path + '_list.txt'
    # Repeat clips enough times to cover duration
    repeats = max(1, int(target_duration / (len(clip_paths) * 8)) + 1)
    with open(list_file, 'w') as f:
        for _ in range(repeats):
            for p in clip_paths:
                f.write(f"file '{p}'\n")
    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', list_file,
        '-vf', 'scale=1080:1920',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-pix_fmt', 'yuv420p', '-r', '30',
        '-t', str(target_duration),
        output_path
    ], check=True, capture_output=True)
    os.remove(list_file)

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 7. CREATE THUMBNAIL ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def create_thumbnail(video_path, title, emoji, output_path):
    """Generate AI thumbnail via HuggingFace FLUX, fallback to FFmpeg."""
    hf_token = os.environ.get('HF_API_TOKEN')
    if hf_token:
        try:
            # Build a vivid finance-themed prompt
            safe_title = title.replace('"', '').replace("'", '')[:60]
            prompt = (
                f"Professional YouTube thumbnail, finance news, dramatic lighting, "
                f"bold text overlay space at bottom, topic: {safe_title}, "
                f"dark background, red and gold accents, cinematic, high contrast, "
                f"stock market charts, Wall Street aesthetic, 16:9 aspect ratio"
            )
            api_url = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
            headers = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}
            resp = requests.post(api_url, headers=headers,
                json={"inputs": prompt, "parameters": {"width": 1280, "height": 720, "num_inference_steps": 4}},
                timeout=60)
            if resp.status_code == 200 and resp.headers.get('content-type', '').startswith('image'):
                # Save AI image
                ai_img = output_path.replace('.jpg', '_ai.jpg')
                with open(ai_img, 'wb') as f:
                    f.write(resp.content)
                # Add title text overlay with FFmpeg
                safe = title.replace("'", "").replace('"', '').replace(':', ' ').replace('%', 'pct')[:45]
                subprocess.run([
                    'ffmpeg', '-y', '-i', ai_img, '-vf',
                    f"drawtext=fontfile={FONT}:text='{safe}':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=h-90:box=1:boxcolor=black@0.75:boxborderw=12",
                    output_path
                ], check=True, capture_output=True)
                os.remove(ai_img)
                print('    AI thumbnail generated!')
                return output_path
            else:
                print(f'    HF thumbnail failed ({resp.status_code}), using FFmpeg fallback')
        except Exception as e:
            print(f'    HF thumbnail error: {e}, using FFmpeg fallback')

    # FFmpeg fallback
    try:
        frame_path = output_path.replace('.jpg', '_frame.jpg')
        subprocess.run([
            'ffmpeg', '-y', '-ss', '1', '-i', video_path,
            '-vframes', '1', '-vf', 'scale=1280:720', frame_path
        ], check=True, capture_output=True)
        safe = title.replace("'", "").replace('"', '').replace(':', ' ').replace('%', 'pct')[:40]
        subprocess.run([
            'ffmpeg', '-y', '-i', frame_path, '-vf',
            f"drawtext=fontfile={FONT}:text='{safe}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=h-100:box=1:boxcolor=black@0.6:boxborderw=10",
            output_path
        ], check=True, capture_output=True)
        os.remove(frame_path)
        return output_path
    except Exception as e:
        print(f'Thumbnail error: {e}')
        return None

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 8. CREATE SHORTS VIDEO ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def create_shorts_video(video_path, audio_path, output_path, title='', emoji='ÃÂ°ÃÂÃÂÃÂ'):
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', audio_path
    ], capture_output=True, text=True)
    duration = float(result.stdout.strip())

    # Handle multi-clip: concat clips first, then use as single video
    if isinstance(video_path, list):
        tmp_concat = output_path + '_concat.mp4'
        concat_videos(video_path, tmp_concat, duration)
        video_path = tmp_concat
    else:
        tmp_concat = None

    safe = title.replace("'", "").replace('"', '').replace(':', ' ').replace('%', 'pct')[:35].upper()
    words = safe.split()
    mid = len(words) // 2
    line1 = ' '.join(words[:mid]) if len(words) > 3 else safe
    line2 = ' '.join(words[mid:]) if len(words) > 3 else ''

    vf = (
        'scale=1080:1920,'
        'drawbox=x=0:y=0:w=iw:h=300:color=black@0.7:t=fill,'
        'drawbox=x=0:y=1620:w=iw:h=300:color=black@0.7:t=fill,'
        'drawbox=x=0:y=295:w=iw:h=8:color=0xff0000@0.9:t=fill,'
        f"drawtext=fontfile={FONT}:text='FINANCE NEWS':fontcolor=0xff4444:fontsize=36:x=(w-text_w)/2:y=30:box=0,"
        f"drawtext=fontfile={FONT}:text='{line1}':fontcolor=white:fontsize=56:x=(w-text_w)/2:y=100:box=0,"
    )
    if line2:
        vf += (f"drawtext=fontfile={FONT}:text='{line2}':fontcolor=white:fontsize=56:x=(w-text_w)/2:y=165:box=0,",)
    vf += (
        f"drawtext=fontfile={FONT}:text='Follow for Daily Finance News!':fontcolor=0xffdd00:fontsize=36:x=(w-text_w)/2:y=1650:box=0,"
        'drawbox=x=0:y=1910:w=iw:h=10:color=white@0.3:t=fill'
    )

    fade_out_start = max(0, duration - 0.5)
    cmd = [
        'ffmpeg', '-y',
        '-stream_loop', '-1', '-i', video_path,
        '-i', audio_path,
        '-map', '0:v:0', '-map', '1:a:0',
        '-vf', ''.join(vf),
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-pix_fmt', 'yuv420p',
        '-r', '30',
        '-movflags', '+faststart',
        '-af', f'loudnorm=I=-16:LRA=11:TP=-1.5,afade=t=in:st=0:d=0.3,afade=t=out:st={fade_out_start:.2f}:d=0.5',
        '-c:a', 'aac', '-b:a', '128k',
        '-t', str(duration),
        output_path
    ]
    subprocess.run(cmd, check=True)

    # Clean up temp concat if it was created
    if tmp_concat and os.path.exists(tmp_concat):
        try: os.remove(tmp_concat)
        except: pass

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 9. PLAYLIST MANAGEMENT ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
_playlist_cache = {}

def get_or_create_playlist(youtube, title, description=''):
    try:
        resp = youtube.playlists().list(part='snippet', mine=True, maxResults=50).execute()
        for pl in resp.get('items', []):
            if pl['snippet']['title'].lower() == title.lower():
                return pl['id']
    except Exception as e:
        print(f'Playlist search error: {e}')
    try:
        pl = youtube.playlists().insert(
            part='snippet,status',
            body={'snippet': {'title': title, 'description': description},
                  'status': {'privacyStatus': 'public'}}
        ).execute()
        print(f'Created playlist: {title}')
        return pl['id']
    except Exception as e:
        print(f'Playlist create error: {e}')
        return None

def add_to_playlist(youtube, playlist_id, video_id):
    if not playlist_id:
        return
    try:
        youtube.playlistItems().insert(
            part='snippet',
            body={'snippet': {
                'playlistId': playlist_id,
                'resourceId': {'kind': 'youtube#video', 'videoId': video_id}
            }}
        ).execute()
        print('Added to playlist!')
    except Exception as e:
        print(f'Playlist add error: {e}')

def get_playlist_for_topic(youtube, tags):
    tl = [t.lower() for t in (tags or [])]
    if any(t in tl for t in ['crypto', 'bitcoin', 'ethereum', 'blockchain', 'defi']):
        name = 'Crypto News Shorts'
    elif any(t in tl for t in ['tech', 'ai', 'apple', 'google', 'microsoft']):
        name = 'Tech Market Shorts'
    elif any(t in tl for t in ['gold', 'oil', 'commodities']):
        name = 'Commodities & Markets'
    elif any(t in tl for t in ['earnings', 'nasdaq', 'sp500', 'dow']):
        name = 'Stock Market Shorts'
    else:
        name = 'Daily Finance News'
    if name not in _playlist_cache:
        _playlist_cache[name] = get_or_create_playlist(
            youtube, name, f'Daily {name} ÃÂ¢ÃÂÃÂ updated every morning & evening!')
    return _playlist_cache[name]

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 10. PINNED COMMENT ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def post_pinned_comment(youtube, video_id):
    try:
        comment_text = (
            "ÃÂ°ÃÂÃÂÃÂ What do you think about today's market?\n"
            "Drop a ÃÂ°ÃÂÃÂÃÂ if you're BULLISH or ÃÂ°ÃÂÃÂÃÂ if you're BEARISH!\n"
            "Follow for daily finance updates ÃÂ¢ÃÂÃÂ every morning & evening!"
        )
        resp = youtube.commentThreads().insert(
            part='snippet',
            body={'snippet': {
                'videoId': video_id,
                'topLevelComment': {'snippet': {'textOriginal': comment_text}}
            }}
        ).execute()
        print('Pinned comment posted!')
    except Exception as e:
        print(f'Comment error: {e}')

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 11. AUTO SAVE REFRESH TOKEN ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def save_refresh_token_to_github(new_token):
    tok = os.environ.get('GITHUB_TOKEN')
    repo = os.environ.get('GITHUB_REPO')
    if not tok or not repo:
        return
    try:
        kd = requests.get(
            f'https://api.github.com/repos/{repo}/actions/secrets/public-key',
            headers={'Authorization': f'token {tok}', 'Accept': 'application/vnd.github.v3+json'}
        ).json()
        from nacl import encoding, public
        pub = public.PublicKey(kd['key'].encode(), encoding.Base64Encoder())
        enc = base64.b64encode(public.SealedBox(pub).encrypt(new_token.encode())).decode()
        requests.put(
            f'https://api.github.com/repos/{repo}/actions/secrets/YOUTUBE_REFRESH_TOKEN',
            headers={'Authorization': f'token {tok}', 'Accept': 'application/vnd.github.v3+json'},
            json={'encrypted_value': enc, 'key_id': kd['key_id']}
        )
        print('New refresh token saved to GitHub Secrets!')
    except Exception as e:
        print(f'Token save error: {e}')

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 12. GET YOUTUBE SERVICE ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def get_youtube_service():
    creds = Credentials(
        token=None, refresh_token=YOUTUBE_REFRESH_TOKEN,
        client_id=YOUTUBE_CLIENT_ID, client_secret=YOUTUBE_CLIENT_SECRET,
        token_uri='https://oauth2.googleapis.com/token'
    )
    try:
        creds.refresh(Request())
        if creds.refresh_token and creds.refresh_token != YOUTUBE_REFRESH_TOKEN:
            print('New token received, saving...')
            save_refresh_token_to_github(creds.refresh_token)
    except Exception as e:
        print(f'Token refresh: {e}')
    return build('youtube', 'v3', credentials=creds)

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 13. UPLOAD TO YOUTUBE ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
def upload_to_youtube(youtube, video_path, title, tags, thumbnail_path=None):
    title = title[:100]
    pub_date = datetime.utcnow().strftime('%B %d, %Y')

    # Dedup tags
    seen = set()
    tags = [t for t in tags if not (t.lower() in seen or seen.add(t.lower()))]
    tags = tags[:30]

    description = (
        f"{title}\n\n"
        f"Published: {pub_date}\n\n"
        "Stay ahead of the markets! We break down the biggest finance stories "
        "every day in 60 seconds ÃÂ¢ÃÂÃÂ fast, clear, straight to the point.\n\n"
        "New videos every morning & evening ÃÂ¢ÃÂÃÂ subscribe now!\n\n"
        "#Shorts #Finance #Money #Investing #StockMarket #FinanceNews "
        "#WallStreet #Trading #DayTrading #FinancialNews #WealthBuilding "
        "#PassiveIncome #PersonalFinance #StockTips #MarketNews"
    )
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags + ['shorts', 'finance', 'money', 'investing', 'stockmarket', 'trading'],
            'categoryId': '25',
            'defaultLanguage': 'en',
            'defaultAudioLanguage': 'en',
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
    try:
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f'  Upload {int(status.progress() * 100)}%')
    except Exception as upload_err:
        msg = str(upload_err)
        if 'quota' in msg.lower() or 'forbidden' in msg.lower() or '403' in msg:
            raise Exception('YouTube daily quota exceeded! Bot resumes automatically tomorrow.')
        raise

    video_id = response['id']
    print(f'Uploaded: https://youtube.com/shorts/{video_id}')

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype='image/jpeg')
            ).execute()
            print('Thumbnail set!')
        except Exception as e:
            print(f'Thumbnail skip: {e}')

    return video_id

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ 14. MAIN ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
async def main():
    print('Starting YouTube Finance Shorts Bot...')

    seen_titles = load_seen_titles()
    print(f'Loaded {len(seen_titles)} seen titles')

    articles = fetch_news(seen_titles)
    if not articles:
        print('No fresh articles ÃÂ¢ÃÂÃÂ resetting seen cache.')
        save_seen_titles(set())
        return

    print('Generating scripts with Groq...')
    scripts = generate_scripts(articles)
    if not scripts:
        print('No scripts generated ÃÂ¢ÃÂÃÂ aborting.')
        return
    print(f'Generated {len(scripts)} scripts')

    youtube = get_youtube_service()
    success = 0
    used = set()

    for i, item in enumerate(scripts):
        print(f'\n--- Video {i+1}/{len(scripts)}: {item["title"]} ---')
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                audio_path     = os.path.join(tmpdir, 'audio.mp3')
                video_raw      = os.path.join(tmpdir, 'raw.mp4')
                video_out      = os.path.join(tmpdir, 'output.mp4')
                thumbnail_path = os.path.join(tmpdir, 'thumb.jpg')

                # Clean + trim script
                item['script'] = clean_script_for_tts(item['script'])
                words = item['script'].split()
                if len(words) > 150:
                    item['script'] = ' '.join(words[:150])
                    print('  Script trimmed to 150 words')

                print('  Generating audio...')
                await generate_audio(item['script'], audio_path)

                if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
                    raise Exception(f'Audio invalid: {os.path.getsize(audio_path) if os.path.exists(audio_path) else "missing"}')

                print('  Downloading Pexels video...')
                video_clips = download_pexels_multi(
                    item.get('search_query', random.choice(PEXELS_QUERIES)), tmpdir, count=3)

                print('  Rendering video...')
                create_shorts_video(video_clips, audio_path, video_out,
                                    title=item['title'], emoji=item.get('emoji', 'ÃÂ°ÃÂÃÂÃÂ'))

                if not os.path.exists(video_out) or os.path.getsize(video_out) < 10000:
                    raise Exception(f'Video invalid: {os.path.getsize(video_out) if os.path.exists(video_out) else "missing"}')

                print('  Creating thumbnail...')
                thumb = create_thumbnail(video_out, item['title'],
                                         item.get('emoji', 'ÃÂ°ÃÂÃÂÃÂ'), thumbnail_path)

                print('  Uploading to YouTube...')
                vid_id = upload_to_youtube(youtube, video_out, item['title'],
                                           item['tags'], thumb)

                print('  Adding to playlist...')
                pl_id = get_playlist_for_topic(youtube, item['tags'])
                add_to_playlist(youtube, pl_id, vid_id)

                print('  Posting comment...')
                post_pinned_comment(youtube, vid_id)

                success += 1
                seen_titles.add(title_hash(item['title']))
                used.add(title_hash(item['title']))

        except Exception as e:
            print(f'  ERROR video {i+1}: {type(e).__name__}: {str(e)[:100]} ÃÂ¢ÃÂÃÂ skipping!')
            continue

    if used:
        save_seen_titles(seen_titles)

    failed = len(scripts) - success
    print(f'\nDone! {success}/{len(scripts)} videos uploaded.')
    if failed > 0:
        print(f'  {failed} videos failed ÃÂ¢ÃÂÃÂ check logs above.')

if __name__ == '__main__':
    asyncio.run(main())
