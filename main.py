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
import edge_tts
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import moviepy.editor as mp
import whisper_timestamped as whisper

# Ortam Değişkenleri
GROQ_API_KEY       = os.environ.get('GROQ_API_KEY', '').strip()
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

# Konfigürasyon
VIDEOS_PER_RUN = 2 
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
    """Haber sitelerinden güncel finans verilerini toplar."""
    print("-> Haberler toplanıyor...")
    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                articles.append({
                    'title': entry.get('title', ''), 
                    'summary': entry.get('summary', '')[:300]
                })
        except Exception as e:
            print(f"   ! RSS Hatası ({url}): {e}")
    
    random.shuffle(articles)
    return articles[:20]

def generate_scripts(articles):
    """Groq AI kullanarak viral senaryolar, açıklamalar ve hashtagler üretir."""
    if not articles:
        return []
    
    print("-> Groq AI senaryo ve içerik hazırlıyor...")
    txt = '\n'.join([f"{i+1}. {a['title']}: {a['summary']}" for i, a in enumerate(articles[:10])])
    prompt = f"""You are a viral YouTube Shorts script writer for a finance news channel.
Today's headlines:\n{txt}
Pick the {VIDEOS_PER_RUN} most engaging stories.
Rules:
- Hook MUST grab attention in FIRST 2 SECONDS.
- Use viral psychology: "You need to hear this," "Your money is at stake."
- End EXACTLY with: "Follow for daily finance news!"
- Generate a "description" for the video caption that is viral.
- Generate a list of 5-8 relevant trending "tags".

Return ONLY valid JSON array:
[{{ "title":"emoji+short title", "script":"full script", "description": "viral description", "tags":["tag1", "tag2"] }}]"""

    headers = {'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'}
    try:
        payload = {
            "model": "llama-3.1-8b-instant", 
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
        resp = requests.post('https://api.groq.com/openai/v1/chat/completions', headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        
        content = resp.json()['choices'][0]['message']['content'].strip()
        
        # Gelişmiş JSON Ayıklama ve Tamir
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            clean_json = match.group(0)
            # AI bazen objeler arasına virgül koymayı unutur, zorla düzeltelim
            clean_json = re.sub(r'\}\s*\{', '}, {', clean_json)
            # Sonda kalan hatalı virgülleri temizleyelim
            clean_json = re.sub(r',\s*\]', ']', clean_json)
            # Görünmez kontrol karakterlerini temizleyelim
            clean_json = re.sub(r'[\x00-\x1F\x7F]', '', clean_json)
            
            try:
                return json.loads(clean_json, strict=False)
            except json.JSONDecodeError:
                # Son çare: Regex ile objeleri tek tek çekmeyi dene
                objects = re.findall(r'\{.*?\}', clean_json, re.DOTALL)
                results = []
                for obj_str in objects:
                    try:
                        results.append(json.loads(obj_str, strict=False))
                    except: continue
                return results
        return []
    except Exception as e:
        print(f"   ! Groq Hatası: {e}")
        return []

def clean_script_for_tts(script):
    """Metni seslendirme motoru için temizler."""
    script = re.sub(r'[\U00010000-\U0010ffff]', '', script, flags=re.UNICODE)
    script = re.sub(r'http\S+', '', script).replace('#', '')
    return re.sub(r'\s+', ' ', script).strip()

async def generate_audio(script, output_path):
    """MP3 ses dosyası üretir."""
    voice, rate, pitch = VOICES[_voice_idx[0] % len(VOICES)]
    _voice_idx[0] += 1
    communicate = edge_tts.Communicate(script, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(output_path)

def extract_random_background(target_duration, output_path):
    """Arka plan videosunu keser, dikey yapar ve SİYAH EKRAN OLMAMASI İÇİN DÖNGÜYE SOKAR."""
    bg_dir = "backgrounds"
    if not os.path.exists(bg_dir):
        raise Exception(f"HATA: '{bg_dir}' klasörü bulunamadı!")
    
    videos = [f for f in os.listdir(bg_dir) if f.endswith('.mp4')]
    if not videos:
        raise Exception("HATA: backgrounds klasöründe video yok!")
    
    chosen_video = os.path.join(bg_dir, random.choice(videos))
    
    res = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", 
        "-of", "default=noprint_wrappers=1:nokey=1", chosen_video
    ], stdout=subprocess.PIPE, text=True)
    
    try:
        total_dur = float(res.stdout.strip())
        # Videonun herhangi bir yerinden başlayabiliriz
        start_time = random.uniform(0, max(0, total_dur - 1))
    except:
        start_time = 0

    print(f"   - Video işleniyor (Döngü Modu): {os.path.basename(chosen_video)}...")
    
    # -stream_loop -1 komutu videonun sonsuz döngüye girmesini sağlar.
    # Böylece video kısa olsa bile ses bitene kadar başa sarıp devam eder.
    subprocess.run([
        'ffmpeg', '-y', 
        '-ss', str(start_time), 
        '-stream_loop', '-1', 
        '-i', chosen_video, 
        '-t', str(target_duration),
        '-vf', 'crop=ih*(9/16):ih,scale=1080:1920,eq=brightness=-0.15:contrast=1.2', 
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
        '-threads', '4', '-an', output_path
    ], check=True, capture_output=True)

def create_text_image(text, font_path, font_size, max_width, color="yellow"):
    """Sarı yazı, kalın siyah stroke ve çok satırlı metin desteği."""
    image = Image.new("RGBA", (max_width, int(font_size * 5)), (0, 0, 0, 0))
    try: font = ImageFont.truetype(font_path, font_size)
    except: font = ImageFont.load_default()
    
    draw = ImageDraw.Draw(image)
    bbox = draw.multiline_textbbox((0, 0), text, font=font, align="center")
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    y_pos = (image.height - th) / 2
    
    draw.multiline_text(((max_width - tw) / 2, y_pos), 
              text, font=font, fill=color, stroke_width=8, stroke_fill="black", align="center")
    return np.array(image)

def create_shorts_video(video_path, audio_path, output_path, title):
    """Sesi, videoyu ve dinamik altyazıları birleştirir."""
    print("   - Altyazı zamanlamaları çıkartılıyor...")
    loaded_audio = whisper.load_audio(audio_path)
    model = whisper.load_model("tiny.en", device="cpu")
    result = whisper.transcribe(model, loaded_audio, language="en")
    
    audio_clip = mp.AudioFileClip(audio_path)
    bg_clip = mp.VideoFileClip(video_path).set_audio(audio_clip)

    text_clips = []
    # Üst başlık (Kesilmemesi için 260px aşağıda)
    safe_title = title.replace("'", "").replace('"', '')[:35].upper()
    title_img = create_text_image(f"FINANCE NEWS\n{safe_title}", FONT, 48, 1080, color="#FFD700")
    title_clip = mp.ImageClip(title_img).set_duration(audio_clip.duration).set_position(('center', 260))
    text_clips.append(title_clip)

    # Dinamik kelime altyazıları (Tam merkezde)
    for segment in result['segments']:
        for word in segment['words']:
            start, end = word['start'], max(word['end'], word['start'] + 0.12)
            word_img = create_text_image(word['text'].strip().upper(), FONT, 85, 1080, color="white")
            txt_clip = mp.ImageClip(word_img).set_start(start).set_end(end).set_position(('center', 'center'))
            text_clips.append(txt_clip)

    print("   - Final render (Yüksek Kalite)...")
    final_clip = mp.CompositeVideoClip([bg_clip] + text_clips)
    final_clip.write_videofile(output_path, fps=30, codec="libx264", audio_codec="aac", preset="medium", threads=4, logger=None)
    
    bg_clip.close(); audio_clip.close(); final_clip.close()

def send_to_telegram(video_path, title, description, tags):
    """Videoyu ve AI tarafından üretilen içerikleri Telegram'a gönderir."""
    token = TELEGRAM_BOT_TOKEN
    if token.lower().startswith("bot"):
        token = token[3:]
    
    url = f"https://api.telegram.org/bot{token}/sendVideo"
    tag_str = " ".join([f"#{t.strip().replace(' ', '')}" for t in tags])
    if "#Finance" not in tag_str: tag_str += " #Finance"
    
    caption = (f"🎬 <b>{title}</b>\n\n"
               f"{description}\n\n"
               f"Follow: @FinanceFlashDaily\n\n"
               f"{tag_str} #Shorts")
    
    try:
        with open(video_path, 'rb') as v_file:
            payload = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}
            files = {'video': v_file}
            r = requests.post(url, data=payload, files=files, timeout=120)
            if r.status_code == 200:
                print("   [BAŞARILI] Video ve içerik Telegram'a ulaştı!")
            else:
                print(f"   [HATA] Telegram: {r.text}")
    except Exception as e:
        print(f"   [HATA] Telegram yükleme hatası: {e}")

