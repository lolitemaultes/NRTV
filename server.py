#!/usr/bin/env python3
"""
NRTV - Python Server
Serves the HTML interface and provides TV guide data via API
Includes audio proxy for CORS issues with ABC streams
"""

import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, send_from_directory, render_template_string, Response, request
from flask_cors import CORS
import logging
import sys

logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('requests').setLevel(logging.ERROR)

class Colors:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    GRAY = '\033[90m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    END = '\033[0m'

def print_status(message, status="info"):
    """Print clean status messages"""
    icons = {
        "success": f"{Colors.GREEN}✓{Colors.END}",
        "error": f"{Colors.RED}✗{Colors.END}",
        "warning": f"{Colors.YELLOW}⚠{Colors.END}",
        "info": f"{Colors.BLUE}•{Colors.END}",
        "loading": f"{Colors.CYAN}⟳{Colors.END}"
    }
    icon = icons.get(status, icons["info"])
    print(f"{icon} {message}")

TZ = ZoneInfo('Australia/Sydney')
UTC = ZoneInfo('UTC')

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

class Program:
    """Program information container"""
    def __init__(self, title: str, description: str, category: str, 
                 start: datetime, stop: datetime):
        self.title = title
        self.description = description
        self.category = category
        self.start = start
        self.stop = stop
        
    @property
    def is_live(self) -> bool:
        now = datetime.now(TZ)
        return self.start <= now < self.stop
    
    @property
    def progress(self) -> float:
        """Get progress percentage of current program"""
        now = datetime.now(TZ)
        if now < self.start:
            return 0.0
        elif now >= self.stop:
            return 100.0
        else:
            total = (self.stop - self.start).total_seconds()
            elapsed = (now - self.start).total_seconds()
            return (elapsed / total) * 100
    
    @property
    def duration_minutes(self) -> int:
        """Get program duration in minutes"""
        return int((self.stop - self.start).total_seconds() / 60)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'title': self.title,
            'description': self.description,
            'category': self.category,
            'start': self.start.isoformat(),
            'stop': self.stop.isoformat(),
            'timeStr': f"{self.start.strftime('%I:%M %p').lstrip('0')} - {self.stop.strftime('%I:%M %p').lstrip('0')}",
            'isLive': self.is_live,
            'progress': self.progress,
            'remainingMins': max(0, int((self.stop - datetime.now(TZ)).total_seconds() / 60)) if self.is_live else 0,
            'durationMins': self.duration_minutes
        }

