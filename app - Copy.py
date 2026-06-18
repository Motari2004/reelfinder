"""
Daily Reel URL Generator - Scheduled Reel Collector
Generates 5 unique Reel URLs daily for specific topics
"""

import asyncio
import re
import json
import logging
import sys
import os
import random
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from fastapi import FastAPI, Query, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import uvicorn
from playwright.async_api import async_playwright, Page, Browser
import hashlib

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

app = FastAPI(title="Daily Reel URL Generator", version="3.0.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@dataclass
class ReelData:
    """Data structure for a Reel"""
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
        return asdict(self)

@dataclass
class DailyCollection:
    """Daily collection of reels"""
    date: str
    topics: Dict[str, List[ReelData]]
    total_count: int
    generated_at: str
    
    def to_dict(self):
        return {
            "date": self.date,
            "topics": {topic: [reel.to_dict() for reel in reels] for topic, reels in self.topics.items()},
            "total_count": self.total_count,
            "generated_at": self.generated_at
        }


class UniversalReelsFinder:
    """Universal Reels Finder - Search anything"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser = None
        self.page = None
        self.playwright = None
        self.search_url = "https://reelsfinder.satishyadav.com"
        
    async def initialize(self):
        """Initialize browser in headless mode"""
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
        """Close browser"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser closed")
    
    async def search(self, query: str, max_results: int = 50, search_type: str = "auto") -> List[ReelData]:
        """Universal search - handles any query type"""
        reels = []
        seen_shortcodes = set()
        
        try:
            query = query.strip()
            search_term = self._normalize_query(query, search_type)
            
            logger.info(f"Searching for: {search_term}")
            
            await self.page.goto(f'{self.search_url}/#gsc.tab=0')
            await self.page.wait_for_load_state('networkidle')
            
            try:
                await self.page.wait_for_selector('#gsc-i-id1', timeout=10000)
                await self.page.click('#gsc-i-id1')
                await self.page.fill('#gsc-i-id1', search_term)
                await self.page.press('#gsc-i-id1', 'Enter')
                await self.page.wait_for_load_state('networkidle')
            except Exception as e:
                logger.error(f"Search input error: {e}")
                await self.page.goto(f'{self.search_url}/#gsc.tab=0&gsc.q={search_term}')
                await self.page.wait_for_load_state('networkidle')
            
            await asyncio.sleep(2)
            
            # Scroll to load more results
            for _ in range(3):
                await self.page.mouse.wheel(0, 500)
                await asyncio.sleep(1)
            
            # Extract links
            links = await self._extract_reel_links()
            
            for link_data in links:
                href = link_data.get('href', '')
                shortcode_match = re.search(r'instagram\.com/reel/([A-Za-z0-9_-]+)', href)
                
                if shortcode_match:
                    shortcode = shortcode_match.group(1)
                    if shortcode not in seen_shortcodes:
                        seen_shortcodes.add(shortcode)
                        
                        text = link_data.get('text', '')
                        hashtags = self._extract_hashtags(text)
                        mentioned = self._extract_mentions(text)
                        
                        reel = ReelData(
                            url=href,
                            shortcode=shortcode,
                            username=link_data.get('username', 'unknown'),
                            caption=link_data.get('caption', 'No caption'),
                            likes=link_data.get('likes', 0),
                            comments=link_data.get('comments', 0),
                            views=link_data.get('views', 0),
                            timestamp=datetime.now().isoformat(),
                            thumbnail_url=link_data.get('thumbnail', ''),
                            hashtags=hashtags,
                            mentioned_users=mentioned
                        )
                        reels.append(reel)
                        
                        if len(reels) >= max_results:
                            break
            
            logger.info(f"Found {len(reels)} reels for '{query}'")
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            
        return reels
    
    async def _extract_reel_links(self) -> List[Dict]:
        """Extract reel links with metadata from page"""
        return await self.page.evaluate('''
            () => {
                const links = [];
                const elements = document.querySelectorAll('a');
                
                elements.forEach(el => {
                    if (el.href && el.href.includes('instagram.com/reel/')) {
                        let parent = el.parentElement;
                        let container = el;
                        for (let i = 0; i < 5 && parent; i++) {
                            if (parent.textContent && parent.textContent.length > 30) {
                                container = parent;
                                break;
                            }
                            parent = parent.parentElement;
                        }
                        
                        const text = container.textContent || '';
                        const usernameMatch = text.match(/@([A-Za-z0-9_.]+)/);
                        const captionMatch = text.match(/@[A-Za-z0-9_.]+\\s*(.+?)(?=\\s*@|$)/);
                        
                        const extractNumber = (pattern) => {
                            const match = text.match(pattern);
                            if (!match) return 0;
                            let num = parseFloat(match[1]);
                            if (match[1].includes('K')) num *= 1000;
                            if (match[1].includes('M')) num *= 1000000;
                            return Math.round(num);
                        };
                        
                        const img = container.querySelector('img');
                        const thumbnail = img ? img.src : '';
                        
                        links.push({
                            href: el.href,
                            text: text,
                            username: usernameMatch ? usernameMatch[1] : '',
                            caption: captionMatch ? captionMatch[1].trim() : '',
                            likes: extractNumber(/([\\d.]+[KM]?)\\s*(?:likes|❤️|♥)/i),
                            comments: extractNumber(/([\\d.]+[KM]?)\\s*(?:comments|💬)/i),
                            views: extractNumber(/([\\d.]+[KM]?)\\s*(?:views|👁️)/i),
                            thumbnail: thumbnail
                        });
                    }
                });
                return links;
            }
        ''')
    
    def _normalize_query(self, query: str, search_type: str) -> str:
        """Normalize query based on search type"""
        query = query.strip()
        
        if search_type == "hashtag":
            if not query.startswith('#'):
                return f'#{query}'
            return query
        elif search_type == "username":
            if query.startswith('@'):
                return query[1:]
            return query
        else:  # auto
            if query.startswith('#'):
                return query[1:]
            elif query.startswith('@'):
                return query[1:]
            return query
    
    def _extract_hashtags(self, text: str) -> List[str]:
        """Extract hashtags from text"""
        return re.findall(r'#([A-Za-z0-9_]+)', text)
    
    def _extract_mentions(self, text: str) -> List[str]:
        """Extract mentioned users from text"""
        return re.findall(r'@([A-Za-z0-9_.]+)', text)