async def main():
    print("=== TELEGRAM FINANCE BOT [BATTLE READY] BAŞLATILDI ===")
    
    if not all([GROQ_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        print("KRİTİK HATA: Ortam değişkenleri eksik!")
        return

    articles = fetch_news()
    if not articles:
        return

    scripts = generate_scripts(articles)
    if not scripts:
        return

    for i, item in enumerate(scripts):
        print(f"\n--- İŞLENİYOR: Video {i+1}/{len(scripts)} ---")
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                audio_path = os.path.join(tmpdir, 'a.mp3')
                video_raw  = os.path.join(tmpdir, 'r.mp4')
                video_out  = os.path.join(tmpdir, 'f.mp4')

                print("  1. Ses dosyası üretiliyor...")
                await generate_audio(clean_script_for_tts(item.get('script', '')), audio_path)
                
                # Ses süresi tespiti
                audio_clip_temp = mp.AudioFileClip(audio_path)
                a_dur = audio_clip_temp.duration
                audio_clip_temp.close()
                
                print("  2. Arka plan hazırlanıyor...")
                extract_random_background(a_dur + 0.5, video_raw)
                
                print("  3. Montaj yapılıyor...")
                create_shorts_video(video_raw, audio_path, video_out, item.get('title', 'NEWS'))
                
                print("  4. Telegrama gönderiliyor...")
                send_to_telegram(
                    video_out, 
                    item.get('title', item.get('title', 'Finance News')), 
                    item.get('description', "Don't miss out on the latest finance developments."),
                    item.get('tags', ['finance', 'news'])
                )

        except Exception as e:
            print(f"   !!! VIDEO {i+1} HATASI: {e}")

    print("\n=== TÜM İŞLEMLER BİTTİ ===")

if __name__ == '__main__':
    asyncio.run(main())