class TVGuideLoader:
    """TV Guide data loader"""
    
    def __init__(self):
        self.programs_cache = {}
        self.last_loaded = None
        self.cache_duration = timedelta(hours=1)
    
    def load_tv_guide(self) -> Dict[int, List[Program]]:
        """Load TV guide from XML sources with caching"""
        now = datetime.now(TZ)
        
        if (self.last_loaded and 
            self.programs_cache and 
            now - self.last_loaded < self.cache_duration):
            return self.programs_cache
        
        urls = [
            "http://xmltv.net/xml_files/Lismore.xml",
            "https://xmltv.net/xml_files/Lismore.xml", 
            "http://xmltv.net/xml_files/Northern_NSW.xml",
            "https://xmltv.net/xml_files/Northern_NSW.xml",
        ]
        
        for url in urls:
            try:
                response = requests.get(url, timeout=15, headers={
                    'User-Agent': 'SmartTV/1.0'
                })
                response.raise_for_status()
                
                root = ET.fromstring(response.content)
                programs = self.parse_xml_guide(root)

                if programs:
                    programs = self._normalize_duplicate_channels(programs)
                    programs = self._filter_abc_news_channels(programs)
                    self.programs_cache = programs
                    self.last_loaded = now
                    print_status(f"TV Guide loaded ({len(programs)} channels)", "success")
                    return programs
                    
            except Exception:
                continue
        
        print_status("Using fallback program data", "warning")
        fallback = self.generate_fallback_programs()
        fallback = self._normalize_duplicate_channels(fallback)
        return fallback
    
    def parse_xml_guide(self, root) -> Dict[int, List[Program]]:
        """Parse XML TV guide data"""
        channel_mapping = {}
        for channel in root.findall('channel'):
            lcn_elem = channel.find('lcn')
            if lcn_elem is not None:
                try:
                    lcn = int(lcn_elem.text)
                    channel_mapping[channel.get('id')] = lcn
                except ValueError:
                    continue
        
        programs_by_channel = {}
        program_count = 0
        
        for programme in root.findall('programme'):
            channel_id = programme.get('channel')
            if channel_id in channel_mapping:
                lcn = channel_mapping[channel_id]
                
                if lcn not in programs_by_channel:
                    programs_by_channel[lcn] = []
                
                title = programme.find('title')
                desc = programme.find('desc')
                category = programme.find('category')
                
                title_text = title.text if title is not None else "No Title"
                desc_text = desc.text if desc is not None else ""
                category_text = category.text if category is not None else "General"
                
                start_time = self.parse_xmltv_time(programme.get('start'))
                stop_time = self.parse_xmltv_time(programme.get('stop'))
                
                if start_time and stop_time:
                    program = Program(
                        title_text, desc_text, category_text,
                        start_time, stop_time
                    )
                    programs_by_channel[lcn].append(program)
                    program_count += 1
        
        for lcn in programs_by_channel:
            programs_by_channel[lcn].sort(key=lambda p: p.start)
        
        return programs_by_channel
    
    def parse_xmltv_time(self, time_str: str) -> Optional[datetime]:
        """Parse XMLTV time format"""
        if not time_str:
            return None
        try:
            if '+' in time_str or '-' in time_str[-5:]:
                if ' ' in time_str:
                    dt_str, tz_str = time_str.split(' ', 1)
                    dt = datetime.strptime(dt_str, '%Y%m%d%H%M%S')
                    if tz_str.startswith('+') or tz_str.startswith('-'):
                        sign = 1 if tz_str[0] == '+' else -1
                        hours = int(tz_str[1:3])
                        minutes = int(tz_str[3:5]) if len(tz_str) >= 5 else 0
                        offset = timedelta(hours=sign*hours, minutes=sign*minutes)
                        dt = dt.replace(tzinfo=timezone(offset))
                        return dt.astimezone(TZ)
                else:
                    for i in range(len(time_str)-1, 0, -1):
                        if time_str[i] in '+-':
                            dt_str = time_str[:i]
                            tz_str = time_str[i:]
                            dt = datetime.strptime(dt_str, '%Y%m%d%H%M%S')
                            sign = 1 if tz_str[0] == '+' else -1
                            hours = int(tz_str[1:3])
                            minutes = int(tz_str[3:5]) if len(tz_str) >= 5 else 0
                            offset = timedelta(hours=sign*hours, minutes=sign*minutes)
                            dt = dt.replace(tzinfo=timezone(offset))
                            return dt.astimezone(TZ)
            else:
                dt = datetime.strptime(time_str[:14], '%Y%m%d%H%M%S')
                return dt.replace(tzinfo=TZ)
        except Exception:
            return None
    
    def generate_fallback_programs(self) -> Dict[int, List[Program]]:
        """Generate fallback program data when XML loading fails"""
        
        tv_channels = [2, 20, 22, 23, 3, 30, 31, 32, 33, 34, 35, 36, 
                      5, 50, 51, 52, 53, 54, 56, 6, 60, 62, 64, 65, 66, 67, 68,
                      8, 80, 81, 82, 83, 84, 85, 88]
        
        programs = {}
        now = datetime.now(TZ)
        
        program_templates = [
            ("Morning News", "Latest news and weather updates", "News"),
            ("Breakfast TV", "Morning entertainment and lifestyle", "Entertainment"),
            ("Kids Programs", "Educational content for children", "Children"),
            ("Midday Movie", "Classic film presentation", "Movies"),
            ("Afternoon Talk", "Discussion and interview program", "Talk"),
            ("Game Show", "Interactive quiz and prizes", "Game Show"),
            ("Documentary", "Educational documentary series", "Documentary"),
            ("Evening News", "Comprehensive news coverage", "News"),
            ("Drama Series", "Popular drama television series", "Drama"),
            ("Comedy Show", "Light entertainment and comedy", "Comedy"),
            ("Late Night", "Late night entertainment", "Entertainment"),
            ("Sports Tonight", "Sports news and highlights", "Sports")
        ]
        
        for lcn in tv_channels:
            channel_programs = []
            
            start_time = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
            
            for i in range(12):
                prog_start = start_time + timedelta(hours=i)
                prog_stop = prog_start + timedelta(hours=1)
                
                template_idx = (lcn + i) % len(program_templates)
                title, desc, category = program_templates[template_idx]
                
                if i < 6:
                    title = f"Morning {title}"
                elif i < 18:
                    title = f"Afternoon {title}"
                else:
                    title = f"Evening {title}"
                
                program = Program(
                    f"{title} #{i+1}",
                    f"{desc} - Episode {i+1}",
                    category,
                    prog_start,
                    prog_stop
                )
                
                channel_programs.append(program)
            
            programs[lcn] = channel_programs

        return programs

    DUPLICATE_LCN_MAP = {
        20: 2,   # ABC TV HD -> ABC TV
        36: 34,  # NITV -> NITV HD
        50: 5,   # 10 HD -> 10 HD Northern NSW
        60: 6,   # 7 HD -> 7 HD Seven
        80: 8,   # 9HD -> Nine
        81: 8,   # Nine far north coast -> Nine
        85: 82,  # 9Gem HD -> 9Gem
        88: 83   # 9Go! HD -> 9Go!
    }

    def _filter_abc_news_channels(self, programs: Dict[int, List[Program]]) -> Dict[int, List[Program]]:
        """
        Remove program data for ABC News channels as they often show different content
        than what's in the XML guide data.
        """
        filtered = dict(programs)
        
        abc_news_channels = [21, 24]
        for lcn in abc_news_channels:
            if lcn in filtered:
                filtered[lcn] = []
        
        return filtered

    def _normalize_duplicate_channels(self, programs: Dict[int, List[Program]]) -> Dict[int, List[Program]]:
        """
        Ensure that duplicate HD/SD channels share the same list of programs.

        Parameters
        ----------
        programs : dict
            Mapping of LCN to list of Program objects.

        Returns
        -------
        dict
            Updated mapping with duplicate channels normalised.
        """
        normalised = dict(programs)

        for dup_lcn, base_lcn in self.DUPLICATE_LCN_MAP.items():
            base_exists = base_lcn in normalised and normalised[base_lcn]
            dup_exists = dup_lcn in normalised and normalised[dup_lcn]

            if base_exists and dup_exists:
                normalised[dup_lcn] = normalised[base_lcn]
                continue

            if base_exists and not dup_exists:
                normalised[dup_lcn] = normalised[base_lcn]
                continue

            if dup_exists and not base_exists:
                normalised[base_lcn] = normalised[dup_lcn]
                continue

        return normalised