class DailyReelCollector:
    """Collects Reels daily for specified topics"""
    
    def __init__(self, scraper: UniversalReelsFinder):
        self.scraper = scraper
        self.topics = ["mafia", "gangstars", "murphy", "war", "ninjas"]
        self.reels_per_topic = 5
        self.collection_history: List[Dict] = []
        self.current_collection: Optional[DailyCollection] = None
        self.collection_file = "daily_reels.json"
        
    async def generate_daily_reels(self) -> DailyCollection:
        """Generate daily reel collection for all topics"""
        logger.info("Starting daily reel collection...")
        
        topic_reels = {}
        total_count = 0
        
        for topic in self.topics:
            logger.info(f"Collecting reels for: {topic}")
            
            # Search with variations to get unique results
            variations = [
                topic,
                f"#{topic}",
                f"{topic} daily",
                f"{topic} trending",
                f"best {topic}"
            ]
            
            all_reels = []
            seen_shortcodes = set()
            
            for variation in variations[:3]:  # Try first 3 variations
                if len(all_reels) >= self.reels_per_topic * 2:
                    break
                    
                try:
                    reels = await self.scraper.search(variation, max_results=20)
                    
                    for reel in reels:
                        if reel.shortcode not in seen_shortcodes:
                            seen_shortcodes.add(reel.shortcode)
                            # Check if reel is relevant to topic
                            if self._is_relevant(reel, topic):
                                all_reels.append(reel)
                except Exception as e:
                    logger.error(f"Error searching {variation}: {e}")
                    continue
                
                await asyncio.sleep(1)  # Rate limiting
            
            # Select the best/unique reels
            selected_reels = self._select_unique_reels(all_reels, self.reels_per_topic)
            topic_reels[topic] = selected_reels
            total_count += len(selected_reels)
            
            logger.info(f"Collected {len(selected_reels)} reels for {topic}")
        
        # Create daily collection
        self.current_collection = DailyCollection(
            date=datetime.now().strftime("%Y-%m-%d"),
            topics=topic_reels,
            total_count=total_count,
            generated_at=datetime.now().isoformat()
        )
        
        # Save to history
        self.collection_history.append(self.current_collection.to_dict())
        self._save_collection()
        
        logger.info(f"Daily collection complete: {total_count} total reels")
        return self.current_collection
    
    def _is_relevant(self, reel: ReelData, topic: str) -> bool:
        """Check if reel is relevant to the topic"""
        text = (reel.caption + ' ' + ' '.join(reel.hashtags)).lower()
        topic_lower = topic.lower()
        
        # Check for topic in caption or hashtags
        if topic_lower in text:
            return True
        
        # Check for related terms
        related_terms = {
            "mafia": ["crime", "gang", "criminal", "underworld"],
            "gangstars": ["gang", "star", "famous", "celebrity", "crew"],
            "murphy": ["murphy", "eddie", "comedian"],
            "war": ["battle", "fight", "conflict", "army", "soldier"],
            "ninjas": ["ninja", "martial", "warrior", "stealth", "samurai"]
        }
        
        for term in related_terms.get(topic_lower, []):
            if term in text:
                return True
        
        return False
    
    def _select_unique_reels(self, reels: List[ReelData], count: int) -> List[ReelData]:
        """Select unique and diverse reels"""
        if len(reels) <= count:
            return reels
        
        # Sort by engagement (likes + comments)
        sorted_reels = sorted(reels, key=lambda r: r.likes + r.comments, reverse=True)
        
        # Ensure diversity by selecting from different users
        selected = []
        used_users = set()
        
        for reel in sorted_reels:
            if reel.username not in used_users:
                selected.append(reel)
                used_users.add(reel.username)
                if len(selected) >= count:
                    break
        
        # If we need more, fill with remaining reels
        if len(selected) < count:
            remaining = [r for r in sorted_reels if r not in selected]
            selected.extend(remaining[:count - len(selected)])
        
        return selected[:count]
    
    def _save_collection(self):
        """Save collection to file"""
        data = {
            "history": self.collection_history,
            "current": self.current_collection.to_dict() if self.current_collection else None,
            "last_updated": datetime.now().isoformat()
        }
        
        with open(self.collection_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def load_collection(self):
        """Load collection from file"""
        if os.path.exists(self.collection_file):
            try:
                with open(self.collection_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.collection_history = data.get("history", [])
                logger.info(f"Loaded {len(self.collection_history)} historical collections")
            except Exception as e:
                logger.error(f"Error loading collection: {e}")
    
    def get_today_collection(self) -> Optional[DailyCollection]:
        """Get today's collection"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        if self.current_collection and self.current_collection.date == today:
            return self.current_collection
        
        # Check history
        for collection in self.collection_history:
            if collection.get("date") == today:
                # Reconstruct DailyCollection
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
        """Get reel URLs for a specific topic or all topics"""
        collection = self.get_today_collection()
        if not collection:
            return []
        
        if topic:
            reels = collection.topics.get(topic, [])
            return [reel.url for reel in reels]
        
        # Return all URLs
        all_urls = []
        for reels in collection.topics.values():
            all_urls.extend([reel.url for reel in reels])
        return all_urls


# Global instances
scraper = None
collector = None
scheduler = None

def create_scheduler():
    """Create and configure the scheduler"""
    global scheduler, collector
    
    scheduler = BackgroundScheduler()
    
    # Schedule daily at midnight
    scheduler.add_job(
        func=daily_collection_job,
        trigger=CronTrigger(hour=0, minute=0),
        id="daily_reel_collection",
        name="Daily Reel Collection",
        replace_existing=True
    )
    
    # Also run at startup to ensure we have data
    scheduler.add_job(
        func=daily_collection_job,
        trigger=CronTrigger(hour=0, minute=5),  # 5 minutes after midnight
        id="daily_collection_backup",
        replace_existing=True
    )
    
    return scheduler

async def daily_collection_job():
    """Background job to collect daily reels"""
    global collector, scraper
    
    logger.info("Running daily collection job...")
    
    try:
        # Ensure browser is initialized
        if not scraper.page:
            await scraper.initialize()
        
        collection = await collector.generate_daily_reels()
        logger.info(f"Daily collection completed: {collection.total_count} reels")
        
        # Print summary
        for topic, reels in collection.topics.items():
            logger.info(f"  {topic}: {len(reels)} reels")
            for reel in reels:
                logger.info(f"    - {reel.url}")
        
    except Exception as e:
        logger.error(f"Daily collection job failed: {e}")

@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    global scraper, collector, scheduler
    
    # Initialize scraper
    scraper = UniversalReelsFinder(headless=True)
    await scraper.initialize()
    logger.info("Universal Reels Finder initialized")
    
    # Initialize collector
    collector = DailyReelCollector(scraper)
    collector.load_collection()
    
    # Check if we already have today's collection
    today_collection = collector.get_today_collection()
    if not today_collection:
        logger.info("No collection for today, generating now...")
        await daily_collection_job()
    else:
        logger.info(f"Today's collection already exists: {today_collection.total_count} reels")
    
    # Start scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler started - daily collection at midnight")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global scraper, scheduler
    
    if scheduler:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
    
    if scraper:
        await scraper.close()
        logger.info("Scraper closed")

@app.get("/")
async def root():
    """Root endpoint - Dashboard"""
    global collector
    
    today_collection = collector.get_today_collection() if collector else None
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Daily Reel URL Generator</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                   max-width: 1200px; margin: 0 auto; padding: 20px; background: #0a0a0a; color: #fff; }
            .header { background: linear-gradient(135deg, #1a1a1a, #2a2a2a); padding: 30px; border-radius: 16px; margin-bottom: 30px; text-align: center; }
            h1 { font-size: 36px; color: #dc2743; margin-bottom: 10px; }
            .subtitle { color: #888; font-size: 16px; }
            .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
            .stat-card { background: #1a1a1a; padding: 20px; border-radius: 12px; text-align: center; border: 1px solid #333; }
            .stat-number { font-size: 28px; font-weight: bold; color: #dc2743; }
            .stat-label { color: #888; font-size: 14px; margin-top: 5px; }
            .section { background: #1a1a1a; padding: 25px; border-radius: 12px; margin-bottom: 20px; }
            .section h2 { color: #fff; margin-bottom: 15px; }
            .topic-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; }
            .topic-card { background: #2a2a2a; padding: 15px; border-radius: 10px; border-left: 4px solid #dc2743; }
            .topic-name { font-weight: bold; color: #dc2743; margin-bottom: 10px; }
            .reel-item { padding: 6px 0; border-bottom: 1px solid #333; font-size: 13px; }
            .reel-item:last-child { border-bottom: none; }
            .reel-url { color: #4ade80; word-break: break-all; text-decoration: none; }
            .reel-url:hover { text-decoration: underline; }
            .reel-meta { color: #888; font-size: 12px; }
            .btn { display: inline-block; padding: 10px 20px; background: #dc2743; color: #fff; 
                   border: none; border-radius: 8px; cursor: pointer; text-decoration: none; transition: all 0.3s; }
            .btn:hover { background: #bc1888; transform: translateY(-2px); }
            .footer { text-align: center; color: #666; font-size: 13px; margin-top: 30px; padding: 20px; border-top: 1px solid #333; }
            @media (max-width: 600px) {
                .topic-grid { grid-template-columns: 1fr; }
                .stats { grid-template-columns: 1fr 1fr; }
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🎬 Daily Reel URL Generator</h1>
            <p class="subtitle">Automatically generates 5 unique Reel URLs daily for your topics</p>
        </div>
    """
    
    if today_collection:
        # Stats
        total = today_collection.total_count
        topics_count = len(today_collection.topics)
        
        html += f"""
        <div class="stats">
            <div class="stat-card">
                <div class="stat-number">{total}</div>
                <div class="stat-label">Total Reels Today</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{topics_count}</div>
                <div class="stat-label">Topics</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{today_collection.date}</div>
                <div class="stat-label">Date</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">✅</div>
                <div class="stat-label">Status: Ready</div>
            </div>
        </div>
        """
        
        # Topics and Reels
        html += """
        <div class="section">
            <h2>📋 Today's Reels</h2>
            <div class="topic-grid">
        """
        
        for topic, reels in today_collection.topics.items():
            html += f"""
            <div class="topic-card">
                <div class="topic-name">#{topic} ({len(reels)} reels)</div>
            """
            
            for reel in reels:
                html += f"""
                <div class="reel-item">
                    <a href="{reel.url}" target="_blank" class="reel-url">📹 {reel.shortcode}</a>
                    <div class="reel-meta">@ {reel.username} • ❤️ {reel.likes} • 💬 {reel.comments}</div>
                </div>
                """
            
            html += "</div>"
        
        html += """
            </div>
        </div>
        """
    else:
        html += """
        <div class="section" style="text-align:center; padding: 40px;">
            <p style="color: #888; font-size: 18px;">⏳ No collection generated yet.</p>
            <p style="color: #666; margin-top: 10px;">The system will generate one at midnight.</p>
            <button onclick="generateNow()" class="btn" style="margin-top: 20px;">Generate Now</button>
        </div>
        <script>
            async function generateNow() {
                const response = await fetch('/generate/now', { method: 'POST' });
                if (response.ok) {
                    location.reload();
                }
            }
        </script>
        """
    
    html += f"""
        <div class="section">
            <h2>📖 API Endpoints</h2>
            <div style="background: #0a0a0a; padding: 15px; border-radius: 8px; font-family: monospace; color: #4ade80; overflow-x: auto;">
                GET /urls - Get all today's URLs<br>
                GET /urls/{collector.topics[0] if collector else 'topic'} - Get URLs for specific topic<br>
                GET /reels - Get full reel data (JSON)<br>
                GET /history - Get collection history<br>
                POST /generate - Force generate new collection
            </div>
        </div>
        
        <div class="section">
            <h2>🔗 Quick Access</h2>
            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                <a href="/urls" class="btn" style="background: #2a2a2a;">📥 All URLs</a>
                <a href="/reels" class="btn" style="background: #2a2a2a;">📊 Full Data</a>
                <a href="/history" class="btn" style="background: #2a2a2a;">📚 History</a>
            </div>
        </div>
        
        <div class="footer">
            Daily Reel URL Generator v3.0 | Powered by Playwright | Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
        
        <script>
            // Auto-refresh every 5 minutes
            setTimeout(() => location.reload(), 300000);
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(html)

@app.post("/generate")
@app.post("/generate/now")
async def generate_now(background_tasks: BackgroundTasks):
    """Force generate a new collection"""
    global collector
    
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    # Run in background
    background_tasks.add_task(daily_collection_job)
    
    return {
        "success": True,
        "message": "Generation started in background",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/urls")
async def get_urls(topic: Optional[str] = None):
    """Get all reel URLs for today"""
    global collector
    
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    urls = collector.get_reel_urls(topic)
    
    if topic:
        return {
            "topic": topic,
            "count": len(urls),
            "urls": urls,
            "date": datetime.now().strftime("%Y-%m-%d")
        }
    
    return {
        "count": len(urls),
        "urls": urls,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "topics": collector.topics
    }

@app.get("/reels")
async def get_reels():
    """Get all reel data for today"""
    global collector
    
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    collection = collector.get_today_collection()
    if not collection:
        return {
            "success": False,
            "message": "No collection for today",
            "date": datetime.now().strftime("%Y-%m-%d")
        }
    
    return {
        "success": True,
        "date": collection.date,
        "total_count": collection.total_count,
        "topics": {topic: [reel.to_dict() for reel in reels] for topic, reels in collection.topics.items()},
        "generated_at": collection.generated_at
    }

@app.get("/history")
async def get_history():
    """Get collection history"""
    global collector
    
    if not collector:
        raise HTTPException(status_code=503, detail="Collector not initialized")
    
    return {
        "total_collections": len(collector.collection_history),
        "history": collector.collection_history
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    global collector
    
    today_collection = collector.get_today_collection() if collector else None
    
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "Daily Reel URL Generator",
        "version": "3.0.0",
        "has_today_collection": today_collection is not None,
        "collection_date": today_collection.date if today_collection else None
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)