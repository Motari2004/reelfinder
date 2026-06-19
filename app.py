"""
Daily Reel URL Generator - Full UI Control with Settings
"""

import asyncio
import re
import json
import logging
import sys
import os
import math
from typing import List, Dict, Optional, Set, Any, Union
from dataclasses import dataclass, asdict, field
from datetime import datetime
from fastapi import FastAPI, Query, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from playwright.async_api import async_playwright, Page, Browser

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('reels_daily.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Daily Reel URL Generator", version="4.0.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Default topics
DEFAULT_TOPICS = ["mafia", "gangstars", "murphy", "war", "ninjas"]

# Global state
scheduler_running = True
scraper = None
collector = None
scheduler = None


def safe_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        if isinstance(value, float) and math.isnan(value):
            return 0
        return int(float(value))
    except (ValueError, TypeError):
        return 0


@dataclass
class ReelData:
    url: str
    shortcode: str
    username: str
    caption: str
    likes: int
    comments: int
    views: int
    timestamp: str
    thumbnail_url: str = ""
    hashtags: List[str] = field(default_factory=list)
    mentioned_users: List[str] = field(default_factory=list)
    
    def to_dict(self):
        return {
            "url": str(self.url),
            "shortcode": str(self.shortcode),
            "username": str(self.username),
            "caption": str(self.caption),
            "likes": safe_int(self.likes),
            "comments": safe_int(self.comments),
            "views": safe_int(self.views),
            "timestamp": str(self.timestamp),
            "thumbnail_url": str(self.thumbnail_url),
            "hashtags": [str(h) for h in self.hashtags],
            "mentioned_users": [str(m) for m in self.mentioned_users]
        }


@dataclass
class DailyCollection:
    date: str
    topics: Dict[str, List[ReelData]]
    total_count: int
    generated_at: str
    
    def to_dict(self):
        return {
            "date": str(self.date),
            "topics": {str(topic): [reel.to_dict() for reel in reels] for topic, reels in self.topics.items()},
            "total_count": safe_int(self.total_count),
            "generated_at": str(self.generated_at)
        }


class UniversalReelsFinder:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser = None
        self.page = None
        self.playwright = None
        self.search_url = "https://reelsfinder.satishyadav.com"
        
    async def initialize(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--disable-gpu',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        self.page = await self.browser.new_page()
        await self.page.set_viewport_size({"width": 1316, "height": 627})
        logger.info("Browser initialized")
        
    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser closed")
    
    async def search(self, query: str, max_results: int = 50, search_type: str = "auto") -> List[ReelData]:
        reels = []
        seen_shortcodes = set()
        
        try:
            query = query.strip()
            search_term = self._normalize_query(query, search_type)
            
            logger.info(f"Searching for: {search_term}")
            
            # Direct search URL
            search_url = f'{self.search_url}/#gsc.tab=0&gsc.q={search_term.replace(" ", "+")}'
            await self.page.goto(search_url)
            await self.page.wait_for_load_state('networkidle', timeout=15000)
            
            await asyncio.sleep(3)
            
            for _ in range(4):
                await self.page.mouse.wheel(0, 500)
                await asyncio.sleep(1)
            
            links = await self.page.evaluate('''
                () => {
                    const links = [];
                    const elements = document.querySelectorAll('a[href*="instagram.com/reel/"], a[href*="instagram.com/p/"]');
                    
                    elements.forEach(el => {
                        const href = el.href || '';
                        let text = el.textContent || '';
                        let parent = el.parentElement;
                        for (let i = 0; i < 5 && parent; i++) {
                            if (parent.textContent && parent.textContent.length > 10) {
                                text = parent.textContent;
                                break;
                            }
                            parent = parent.parentElement;
                        }
                        
                        const img = el.querySelector('img');
                        const thumbnail = img ? img.src : '';
                        
                        links.push({
                            href: href,
                            text: text,
                            thumbnail: thumbnail
                        });
                    });
                    return links;
                }
            ''')
            
            logger.info(f"Found {len(links)} potential reel links")
            
            for link_data in links:
                href = link_data.get('href', '')
                text = link_data.get('text', '')
                
                shortcode_match = re.search(r'instagram\.com/(?:reel|p)/([A-Za-z0-9_-]+)', href)
                if not shortcode_match:
                    continue
                    
                shortcode = shortcode_match.group(1)
                if shortcode in seen_shortcodes:
                    continue
                    
                seen_shortcodes.add(shortcode)
                
                username_match = re.search(r'@([A-Za-z0-9_.]+)', text)
                username = username_match.group(1) if username_match else 'unknown'
                
                caption = ''
                if username_match:
                    caption_parts = text.split(username_match.group(0))
                    if len(caption_parts) > 1:
                        caption = caption_parts[1].strip()[:200]
                
                hashtags = re.findall(r'#([A-Za-z0-9_]+)', text)
                
                likes = 0
                likes_match = re.search(r'([\d.]+[KM]?)\s*(?:likes|❤️|♥)', text, re.IGNORECASE)
                if likes_match:
                    likes_str = likes_match.group(1).upper()
                    try:
                        if 'K' in likes_str:
                            likes = int(float(likes_str.replace('K', '')) * 1000)
                        elif 'M' in likes_str:
                            likes = int(float(likes_str.replace('M', '')) * 1000000)
                        else:
                            likes = int(float(likes_str))
                    except:
                        likes = 0
                
                comments = 0
                comments_match = re.search(r'([\d.]+[KM]?)\s*(?:comments|💬)', text, re.IGNORECASE)
                if comments_match:
                    comments_str = comments_match.group(1).upper()
                    try:
                        if 'K' in comments_str:
                            comments = int(float(comments_str.replace('K', '')) * 1000)
                        elif 'M' in comments_str:
                            comments = int(float(comments_str.replace('M', '')) * 1000000)
                        else:
                            comments = int(float(comments_str))
                    except:
                        comments = 0
                
                views = 0
                views_match = re.search(r'([\d.]+[KM]?)\s*(?:views|👁️)', text, re.IGNORECASE)
                if views_match:
                    views_str = views_match.group(1).upper()
                    try:
                        if 'K' in views_str:
                            views = int(float(views_str.replace('K', '')) * 1000)
                        elif 'M' in views_str:
                            views = int(float(views_str.replace('M', '')) * 1000000)
                        else:
                            views = int(float(views_str))
                    except:
                        views = 0
                
                reel = ReelData(
                    url=href,
                    shortcode=shortcode,
                    username=username,
                    caption=caption if caption else 'No caption',
                    likes=likes,
                    comments=comments,
                    views=views,
                    timestamp=datetime.now().isoformat(),
                    thumbnail_url=link_data.get('thumbnail', ''),
                    hashtags=hashtags,
                    mentioned_users=[]
                )
                reels.append(reel)
                
                if len(reels) >= max_results:
                    break
            
            logger.info(f"Extracted {len(reels)} reels for '{query}'")
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            
        return reels
    
    def _normalize_query(self, query: str, search_type: str) -> str:
        query = query.strip()
        
        if search_type == "hashtag":
            if not query.startswith('#'):
                return f'#{query}'
            return query
        elif search_type == "username":
            if query.startswith('@'):
                return query[1:]
            return query
        else:
            if query.startswith('#'):
                return query[1:]
            elif query.startswith('@'):
                return query[1:]
            return query


class DailyReelCollector:
    def __init__(self, scraper: UniversalReelsFinder):
        self.scraper = scraper
        self.topics: List[str] = []
        self.reels_per_topic = 5
        self.collection_history: List[Dict] = []
        self.current_collection: Optional[DailyCollection] = None
        self.collection_file = "daily_reels.json"
        self.topics_file = "topics_config.json"
        self._load_topics()
        
    def _load_topics(self):
        if os.path.exists(self.topics_file):
            try:
                with open(self.topics_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    topics_data = data.get("topics", [])
                    
                    if isinstance(topics_data, dict):
                        self.topics = list(topics_data.keys())
                    elif isinstance(topics_data, list):
                        self.topics = topics_data
                    else:
                        self.topics = DEFAULT_TOPICS.copy()
                    
                    self.topics = [t for t in self.topics if t and isinstance(t, str)]
                    if not self.topics:
                        self.topics = DEFAULT_TOPICS.copy()
                        
            except Exception as e:
                logger.error(f"Error loading topics: {e}")
                self.topics = DEFAULT_TOPICS.copy()
        else:
            self.topics = DEFAULT_TOPICS.copy()
            self._save_topics()
    
    def _save_topics(self):
        try:
            with open(self.topics_file, 'w', encoding='utf-8') as f:
                json.dump({"topics": self.topics, "updated": datetime.now().isoformat()}, f, indent=2)
            logger.info(f"Saved {len(self.topics)} topics")
        except Exception as e:
            logger.error(f"Error saving topics: {e}")
    
    def update_topics(self, new_topics: List[str]):
        clean_topics = []
        for t in new_topics:
            t = t.strip().lower()
            if t and t not in clean_topics:
                clean_topics.append(t)
        
        if not clean_topics:
            return False
        
        self.topics = clean_topics
        self._save_topics()
        return True
    
    def add_topic(self, topic: str):
        topic = topic.strip().lower()
        if not topic:
            return False
        if topic in self.topics:
            return False
        self.topics.append(topic)
        self._save_topics()
        return True
    
    def remove_topic(self, topic: str):
        topic = topic.strip().lower()
        if topic not in self.topics:
            return False
        self.topics.remove(topic)
        self._save_topics()
        return True
    
    async def generate_daily_reels(self) -> DailyCollection:
        logger.info("Starting daily reel collection...")
        
        topic_reels = {}
        total_count = 0
        
        for topic in self.topics:
            logger.info(f"Collecting reels for: {topic}")
            
            variations = [
                topic,
                f"#{topic}",
                f"{topic} daily",
                f"{topic} trending"
            ]
            
            all_reels = []
            seen_shortcodes = set()
            
            for variation in variations[:3]:
                if len(all_reels) >= self.reels_per_topic * 2:
                    break
                    
                try:
                    reels = await self.scraper.search(variation, max_results=20)
                    
                    for reel in reels:
                        if reel.shortcode not in seen_shortcodes:
                            seen_shortcodes.add(reel.shortcode)
                            if self._is_relevant(reel, topic):
                                all_reels.append(reel)
                except Exception as e:
                    logger.error(f"Error searching {variation}: {e}")
                    continue
                
                await asyncio.sleep(1)
            
            selected_reels = self._select_unique_reels(all_reels, self.reels_per_topic)
            topic_reels[topic] = selected_reels
            total_count += len(selected_reels)
            
            logger.info(f"Collected {len(selected_reels)} reels for {topic}")
        
        self.current_collection = DailyCollection(
            date=datetime.now().strftime("%Y-%m-%d"),
            topics=topic_reels,
            total_count=total_count,
            generated_at=datetime.now().isoformat()
        )
        
        self.collection_history.append(self.current_collection.to_dict())
        self._save_collection()
        
        logger.info(f"Daily collection complete: {total_count} total reels")
        return self.current_collection
    
    def _is_relevant(self, reel: ReelData, topic: str) -> bool:
        text = (reel.caption + ' ' + ' '.join(reel.hashtags)).lower()
        topic_lower = topic.lower()
        
        if topic_lower in text:
            return True
        
        return False
    
    def _select_unique_reels(self, reels: List[ReelData], count: int) -> List[ReelData]:
        if len(reels) <= count:
            return reels
        
        sorted_reels = sorted(reels, key=lambda r: r.likes + r.comments, reverse=True)
        
        selected = []
        used_users = set()
        
        for reel in sorted_reels:
            if reel.username not in used_users:
                selected.append(reel)
                used_users.add(reel.username)
                if len(selected) >= count:
                    break
        
        if len(selected) < count:
            remaining = [r for r in sorted_reels if r not in selected]
            selected.extend(remaining[:count - len(selected)])
        
        return selected[:count]
    
    def _save_collection(self):
        data = {
            "history": self.collection_history,
            "current": self.current_collection.to_dict() if self.current_collection else None,
            "last_updated": datetime.now().isoformat()
        }
        with open(self.collection_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def load_collection(self):
        if os.path.exists(self.collection_file):
            try:
                with open(self.collection_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.collection_history = data.get("history", [])
                logger.info(f"Loaded {len(self.collection_history)} historical collections")
            except Exception as e:
                logger.error(f"Error loading collection: {e}")
    
    def get_today_collection(self) -> Optional[DailyCollection]:
        today = datetime.now().strftime("%Y-%m-%d")
        
        if self.current_collection and self.current_collection.date == today:
            return self.current_collection
        
        for collection in self.collection_history:
            if collection.get("date") == today:
                topics = {}
                for topic, reels_data in collection.get("topics", {}).items():
                    topics[topic] = [ReelData(**data) for data in reels_data]
                return DailyCollection(
                    date=collection["date"],
                    topics=topics,
                    total_count=collection["total_count"],
                    generated_at=collection["generated_at"]
                )
        
        return None
    
    def get_reel_urls(self, topic: Optional[str] = None) -> List[str]:
        collection = self.get_today_collection()
        if not collection:
            return []
        
        if topic:
            reels = collection.topics.get(topic, [])
            return [reel.url for reel in reels]
        
        all_urls = []
        for reels in collection.topics.values():
            all_urls.extend([reel.url for reel in reels])
        return all_urls


async def daily_collection_job():
    global collector, scraper, scheduler_running
    
    if not scheduler_running:
        logger.info("Scheduler is stopped - skipping collection")
        return
    
    logger.info("Running daily collection job...")
    
    try:
        if not scraper.page:
            await scraper.initialize()
        
        collection = await collector.generate_daily_reels()
        logger.info(f"Daily collection completed: {collection.total_count} reels")
        
        for topic, reels in collection.topics.items():
            logger.info(f"  {topic}: {len(reels)} reels")
            for reel in reels:
                logger.info(f"    - {reel.url}")
        
    except Exception as e:
        logger.error(f"Daily collection job failed: {e}")


# ======================== UI HTML ========================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Daily Reel URL Generator</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px; margin: 0 auto; padding: 20px;
            background: #0a0a0a; color: #fff;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1a1a, #2a2a2a);
            padding: 30px; border-radius: 16px; margin-bottom: 30px;
            text-align: center;
        }
        h1 { font-size: 36px; color: #dc2743; margin-bottom: 10px; }
        .subtitle { color: #888; font-size: 16px; }
        
        .stats {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px; margin: 20px 0;
        }
        .stat-card {
            background: #1a1a1a; padding: 20px; border-radius: 12px;
            text-align: center; border: 1px solid #333;
        }
        .stat-number { font-size: 28px; font-weight: bold; color: #dc2743; }
        .stat-label { color: #888; font-size: 13px; margin-top: 5px; }
        
        .section {
            background: #1a1a1a; padding: 25px; border-radius: 12px;
            margin-bottom: 20px;
        }
        .section h2 { color: #fff; margin-bottom: 15px; }
        
        .switch-container {
            display: flex; align-items: center; gap: 20px;
            background: #2a2a2a; padding: 15px 25px; border-radius: 12px;
            flex-wrap: wrap;
        }
        .switch {
            position: relative; width: 70px; height: 38px;
            flex-shrink: 0;
        }
        .switch input {
            opacity: 0; width: 0; height: 0;
        }
        .slider {
            position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
            background: #555; transition: .4s; border-radius: 38px;
        }
        .slider:before {
            position: absolute; content: ""; height: 30px; width: 30px;
            left: 4px; bottom: 4px; background: white; transition: .4s; border-radius: 50%;
        }
        input:checked + .slider { background: #dc2743; }
        input:checked + .slider:before { transform: translateX(32px); }
        
        .switch-label { font-size: 20px; font-weight: 700; }
        .switch-status { font-size: 14px; color: #888; }
        .status-running { color: #10b981; }
        .status-stopped { color: #ef4444; }
        
        .topic-input-area {
            display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 15px;
        }
        .topic-input-area input {
            flex: 1; min-width: 200px; padding: 12px 16px;
            background: #0a0a0a; border: 2px solid #333; border-radius: 8px;
            color: #fff; font-size: 14px;
        }
        .topic-input-area input:focus { outline: none; border-color: #dc2743; }
        
        .topic-list {
            display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 0;
        }
        .topic-tag {
            background: #2a2a2a; padding: 8px 16px; border-radius: 20px;
            border: 1px solid #dc2743; display: flex; align-items: center; gap: 10px;
            font-size: 14px;
        }
        .topic-tag .remove {
            cursor: pointer; color: #ff4444; font-weight: bold; font-size: 18px;
            line-height: 1;
        }
        .topic-tag .remove:hover { color: #ff6666; transform: scale(1.2); }
        
        .btn {
            display: inline-block; padding: 10px 20px;
            background: #dc2743; color: #fff;
            border: none; border-radius: 8px;
            cursor: pointer; text-decoration: none;
            transition: all 0.3s; font-size: 14px;
            font-weight: 600;
        }
        .btn:hover { background: #bc1888; transform: translateY(-2px); }
        .btn-secondary { background: #2a2a2a; border: 1px solid #444; }
        .btn-secondary:hover { background: #333; }
        .btn-success { background: #10b981; }
        .btn-success:hover { background: #059669; }
        .btn-danger { background: #ef4444; }
        .btn-danger:hover { background: #dc2626; }
        .btn-warning { background: #f59e0b; color: #000; }
        .btn-warning:hover { background: #d97706; }
        
        .action-buttons {
            display: flex; gap: 10px; flex-wrap: wrap;
        }
        
        .topic-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 15px;
        }
        .topic-card {
            background: #2a2a2a; padding: 15px; border-radius: 10px;
            border-left: 4px solid #dc2743;
        }
        .topic-name { font-weight: bold; color: #dc2743; margin-bottom: 10px; }
        .reel-item {
            padding: 6px 0; border-bottom: 1px solid #333; font-size: 13px;
            display: flex; justify-content: space-between; align-items: center;
        }
        .reel-item:last-child { border-bottom: none; }
        .reel-url { color: #4ade80; word-break: break-all; text-decoration: none; }
        .reel-url:hover { text-decoration: underline; }
        .reel-meta { color: #888; font-size: 12px; }
        
        .footer {
            text-align: center; color: #666; font-size: 13px;
            margin-top: 30px; padding: 20px; border-top: 1px solid #333;
        }
        .status-msg { padding: 10px; border-radius: 8px; margin: 10px 0; display: none; }
        .status-msg.success { display: block; background: #10b98120; border: 1px solid #10b981; }
        .status-msg.error { display: block; background: #ef444420; border: 1px solid #ef4444; }
        .status-msg.info { display: block; background: #3b82f620; border: 1px solid #3b82f6; }
        .status-msg.warning { display: block; background: #f59e0b20; border: 1px solid #f59e0b; }
        
        .last-run { color: #888; font-size: 13px; margin-left: auto; }
        
        @media (max-width: 600px) {
            .topic-grid { grid-template-columns: 1fr; }
            .stats { grid-template-columns: 1fr 1fr; }
            .switch-container { flex-direction: column; align-items: stretch; text-align: center; }
            .last-run { margin-left: 0; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🎬 Daily Reel URL Generator</h1>
        <p class="subtitle">Full UI Control - Manage topics, scheduler, and generate daily Reel URLs</p>
    </div>
    
    <div id="statsContainer"></div>
    
    <div class="section">
        <h2>⏹️ Scheduler Control (Kill Switch)</h2>
        <div class="switch-container">
            <div>
                <div class="switch-label">
                    <span id="statusText">⏹️ Stopped</span>
                </div>
                <div class="switch-status">
                    Status: <span id="statusDetail" class="status-stopped">Scheduler is OFF</span>
                </div>
            </div>
            <label class="switch">
                <input type="checkbox" id="schedulerSwitch" onchange="toggleScheduler()" checked>
                <span class="slider"></span>
            </label>
            <div class="last-run" id="lastRunTime">Last run: Never</div>
        </div>
    </div>
    
    <div class="section">
        <h2>🔧 Manage Topics</h2>
        <div class="topic-input-area">
            <input type="text" id="newTopicInput" placeholder="Enter topic name..." onkeypress="if(event.key==='Enter') addTopic()">
            <button class="btn btn-success" onclick="addTopic()">➕ Add Topic</button>
            <button class="btn btn-secondary" onclick="saveTopics()">💾 Save Topics</button>
            <button class="btn btn-warning" onclick="resetTopics()">🔄 Reset</button>
        </div>
        <div id="topicTags" class="topic-list"></div>
        <div id="topicStatus" class="status-msg"></div>
    </div>
    
    <div class="section">
        <h2>🎯 Actions</h2>
        <div class="action-buttons">
            <button class="btn btn-primary" onclick="generateNow()">🚀 Generate Now</button>
            <button class="btn btn-secondary" onclick="refreshData()">🔄 Refresh</button>
            <button class="btn btn-danger" onclick="clearHistory()">🗑️ Clear History</button>
        </div>
    </div>
    
    <div id="resultsSection" class="section">
        <h2>📋 Today's Reels</h2>
        <div id="resultsContent">
            <div style="text-align:center;color:#888;padding:20px;">No collection yet. Click "Generate Now" or wait for scheduled run.</div>
        </div>
    </div>
    
    <div class="section">
        <h2>📖 Quick Access</h2>
        <div class="action-buttons">
            <a href="/urls" class="btn btn-secondary">📥 All URLs</a>
            <a href="/reels" class="btn btn-secondary">📊 Full Data</a>
            <a href="/history" class="btn btn-secondary">📚 History</a>
        </div>
    </div>
    
    <div class="footer">
        Daily Reel URL Generator v4.0 | Powered by Playwright | Click buttons to control everything
    </div>

    <script>
        let currentTopics = [];
        
        function showStatus(message, type = 'info') {
            const el = document.getElementById('topicStatus');
            el.className = 'status-msg ' + type;
            el.textContent = message;
            setTimeout(() => { el.className = 'status-msg'; }, 5000);
        }
        
        async function loadTopics() {
            try {
                const response = await fetch('/api/topics');
                const data = await response.json();
                currentTopics = data.topics || [];
                renderTopics(currentTopics);
                updateStats(data.stats);
                updateSchedulerStatus(data);
            } catch (error) {
                console.error('Error loading topics:', error);
            }
        }
        
        function renderTopics(topics) {
            const container = document.getElementById('topicTags');
            if (!topics || topics.length === 0) {
                container.innerHTML = '<span style="color:#888;">No topics added. Add some above!</span>';
                return;
            }
            
            container.innerHTML = topics.map(topic => `
                <span class="topic-tag">
                    #${topic}
                    <span class="remove" onclick="removeTopic('${topic}')">×</span>
                </span>
            `).join('');
        }
        
        async function updateStats(stats) {
            const container = document.getElementById('statsContainer');
            if (!stats) return;
            
            container.innerHTML = `
                <div class="stats">
                    <div class="stat-card">
                        <div class="stat-number">${stats.total_topics || 0}</div>
                        <div class="stat-label">Total Topics</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${stats.total_collected || 0}</div>
                        <div class="stat-label">Total Collected</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${stats.today_collected || 0}</div>
                        <div class="stat-label">Collected Today</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${stats.scheduler_running !== undefined ? (stats.scheduler_running ? '✅' : '⏹️') : '📊'}</div>
                        <div class="stat-label">${stats.scheduler_running ? 'Scheduler ON' : 'Scheduler OFF'}</div>
                    </div>
                </div>
            `;
        }
        
        function updateSchedulerStatus(data) {
            const isRunning = data.stats && data.stats.scheduler_running;
            const statusText = document.getElementById('statusText');
            const statusDetail = document.getElementById('statusDetail');
            const switchEl = document.getElementById('schedulerSwitch');
            
            if (isRunning) {
                statusText.textContent = '▶️ Running';
                statusDetail.textContent = 'Scheduler is ON';
                statusDetail.className = 'status-running';
                switchEl.checked = true;
            } else {
                statusText.textContent = '⏹️ Stopped';
                statusDetail.textContent = 'Scheduler is OFF';
                statusDetail.className = 'status-stopped';
                switchEl.checked = false;
            }
            
            if (data.stats && data.stats.last_run) {
                document.getElementById('lastRunTime').textContent = `Last run: ${new Date(data.stats.last_run).toLocaleString()}`;
            }
        }
        
        async function toggleScheduler() {
            const checked = document.getElementById('schedulerSwitch').checked;
            
            try {
                const response = await fetch('/api/scheduler', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ running: checked })
                });
                
                const data = await response.json();
                if (data.success) {
                    showStatus(checked ? '✅ Scheduler started' : '⏹️ Scheduler stopped', checked ? 'success' : 'warning');
                    loadTopics();
                } else {
                    showStatus('❌ ' + data.error, 'error');
                    document.getElementById('schedulerSwitch').checked = !checked;
                }
            } catch (error) {
                showStatus('❌ Error: ' + error.message, 'error');
                document.getElementById('schedulerSwitch').checked = !checked;
            }
        }
        
        async function addTopic() {
            const input = document.getElementById('newTopicInput');
            const topic = input.value.trim().toLowerCase();
            
            if (!topic) {
                showStatus('Please enter a topic name', 'error');
                return;
            }
            
            try {
                const response = await fetch('/api/topics/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ topic: topic })
                });
                
                const data = await response.json();
                if (data.success) {
                    currentTopics = data.topics;
                    renderTopics(currentTopics);
                    showStatus(`✅ Topic "${topic}" added!`, 'success');
                    input.value = '';
                    loadTopics();
                } else {
                    showStatus('❌ ' + data.error, 'error');
                }
            } catch (error) {
                showStatus('❌ Error: ' + error.message, 'error');
            }
        }
        
        async function removeTopic(topic) {
            if (!confirm(`Remove topic "${topic}"?`)) return;
            
            try {
                const response = await fetch(`/api/topics/${topic}`, { method: 'DELETE' });
                const data = await response.json();
                if (data.success) {
                    currentTopics = data.topics;
                    renderTopics(currentTopics);
                    showStatus(`✅ Topic "${topic}" removed`, 'success');
                    loadTopics();
                } else {
                    showStatus('❌ ' + data.error, 'error');
                }
            } catch (error) {
                showStatus('❌ Error: ' + error.message, 'error');
            }
        }
        
        async function saveTopics() {
            try {
                const response = await fetch('/api/topics', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ topics: currentTopics })
                });
                
                const data = await response.json();
                if (data.success) {
                    showStatus('✅ Topics saved!', 'success');
                } else {
                    showStatus('❌ ' + data.error, 'error');
                }
            } catch (error) {
                showStatus('❌ Error: ' + error.message, 'error');
            }
        }
        
        async function resetTopics() {
            if (!confirm('Reset to default topics? (mafia, gangstars, murphy, war, ninjas)')) return;
            
            const defaultTopics = ['mafia', 'gangstars', 'murphy', 'war', 'ninjas'];
            
            try {
                const response = await fetch('/api/topics', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ topics: defaultTopics })
                });
                
                const data = await response.json();
                if (data.success) {
                    currentTopics = data.topics;
                    renderTopics(currentTopics);
                    showStatus('✅ Reset to default topics', 'success');
                    loadTopics();
                } else {
                    showStatus('❌ ' + data.error, 'error');
                }
            } catch (error) {
                showStatus('❌ Error: ' + error.message, 'error');
            }
        }
        
        async function generateNow() {
            showStatus('⏳ Generating reels...', 'info');
            
            try {
                const response = await fetch('/generate/now', { method: 'POST' });
                const data = await response.json();
                
                if (data.success) {
                    showStatus('✅ Generation started! Refreshing...', 'success');
                    setTimeout(() => { loadTopics(); loadResults(); }, 3000);
                } else {
                    showStatus('❌ ' + data.error, 'error');
                }
            } catch (error) {
                showStatus('❌ Error: ' + error.message, 'error');
            }
        }
        
        async function clearHistory() {
            if (!confirm('⚠️ Clear all collection history? This cannot be undone!')) return;
            
            try {
                const response = await fetch('/api/history/clear', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    showStatus('✅ History cleared', 'success');
                    loadTopics();
                    loadResults();
                } else {
                    showStatus('❌ ' + data.error, 'error');
                }
            } catch (error) {
                showStatus('❌ Error: ' + error.message, 'error');
            }
        }
        
        async function loadResults() {
            try {
                const response = await fetch('/reels');
                const data = await response.json();
                const container = document.getElementById('resultsContent');
                
                if (data.success && data.topics && Object.keys(data.topics).length > 0) {
                    let html = '';
                    let total = 0;
                    
                    for (const [topic, reels] of Object.entries(data.topics)) {
                        total += reels.length;
                        html += `
                            <div class="topic-card">
                                <div class="topic-name">#${topic} (${reels.length} reels)</div>
                                ${reels.map(reel => `
                                    <div class="reel-item">
                                        <a href="${reel.url}" target="_blank" class="reel-url">📹 ${reel.shortcode}</a>
                                        <div class="reel-meta">@ ${reel.username} • ❤️ ${reel.likes} • 💬 ${reel.comments}</div>
                                    </div>
                                `).join('')}
                            </div>
                        `;
                    }
                    
                    container.innerHTML = `
                        <div style="margin-bottom:10px;color:#888;">Total: ${total} reels • ${data.date}</div>
                        <div class="topic-grid">${html}</div>
                    `;
                } else {
                    container.innerHTML = '<div style="text-align:center;color:#888;padding:20px;">No reels collected today. Click "Generate Now"!</div>';
                }
            } catch (error) {
                console.error('Error loading results:', error);
            }
        }
        
        async function refreshData() {
            await loadTopics();
            await loadResults();
            showStatus('🔄 Refreshed!', 'info');
        }
        
        // Load on page load
        loadTopics();
        loadResults();
        
        // Auto-refresh every 30 seconds
        setInterval(() => { loadResults(); }, 30000);
    </script>
</body>
</html>
"""


# ======================== API Endpoints ========================
@app.get("/")
async def root():
    return HTMLResponse(HTML_TEMPLATE)

@app.get("/api/topics")
async def get_topics_api():
    global collector, scheduler_running
    
    if not collector:
        return {"topics": DEFAULT_TOPICS, "stats": {"total_topics": 0, "total_collected": 0, "today_collected": 0, "scheduler_running": scheduler_running}}
    
    today_collection = collector.get_today_collection()
    today_count = today_collection.total_count if today_collection else 0
    
    return {
        "topics": collector.topics,
        "stats": {
            "total_topics": len(collector.topics),
            "total_collected": len(collector.collection_history),
            "today_collected": today_count,
            "scheduler_running": scheduler_running,
            "last_run": datetime.now().isoformat()
        }
    }

@app.post("/api/topics")
async def update_topics_api(data: dict):
    global collector
    
    new_topics = data.get("topics", [])
    if not new_topics or len(new_topics) == 0:
        raise HTTPException(status_code=400, detail="At least one topic required")
    
    if collector.update_topics(new_topics):
        return {"success": True, "topics": collector.topics}
    else:
        raise HTTPException(status_code=400, detail="Failed to update topics")

@app.post("/api/topics/add")
async def add_topic_api(data: dict):
    global collector
    
    topic = data.get("topic", "").strip().lower()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic name required")
    
    if collector.add_topic(topic):
        return {"success": True, "topics": collector.topics}
    else:
        raise HTTPException(status_code=400, detail=f"Topic '{topic}' already exists")

@app.delete("/api/topics/{topic}")
async def remove_topic_api(topic: str):
    global collector
    
    if collector.remove_topic(topic):
        return {"success": True, "topics": collector.topics}
    else:
        raise HTTPException(status_code=404, detail=f"Topic '{topic}' not found")

@app.post("/api/scheduler")
async def toggle_scheduler(data: dict):
    global scheduler_running
    
    running = data.get("running", True)
    
    if running and not scheduler_running:
        scheduler_running = True
        logger.info("Scheduler started")
        return {"success": True, "message": "Scheduler started"}
    elif not running and scheduler_running:
        scheduler_running = False
        logger.info("Scheduler stopped (Kill Switch)")
        return {"success": True, "message": "Scheduler stopped"}
    
    return {"success": True, "message": f"Scheduler already {'running' if scheduler_running else 'stopped'}"}

@app.post("/api/history/clear")
async def clear_history():
    global collector
    
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    collector.collection_history = []
    collector.current_collection = None
    collector._save_collection()
    return {"success": True, "message": "History cleared"}

@app.post("/generate")
@app.post("/generate/now")
async def generate_now(background_tasks: BackgroundTasks):
    global collector
    
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    background_tasks.add_task(daily_collection_job)
    return {
        "success": True,
        "message": "Generation started in background",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/urls")
async def get_urls(topic: Optional[str] = None):
    global collector
    
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    urls = collector.get_reel_urls(topic)
    
    if topic:
        return {"topic": topic, "count": len(urls), "urls": urls}
    
    return {"count": len(urls), "urls": urls, "topics": collector.topics}

@app.get("/reels")
async def get_reels():
    global collector
    
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    collection = collector.get_today_collection()
    if not collection:
        return {"success": False, "message": "No collection for today"}
    
    return {
        "success": True,
        "date": collection.date,
        "total_count": collection.total_count,
        "topics": {topic: [reel.to_dict() for reel in reels] for topic, reels in collection.topics.items()},
        "generated_at": collection.generated_at
    }

@app.get("/history")
async def get_history():
    global collector
    
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    return {"total_collections": len(collector.collection_history), "history": collector.collection_history}

@app.get("/health")
async def health_check():
    global collector, scheduler_running
    
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "scheduler_running": scheduler_running,
        "topics": collector.topics if collector else DEFAULT_TOPICS,
        "has_today_collection": collector.get_today_collection() is not None if collector else False
    }


# ======================== Main ========================
@app.on_event("startup")
async def startup_event():
    global scraper, collector, scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    
    scraper = UniversalReelsFinder(headless=True)
    await scraper.initialize()
    logger.info("Universal Reels Finder initialized")
    
    collector = DailyReelCollector(scraper)
    collector.load_collection()
    
    today_collection = collector.get_today_collection()
    if not today_collection:
        logger.info("No collection for today, generating now...")
        await daily_collection_job()
    else:
        logger.info(f"Today's collection already exists: {today_collection.total_count} reels")
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=daily_collection_job,
        trigger=CronTrigger(hour=0, minute=0),
        id="daily_reel_collection",
        replace_existing=True
    )
    scheduler.start()
    logger.info("Scheduler started - daily collection at midnight")

@app.on_event("shutdown")
async def shutdown_event():
    global scraper, scheduler
    if scheduler:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
    if scraper:
        await scraper.close()
        logger.info("Scraper closed")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 Starting server on http://localhost:{port}")
    print("📌 Use the UI to control everything - click buttons, add topics, toggle scheduler")
    uvicorn.run(app, host="0.0.0.0", port=port)