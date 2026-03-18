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
import hashlib
import edge_tts

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import moviepy.editor as mp
import whisper_timestamped as whisper

GROQ_API_KEY       = os.environ.get('GROQ_API_KEY')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID')

VIDEOS_PER_RUN = 2 # Telegram'i spamlamamak icin tek calismada 2 video uretir.

RSS_FEEDS = [
    'https://feeds.reuters.com/reuters/businessNews',
    'https://finance.yahoo.com/news/rssindex',
    'https://feeds.bloomberg.com/markets/news.rss',
]

VOICES = [
    ('en-US-GuyNeural',    '+10%', '+0Hz'),
    ('en-US-AndrewNeural', '+8%',  '+0Hz'),
]
_voice_idx = [0]
FONT = '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'

def fetch_news():
    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                articles.append({'title': entry.get('title', ''), 'summary': entry.get('summary', '')[:300]})
        except: pass
    random.shuffle(articles)
    return articles[:20]

def generate_scripts(articles):
    txt = '\n'.join([f"{i+1}. {a['title']}: {a['summary']}" for i, a in enumerate(articles[:10])])
    prompt = f"""You are a viral YouTube Shorts script writer for a finance news channel.
Today's headlines:\n{txt}
Pick the {VIDEOS_PER_RUN} most engaging stories.
Write a YouTube Shorts script (max 150 words).
Rules:
- Hook MUST grab attention in FIRST 2 SECONDS
- Use "YOU", "YOUR money"
- End EXACTLY with: "Follow for daily finance news!"

Return ONLY valid JSON array:
[{{ "title":"emoji+title", "script":"full script", "tags":["finance", "news"] }}]"""

    headers = {'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'}
    try:
        payload = json.dumps({"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}]})
        resp = requests.post('https://api.groq.com/openai/v1/chat/completions', headers=headers, data=payload, timeout=30)
        text = resp.json()['choices'][0]['message']['content'].strip()
        
        # Groq ne yazarsa yazsin sadece JSON kismini zorla cekip alir
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
           return json.loads(match.group(0), strict=False)
        return []
    except Exception as e:
        print("Groq Hatasi:", e)
        return []

def clean_script_for_tts(script):
    script = re.sub(r'[\U00010000-\U0010ffff]', '', script, flags=re.UNICODE)
    script = re.sub(r'http\S+', '', script).replace('#', '')
    return re.sub(r'\s+', ' ', script).strip()

async def generate_audio(script, output_path):
    voice, rate, pitch = VOICES[_voice_idx[0] % len(VOICES)]
    _voice_idx[0] += 1
    communicate = edge_tts.Communicate(script, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(output_path)

def extract_random_background(target_duration, output_path):
    bg_dir = "backgrounds"
    if not os.path.exists(bg_dir) or not any(f.endswith('.mp4') for f in os.listdir(bg_dir)):
        raise Exception("Lutfen GitHub'da 'backgrounds' klasoru acip icine en az 1 tane mp4 video yukle!")
    
    videos = [f for f in os.listdir(bg_dir) if f.endswith('.mp4')]
    chosen_video = os.path.join(bg_dir, random.choice(videos))
    
    # Videonun toplam suresini bul
    res = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", chosen_video], stdout=subprocess.PIPE, text=True)
    try:
        dur = float(res.stdout.strip())
    except ValueError:
        dur = target_duration + 10

    start_time = random.uniform(0, max(0, dur - target_duration))
    
    # FFmpeg ile isik hizinda kes, dikey formata (9:16) kirp ve olcekle
    subprocess.run([
        'ffmpeg', '-y', '-ss', str(start_time), '-i', chosen_video, '-t', str(target_duration),
        '-vf', 'crop=ih*(9/16):ih,scale=1080:1920', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-an', output_path
    ], check=True, capture_output=True)

def create_text_image(text, font_path, font_size, max_width):
    image = Image.new("RGBA", (max_width, int(font_size * 2.5)), (0, 0, 0, 0))
    try: font = ImageFont.truetype(font_path, font_size)
    except: font = ImageFont.load_default()
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw.text(((max_width - text_w) / 2, (font_size * 2.5 - text_h) / 2), text, font=font, fill="yellow", stroke_width=6, stroke_fill="black")
    return np.array(image)

def create_shorts_video(video_path, audio_path, output_path, title):
    loaded_audio = whisper.load_audio(audio_path)
    model = whisper.load_model("tiny.en", device="cpu")
    result = whisper.transcribe(model, loaded_audio, language="en")
    
    audio_clip = mp.AudioFileClip(audio_path)
    bg_clip = mp.VideoFileClip(video_path).subclip(0, audio_clip.duration).set_audio(audio_clip)

    text_clips = []
    safe_title = title.replace("'", "").replace('"', '')[:35].upper()
    title_clip = mp.ImageClip(create_text_image(f"FINANCE NEWS\n{safe_title}", FONT, 60, 1080)).set_duration(audio_clip.duration).set_position(('center', 150))
    text_clips.append(title_clip)

    for segment in result['segments']:
        for word in segment['words']:
            start, end = word['start'], max(word['end'], word['start'] + 0.2)
            txt_clip = mp.ImageClip(create_text_image(word['text'].strip().upper(), FONT, 90, 1080)).set_start(start).set_end(end).set_position(('center', 'center'))
            text_clips.append(txt_clip)

    final_clip = mp.CompositeVideoClip([bg_clip] + text_clips)
    final_clip.write_videofile(output_path, fps=30, codec="libx264", audio_codec="aac", preset="fast", threads=4, logger=None)
    
    bg_clip.close()
    audio_clip.close()
    final_clip.close()

def send_to_telegram(video_path, title, tags):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    tag_str = " ".join([f"#{t.replace(' ', '')}" for t in tags])
    caption = f"🎬 <b>YENI VIDEO HAZIR PATRON!</b>\n\n<b>Baslik:</b> {title}\n\n<b>Aciklama:</b>\n{title}\n\nSubscribe to @FinanceFlashDaily for daily finance news! {tag_str} #Shorts #Finance\n\n<i>Videoyu indirip YouTube'a trend muzik ekleyerek yukleyebilirsin!</i>"
    
    with open(video_path, 'rb') as video:
        response = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}, files={'video': video})
        if response.status_code != 200:
            print(f"Telegram Gonderme Hatasi: {response.text}")

async def main():
    print('Starting Telegram Finance Shorts Bot...')
    articles = fetch_news()
    scripts = generate_scripts(articles)

    for i, item in enumerate(scripts):
        print(f'\n--- Video {i+1}/{len(scripts)} ---')
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                audio_path = os.path.join(tmpdir, 'audio.mp3')
                video_raw = os.path.join(tmpdir, 'raw.mp4')
                video_out = os.path.join(tmpdir, 'output.mp4')

                print('  1. Ses Olusturuluyor...')
                await generate_audio(clean_script_for_tts(item.get('script', '')), audio_path)

                print('  2. Arka Plan Videosu Kesiliyor (FFMPEG Isik Hizi)...')
                temp_audio = mp.AudioFileClip(audio_path)
                audio_len = temp_audio.duration
                temp_audio.close()
                extract_random_background(audio_len + 1, video_raw)
                
                print('  3. Altyazilar Ekleniyor...')
                create_shorts_video(video_raw, audio_path, video_out, item.get('title', 'News'))

                print('  4. Telegram Kuryesi Yola Cikti...')
                send_to_telegram(video_out, item.get('title', 'News'), item.get('tags', ['finance']))

        except Exception as e:
            print(f'  HATA: {e}')

if __name__ == '__main__':
    asyncio.run(main())