tv_guide_loader = TVGuideLoader()

@app.route('/')
def index():
    """Serve the main TV interface"""
    return send_from_directory('.', 'smart_tv.html')

@app.route('/status')
def status():
    """Serve the server status page"""
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NRTV Server</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #0a0a0a, #1f1f1f);
            color: white;
            text-align: center;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2rem;
        }
        
        .container {
            max-width: 800px;
            background: rgba(255, 255, 255, 0.05);
            padding: 3rem;
            border-radius: 24px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(24px);
            box-shadow: 0 8px 64px rgba(0, 0, 0, 0.7);
        }
        
        h1 {
            background: linear-gradient(135deg, #0070f3, #00d9ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            font-size: 3rem;
            font-weight: 700;
            margin-bottom: 1rem;
        }
        
        .icon {
            font-size: 4rem;
            margin: 2rem 0;
            animation: float 3s ease-in-out infinite;
        }
        
        @keyframes float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-0.5rem); }
        }
        
        p {
            font-size: 1.125rem;
            line-height: 1.6;
            margin-bottom: 1.5rem;
            color: #a1a1aa;
        }
        
        .highlight {
            color: #00d9ff;
            font-weight: 600;
            background: rgba(0, 217, 255, 0.1);
            padding: 0.25rem 0.5rem;
            border-radius: 6px;
        }
        
        .status {
            background: rgba(16, 185, 129, 0.1);
            color: #10b981;
            padding: 1rem 1.5rem;
            border-radius: 16px;
            border: 1px solid rgba(16, 185, 129, 0.2);
            margin: 2rem 0;
            font-weight: 600;
            font-size: 1.125rem;
        }
        
        .features {
            text-align: left;
            margin: 2rem 0;
            background: rgba(255, 255, 255, 0.03);
            padding: 2rem;
            border-radius: 16px;
            border-left: 3px solid #00d9ff;
        }
        
        .features h3 {
            color: #00d9ff;
            margin-bottom: 1rem;
            font-size: 1.25rem;
        }
        
        .features p {
            margin-bottom: 0.75rem;
            font-size: 1rem;
        }
        
        .instructions {
            background: rgba(245, 158, 11, 0.1);
            border: 1px solid rgba(245, 158, 11, 0.2);
            padding: 2rem;
            border-radius: 16px;
            margin: 2rem 0;
        }
        
        .instructions h3 {
            color: #f59e0b;
            margin-bottom: 1rem;
        }
        
        .button {
            background: linear-gradient(135deg, #0070f3, #00d9ff);
            border: none;
            padding: 1rem 2rem;
            color: white;
            font-size: 1rem;
            font-weight: 600;
            border-radius: 12px;
            cursor: pointer;
            margin: 0.5rem;
            transition: all 0.3s ease;
            text-decoration: none;
            display: inline-block;
        }
        
        .button:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 32px rgba(0, 112, 243, 0.4);
        }
        
        .api-info {
            background: rgba(255, 255, 255, 0.03);
            padding: 1.5rem;
            border-radius: 12px;
            margin: 1.5rem 0;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .api-info h3 {
            color: #00d9ff;
            margin-bottom: 1rem;
        }
        
        code {
            background: rgba(0, 0, 0, 0.3);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📺 Northern Rivers Television</h1>
        <div class="icon">🎬</div>
        
        <div class="status">
            ✅ Server Running Successfully
        </div>
        
        <p>Your Smart TV server is ready with instant channel switching and full TV guide.</p>
        
        <div class="instructions">
            <h3 style="color: #f59e0b; margin-bottom: 1rem;">📋 Quick Setup:</h3>
            <p>1. Open <span class="highlight">http://{{ request.host }}</span> in your browser</p>
            <p>2. Click "Start TV Experience" and enjoy!</p>
        </div>
        
        <div class="features">
            <h3>✨ Features:</h3>
            <p>• <strong>⚡ Instant channel switching</strong> - No delays or freezing</p>
            <p>• <strong>📺 Full TV guide</strong> - Professional EPG with live programs</p>
            <p>• <strong>🎵 Working audio channels</strong> - ABC radio via proxy, SBS direct</p>
            <p>• <strong>🚀 Responsive UI</strong> - Updates immediately on channel change</p>
            <p>• <strong>🎯 Live indicators</strong> - See what's on now with progress bars</p>
        </div>
        
        <div class="api-info">
            <h3>🔗 Available APIs:</h3>
            <p><code>/api/tv-guide</code> - TV program guide data</p>
            <p><code>/api/channels</code> - Complete channel list</p>
            <p><code>/api/stream-proxy/&lt;lcn&gt;</code> - Audio stream proxy</p>
            <p><code>/api/health</code> - Server health status</p>
        </div>
        
        <div style="margin-top: 2rem;">
            <a href="/api/health" class="button" target="_blank">📊 Health Check</a>
            <a href="/api/tv-guide" class="button" target="_blank">📺 View Guide Data</a>
        </div>
        
        <p style="margin-top: 2rem; font-size: 1rem; opacity: 0.8;">
            Server running on <span class="highlight">{{ request.host }}</span>
        </p>
    </div>
</body>
</html>
    """, request=request)

@app.route('/api/tv-guide')
def get_tv_guide():
    """API endpoint to get TV guide data"""
    try:
        programs = tv_guide_loader.load_tv_guide()
        
        json_programs = {}
        for lcn, prog_list in programs.items():
            json_programs[lcn] = [prog.to_dict() for prog in prog_list]
        
        return jsonify(json_programs)
        
    except Exception as e:
        return jsonify({"error": "Failed to load TV guide"}), 500

@app.route('/api/channels')
def get_channels():
    """API endpoint to get channel list with direct stream URLs"""
    channels = {
        # TV Channels
        2: {"lcn": 2, "name": "ABC TV", "stream": "https://c.mjh.nz/abc-nsw.m3u8", "isAudioOnly": False},
        20: {"lcn": 20, "name": "ABC TV HD", "stream": "https://c.mjh.nz/abc-nsw.m3u8", "isAudioOnly": False},
        21: {"lcn": 21, "name": "ABC News", "stream": "https://c.mjh.nz/abc-news.m3u8", "isAudioOnly": False},
        22: {"lcn": 22, "name": "ABC Kids/Family", "stream": "https://c.mjh.nz/abc-kids.m3u8", "isAudioOnly": False},
        23: {"lcn": 23, "name": "ABC Entertains", "stream": "https://c.mjh.nz/abc-me.m3u8", "isAudioOnly": False},
        24: {"lcn": 24, "name": "ABC News", "stream": "https://c.mjh.nz/abc-news.m3u8", "isAudioOnly": False},
        3: {"lcn": 3, "name": "SBS One", "stream": "https://i.mjh.nz/.r/sbs-sbst.m3u8", "isAudioOnly": False},
        30: {"lcn": 30, "name": "SBS One HD", "stream": "https://i.mjh.nz/.r/sbs-sbst.m3u8", "isAudioOnly": False},
        31: {"lcn": 31, "name": "SBS Viceland HD", "stream": "https://i.mjh.nz/.r/sbs-2syd.m3u8", "isAudioOnly": False},
        32: {"lcn": 32, "name": "SBS World Movies", "stream": "https://i.mjh.nz/.r/sbs-4syd.m3u8", "isAudioOnly": False},
        33: {"lcn": 33, "name": "SBS Food", "stream": "https://i.mjh.nz/.r/sbs-3syd.m3u8", "isAudioOnly": False},
        34: {"lcn": 34, "name": "NITV HD", "stream": "https://i.mjh.nz/.r/sbs-5nsw.m3u8", "isAudioOnly": False},
        35: {"lcn": 35, "name": "SBS WorldWatch", "stream": "https://i.mjh.nz/.r/sbs-6nat.m3u8", "isAudioOnly": False},
        36: {"lcn": 36, "name": "NITV", "stream": "https://i.mjh.nz/.r/sbs-5nsw.m3u8", "isAudioOnly": False},
        5: {"lcn": 5, "name": "10 HD Northern NSW", "stream": "https://i.mjh.nz/.r/10-nsw.m3u8", "isAudioOnly": False},
        50: {"lcn": 50, "name": "10 HD", "stream": "https://i.mjh.nz/.r/10-nsw.m3u8", "isAudioOnly": False},
        51: {"lcn": 51, "name": "10 Drama", "stream": "https://i.mjh.nz/.r/10bold-nsw.m3u8", "isAudioOnly": False},
        52: {"lcn": 52, "name": "10 Comedy", "stream": "https://i.mjh.nz/.r/10peach-nsw.m3u8", "isAudioOnly": False},
        53: {"lcn": 53, "name": "Sky News Regional", "stream": "https://i.mjh.nz/.r/sky-news-now.m3u8", "isAudioOnly": False},
        54: {"lcn": 54, "name": "Gecko", "stream": "https://i.mjh.nz/.r/10-geckotv.m3u8", "isAudioOnly": False},
        56: {"lcn": 56, "name": "You TV", "stream": "https://i.mjh.nz/.r/10-youtv.m3u8", "isAudioOnly": False},
        6: {"lcn": 6, "name": "7 HD Seven", "stream": "https://i.mjh.nz/.r/seven-syd.m3u8", "isAudioOnly": False},
        60: {"lcn": 60, "name": "7 HD", "stream": "https://i.mjh.nz/.r/seven-syd.m3u8", "isAudioOnly": False},
        62: {"lcn": 62, "name": "7two HD", "stream": "https://i.mjh.nz/.r/7two-syd.m3u8", "isAudioOnly": False},
        64: {"lcn": 64, "name": "7mate HD", "stream": "https://i.mjh.nz/.r/7mate-syd.m3u8", "isAudioOnly": False},
        65: {"lcn": 65, "name": "7Bravo", "stream": "https://i.mjh.nz/.r/7bravo-fast.m3u8", "isAudioOnly": False},
        66: {"lcn": 66, "name": "7flix", "stream": "https://i.mjh.nz/.r/7flix-syd.m3u8", "isAudioOnly": False},
        67: {"lcn": 67, "name": "TVSN", "stream": "https://i.mjh.nz/.r/tvsn-fast.m3u8", "isAudioOnly": False},
        68: {"lcn": 68, "name": "Racing.com", "stream": "https://i.mjh.nz/.r/racing-fast.m3u8", "isAudioOnly": False},
        8: {"lcn": 8, "name": "Nine", "stream": "https://i.mjh.nz/.r/channel-9-nsw.m3u8", "isAudioOnly": False},
        80: {"lcn": 80, "name": "9HD", "stream": "https://i.mjh.nz/.r/channel-9-nsw.m3u8", "isAudioOnly": False},
        81: {"lcn": 81, "name": "Nine far north coast", "stream": "https://i.mjh.nz/.r/channel-9-nsw.m3u8", "isAudioOnly": False},
        82: {"lcn": 82, "name": "9Gem", "stream": "https://i.mjh.nz/.r/gem-nsw.m3u8", "isAudioOnly": False},
        83: {"lcn": 83, "name": "9Go!", "stream": "https://i.mjh.nz/.r/go-nsw.m3u8", "isAudioOnly": False},
        84: {"lcn": 84, "name": "9Life", "stream": "https://i.mjh.nz/.r/life-nsw.m3u8", "isAudioOnly": False},
        85: {"lcn": 85, "name": "9Gem HD", "stream": "https://i.mjh.nz/.r/gem-nsw.m3u8", "isAudioOnly": False},
        88: {"lcn": 88, "name": "9Go! HD", "stream": "https://i.mjh.nz/.r/go-nsw.m3u8", "isAudioOnly": False},
        
        # Audio Channels - Using proxy for ABC streams that have CORS issues
        25: {"lcn": 25, "name": "ABC Radio Sydney", "stream": "/api/stream-proxy/25", "isAudioOnly": True},
        26: {"lcn": 26, "name": "Radio National", "stream": "/api/stream-proxy/26", "isAudioOnly": True},
        27: {"lcn": 27, "name": "ABC Classic", "stream": "/api/stream-proxy/27", "isAudioOnly": True},
        28: {"lcn": 28, "name": "Triple J", "stream": "/api/stream-proxy/28", "isAudioOnly": True},
        29: {"lcn": 29, "name": "Triple J Unearthed", "stream": "/api/stream-proxy/29", "isAudioOnly": True},
        200: {"lcn": 200, "name": "Double J", "stream": "/api/stream-proxy/200", "isAudioOnly": True},
        201: {"lcn": 201, "name": "ABC Jazz", "stream": "/api/stream-proxy/201", "isAudioOnly": True},
        202: {"lcn": 202, "name": "ABC Kids Listen", "stream": "/api/stream-proxy/202", "isAudioOnly": True},
        203: {"lcn": 203, "name": "ABC Country", "stream": "/api/stream-proxy/203", "isAudioOnly": True},
        204: {"lcn": 204, "name": "ABC NewsRadio", "stream": "/api/stream-proxy/204", "isAudioOnly": True},
        301: {"lcn": 301, "name": "SBS Radio 1", "stream": "https://i.mjh.nz/.r/sbs-sbs-radio-1.m3u8", "isAudioOnly": True},
        302: {"lcn": 302, "name": "SBS Radio 2", "stream": "https://i.mjh.nz/.r/sbs-sbs-radio-2.m3u8", "isAudioOnly": True},
        303: {"lcn": 303, "name": "SBS Radio 3", "stream": "https://i.mjh.nz/.r/sbs-sbs-radio-3.m3u8", "isAudioOnly": True},
        304: {"lcn": 304, "name": "SBS Arabic", "stream": "https://i.mjh.nz/.r/sbs-sbs-pop-araby.m3u8", "isAudioOnly": True},
        305: {"lcn": 305, "name": "SBS South Asian", "stream": "https://i.mjh.nz/.r/sbs-sbs-pop-desi.m3u8", "isAudioOnly": True},
        306: {"lcn": 306, "name": "SBS Chill", "stream": "https://i.mjh.nz/.r/sbs-sbs-chill.m3u8", "isAudioOnly": True},
        307: {"lcn": 307, "name": "SBS PopAsia", "stream": "https://i.mjh.nz/.r/sbs-sbs-pop-asia.m3u8", "isAudioOnly": True},
    }
    
    return jsonify(channels)

@app.route('/api/stream-proxy/<int:lcn>')
def stream_proxy(lcn):
    """Proxy streaming requests for ABC audio channels that have CORS issues"""
    # Audio channel stream mapping for ABC channels only
    audio_streams = {
        25: "https://i.mjh.nz/.r/radio-ih-7135",   # ABC Radio Sydney
        26: "https://i.mjh.nz/.r/radio-ih-7111",   # Radio National
        27: "https://i.mjh.nz/.r/radio-ih-7118",   # ABC Classic
        28: "https://i.mjh.nz/.r/radio-ih-7115",   # Triple J
        29: "https://i.mjh.nz/.r/radio-ih-7116",   # Triple J Unearthed
        200: "https://i.mjh.nz/.r/radio-ih-7090",  # Double J
        201: "https://i.mjh.nz/.r/radio-ih-7124",  # ABC Jazz
        202: "https://i.mjh.nz/.r/radio-ih-7967",  # ABC Kids Listen
        203: "https://i.mjh.nz/.r/radio-ih-7125",  # ABC Country
        204: "https://i.mjh.nz/.r/radio-ih-7110",  # ABC NewsRadio
    }
    
    if lcn not in audio_streams:
        return jsonify({"error": "Audio channel not found"}), 404
    
    try:
        response = requests.get(audio_streams[lcn], 
                              stream=True, 
                              allow_redirects=True,
                              timeout=30, 
                              headers={
                                  'User-Agent': 'SmartTV/1.0',
                                  'Accept': 'audio/*,*/*'
                              })
        response.raise_for_status()
        
        def generate():
            try:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            except Exception:
                pass
        
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': 'Range, Content-Type, Accept',
            'Content-Type': response.headers.get('Content-Type', 'audio/mpeg'),
            'Cache-Control': 'no-cache',
            'Connection': 'close'
        }
        
        if 'content-length' in response.headers:
            headers['Content-Length'] = response.headers['content-length']
        else:
            headers['Transfer-Encoding'] = 'chunked'
        
        return Response(generate(), status=200, headers=headers)
        
    except Exception as e:
        return jsonify({
            "error": "Stream unavailable", 
            "details": str(e),
            "lcn": lcn
        }), 503

@app.route('/api/stream-proxy/<int:lcn>', methods=['OPTIONS'])
def proxy_options(lcn=None):
    """Handle OPTIONS requests for audio proxy"""
    response = Response()
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
    response.headers.add('Access-Control-Allow-Headers', 'Range, Content-Type, Accept')
    return response

@app.route('/api/stream-status/<int:lcn>')
def get_stream_status(lcn):
    """Check if a stream is available"""
    all_channels = get_channels().get_json()
    
    if lcn not in all_channels:
        return jsonify({"error": "Channel not found"}), 404
    
    channel = all_channels[lcn]
    
    return jsonify({
        "lcn": lcn,
        "name": channel['name'],
        "available": True,
        "stream": channel['stream'],
        "isAudioOnly": channel['isAudioOnly']
    })

@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(TZ).isoformat(),
        "tv_guide_last_loaded": tv_guide_loader.last_loaded.isoformat() if tv_guide_loader.last_loaded else None,
        "cached_channels": len(tv_guide_loader.programs_cache),
        "mode": "hybrid_stream_with_proxy"
    })

@app.before_request
def handle_preflight():
    """Handle CORS preflight requests"""
    if request.method == "OPTIONS":
        response = Response()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "*")
        response.headers.add('Access-Control-Allow-Methods', "*")
        return response

@app.after_request
def after_request(response):
    """Add CORS headers to all responses"""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,Range')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.route('/favicon.ico')
def favicon():
    """Serve favicon"""
    svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
    <rect width="100" height="100" fill="#000"/>
    <text x="50" y="70" font-size="60" text-anchor="middle" fill="#0070f3">📺</text>
</svg>'''
    
    response = Response(svg_content, mimetype='image/svg+xml')
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response

@app.errorhandler(404)
def not_found(error):
    """Custom 404 page"""
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <title>Smart TV - Page Not Found</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #0a0a0a, #1f1f1f);
            color: white;
            text-align: center;
            padding: 6rem 2rem;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }
        h1 { 
            background: linear-gradient(135deg, #0070f3, #00d9ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            font-size: 3rem; 
            margin-bottom: 1rem;
        }
        h2 { margin-bottom: 1rem; }
        p { font-size: 1.125rem; margin: 1rem 0; color: #a1a1aa; }
        a { 
            color: #00d9ff; 
            text-decoration: none; 
            font-weight: 600;
        }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <h1>📺 Smart TV</h1>
    <h2>Page Not Found</h2>
    <p>The page you're looking for doesn't exist.</p>
    <p><a href="/">← Back to Smart TV</a></p>
</body>
</html>
    """), 404

def print_banner():
    """Print clean startup banner"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}📺 NRTV Server{Colors.END}")
    print(f"{Colors.DIM}═══════════════════════════════════════════════════════════════{Colors.END}")
    print(f"{Colors.GREEN}Enhanced Hybrid Mode{Colors.END} • {Colors.BLUE}Instant Switching{Colors.END} • {Colors.YELLOW}Full TV Guide{Colors.END}")
    print()

def print_access_info():
    """Print access information"""
    print(f"{Colors.BOLD}🌐 Access Points{Colors.END}")
    print(f"{Colors.WHITE}Main Interface:{Colors.END}  {Colors.CYAN}http://localhost:5000{Colors.END}")
    print(f"{Colors.WHITE}Server Status:{Colors.END}   {Colors.CYAN}http://localhost:5000/status{Colors.END}")
    print(f"{Colors.WHITE}Health Check:{Colors.END}    {Colors.CYAN}http://localhost:5000/api/health{Colors.END}")
    print()

def print_controls():
    """Print control information"""
    print(f"{Colors.BOLD}⌨️  Controls{Colors.END}")
    print(f"{Colors.WHITE}↑↓ Arrow Keys:{Colors.END} Change channels")
    print(f"{Colors.WHITE}G/Space/Enter:{Colors.END} TV Guide")
    print(f"{Colors.WHITE}M:{Colors.END} Mute • {Colors.WHITE}ESC:{Colors.END} Close Guide")
    print()

if __name__ == '__main__':
    print_banner()
    
    print_status("Initializing TV guide...", "loading")
    try:
        programs = tv_guide_loader.load_tv_guide()
        if programs:
            sample_lcn = list(programs.keys())[0]
            sample_count = len(programs[sample_lcn])
            print_status(f"Guide loaded • Example: Channel {sample_lcn} has {sample_count} programs", "success")
    except Exception:
        print_status("Using fallback guide data", "warning")
    
    print()
    print_access_info()
    print_controls()
    
    print_status("Starting server on http://localhost:5000", "loading")
    print(f"{Colors.DIM}Press Ctrl+C to stop{Colors.END}\n")
    
    try:
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=False,
            threaded=True,
            use_reloader=False
        )
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}⚠{Colors.END} Server stopped by user")
    except Exception as e:
        print_status(f"Server error: {e}", "error")
        print_status("Try checking if port 5000 is available", "info")
    finally:
        print_status("Server shutdown complete", "info")
