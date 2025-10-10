import requests
import json
import re
from xml.etree import ElementTree
import datetime

def get_lyrics(song_id, storefront, token, media_user_token, lrc_format):

    if not media_user_token or len(media_user_token) < 50:
        raise ValueError("A valid media-user-token is required.")

    ttml = _fetch_ttml(song_id, storefront, token, media_user_token)
    if not ttml:
        raise ValueError("No synced lyrics available from API.")

    if lrc_format == "ttml":
        return ttml
    
    return _ttml_to_lrc(ttml)

def _fetch_ttml(song_id, storefront, token, media_user_token):

    url = f"https://amp-api.music.apple.com/v1/catalog/{storefront}/songs/{song_id}/lyrics"
    headers = {
        "Authorization": f"Bearer {token}",
        "media-user-token": media_user_token,
        "Origin": "https://music.apple.com",
        "Referer": "https://music.apple.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/536"
    }
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    data = response.json()
    if 'data' in data and len(data['data']) > 0 and 'attributes' in data['data'][0]:
        return data['data'][0]['attributes'].get('ttml')
    
    return None

def _ttml_to_lrc(ttml):

    try:
        root = ElementTree.fromstring(ttml)
        body = root.find('{http://www.w3.org/ns/ttml}body')
        div = body.find('{http://www.w3.org/ns/ttml}div')
        
        lines = []
        for p in div.findall('{http://www.w3.org/ns/ttml}p'):
            begin = p.attrib.get('begin')
            text = "".join(p.itertext()).strip()
            if begin and text:
                
                parts = begin.split(':')
                if len(parts) == 3:
                    h, m, s_ms = parts
                    s_parts = s_ms.split('.')
                    s = s_parts[0]
                    ms = s_parts[1][:2] if len(s_parts) > 1 else "00"
                    
                    total_minutes = int(h) * 60 + int(m)
                    lrc_time = f"[{total_minutes:02d}:{int(s):02d}.{ms}]"
                    lines.append(f"{lrc_time}{text}")

        return "\n".join(lines)
    except Exception as e:
       
        try:
            lines = []
            for p in re.finditer(r'<p begin="([^"]+)">([^<]+)</p>', ttml):
                begin, text = p.groups()
                parts = begin.split(':')
                if len(parts) == 3:
                    h, m, s_ms = parts
                    s_parts = s_ms.split('.')
                    s = s_parts[0]
                    ms = s_parts[1][:2] if len(s_parts) > 1 else "00"
                    
                    total_minutes = int(h) * 60 + int(m)
                    lrc_time = f"[{total_minutes:02d}:{int(s):02d}.{ms}]"
                    lines.append(f"{lrc_time}{text.strip()}")
            if lines:
                return "\n".join(lines)
            else:
                raise e 
        except Exception as e:
            raise ValueError(f"Failed to parse TTML: {e}")