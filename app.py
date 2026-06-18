"""
Universal Reels Finder - Web Interface for Render Deployment
Search anything: hashtags, keywords, usernames, topics
"""

import asyncio
import re
import json
import logging
import sys
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from playwright.async_api import async_playwright, Page, Browser
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('reels_finder.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Universal Reels Finder API", version="2.0.0")

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
    profile_pic: str = ""
    is_video: bool = True
    duration: int = 0
    hashtags: List[str] = field(default_factory=list)
    mentioned_users: List[str] = field(default_factory=list)
    
    def to_dict(self):
        return asdict(self)


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
        """
        Universal search - handles any query type
        
        Args:
            query: Search term (hashtag, keyword, username, topic, etc.)
            max_results: Maximum number of results
            search_type: 'auto', 'hashtag', 'keyword', 'username', 'topic'
        """
        reels = []
        seen_shortcodes = set()
        
        try:
            # Normalize query
            query = query.strip()
            search_term = self._normalize_query(query, search_type)
            
            logger.info(f"Searching for: {search_term} (type: {search_type})")
            
            # Navigate to search
            await self.page.goto(f'{self.search_url}/#gsc.tab=0')
            await self.page.wait_for_load_state('networkidle')
            
            # Perform search
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
            for _ in range(min(5, max_results // 10 + 2)):
                await self.page.mouse.wheel(0, 500)
                await asyncio.sleep(1)
            
            # Extract all reel links with metadata
            links = await self._extract_reel_links()
            
            # Process links
            for link_data in links:
                href = link_data.get('href', '')
                shortcode_match = re.search(r'instagram\.com/reel/([A-Za-z0-9_-]+)', href)
                
                if shortcode_match:
                    shortcode = shortcode_match.group(1)
                    if shortcode not in seen_shortcodes:
                        seen_shortcodes.add(shortcode)
                        
                        # Extract metadata
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
            
            # If no results, try API fallback
            if not reels:
                logger.warning("No results found via scraping, trying API...")
                reels = await self._api_fallback(search_term, max_results)
            
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
                        // Find container
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
                        
                        // Extract username
                        const usernameMatch = text.match(/@([A-Za-z0-9_.]+)/);
                        
                        // Extract caption (everything after username)
                        const captionMatch = text.match(/@[A-Za-z0-9_.]+\s*(.+?)(?=\s*@|$)/);
                        
                        // Extract numbers with K/M suffixes
                        const extractNumber = (pattern) => {
                            const match = text.match(pattern);
                            if (!match) return 0;
                            let num = parseFloat(match[1]);
                            if (match[1].includes('K')) num *= 1000;
                            if (match[1].includes('M')) num *= 1000000;
                            return Math.round(num);
                        };
                        
                        // Extract thumbnail
                        const img = container.querySelector('img');
                        const thumbnail = img ? img.src : '';
                        
                        links.push({
                            href: el.href,
                            text: text,
                            username: usernameMatch ? usernameMatch[1] : '',
                            caption: captionMatch ? captionMatch[1].trim() : '',
                            likes: extractNumber(/([\\d.]+[KM]?)\s*(?:likes|❤️|♥)/i),
                            comments: extractNumber(/([\\d.]+[KM]?)\s*(?:comments|💬)/i),
                            views: extractNumber(/([\\d.]+[KM]?)\s*(?:views|👁️)/i),
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
            # Ensure hashtag format
            if not query.startswith('#'):
                return f'#{query}'
            return query
            
        elif search_type == "username":
            # Ensure username format
            if query.startswith('@'):
                return query[1:]
            return query
            
        elif search_type == "keyword":
            return query
            
        elif search_type == "topic":
            return query
            
        else:  # auto
            # Auto-detect
            if query.startswith('#'):
                return query[1:]  # Remove # for search
            elif query.startswith('@'):
                return query[1:]  # Remove @ for search
            return query
    
    def _extract_hashtags(self, text: str) -> List[str]:
        """Extract hashtags from text"""
        return re.findall(r'#([A-Za-z0-9_]+)', text)
    
    def _extract_mentions(self, text: str) -> List[str]:
        """Extract mentioned users from text"""
        return re.findall(r'@([A-Za-z0-9_.]+)', text)
    
    async def _api_fallback(self, query: str, max_results: int) -> List[ReelData]:
        """Fallback to API if scraping fails"""
        reels = []
        try:
            import requests
            response = requests.get(
                f"{self.search_url}/api/search",
                params={"q": query},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                for item in data.get('results', [])[:max_results]:
                    shortcode = item.get('shortcode') or item.get('id')
                    if shortcode:
                        reels.append(ReelData(
                            url=f"https://www.instagram.com/reel/{shortcode}/",
                            shortcode=shortcode,
                            username=item.get('username', 'unknown'),
                            caption=item.get('caption', ''),
                            likes=item.get('likes', 0),
                            comments=item.get('comments', 0),
                            views=item.get('views', 0),
                            timestamp=datetime.now().isoformat(),
                            thumbnail_url=item.get('thumbnail', '')
                        ))
        except Exception as e:
            logger.warning(f"API fallback failed: {e}")
        
        return reels


# Global scraper instance
scraper = None

@app.on_event("startup")
async def startup_event():
    """Initialize scraper on startup"""
    global scraper
    scraper = UniversalReelsFinder(headless=True)
    await scraper.initialize()
    logger.info("Universal Reels Finder initialized")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global scraper
    if scraper:
        await scraper.close()
        logger.info("Scraper closed")

@app.get("/")
async def root():
    """Root endpoint - HTML interface"""
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Universal Reels Finder</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                   max-width: 900px; margin: 0 auto; padding: 20px; background: #0a0a0a; color: #fff; min-height: 100vh; }
            .container { background: #1a1a1a; padding: 40px; border-radius: 16px; box-shadow: 0 8px 40px rgba(0,0,0,0.5); }
            h1 { font-size: 32px; color: #dc2743; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; }
            .subtitle { color: #888; margin-bottom: 30px; font-size: 16px; }
            .search-box { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
            input, select, button { padding: 14px 20px; border-radius: 10px; border: none; font-size: 16px; }
            input { flex: 1; min-width: 200px; background: #2a2a2a; color: #fff; }
            input::placeholder { color: #666; }
            select { background: #2a2a2a; color: #fff; cursor: pointer; }
            button { background: linear-gradient(135deg, #dc2743, #bc1888); color: #fff; cursor: pointer; font-weight: 600; 
                     transition: transform 0.2s; }
            button:hover { transform: translateY(-2px); }
            .type-badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; 
                          background: #2a2a2a; color: #888; margin: 5px 0; }
            .results { margin-top: 30px; }
            .result-card { background: #2a2a2a; padding: 20px; border-radius: 12px; margin-bottom: 12px; 
                           border-left: 4px solid #dc2743; transition: transform 0.2s; }
            .result-card:hover { transform: translateX(4px); }
            .url { color: #4ade80; word-break: break-all; font-size: 14px; }
            .meta { color: #888; font-size: 13px; margin-top: 8px; }
            .meta span { margin-right: 15px; }
            .caption { color: #ccc; margin-top: 8px; font-size: 14px; }
            .hashtags { color: #dc2743; font-size: 13px; margin-top: 6px; }
            .stats { display: flex; gap: 20px; margin-top: 10px; flex-wrap: wrap; }
            .stat { display: flex; align-items: center; gap: 4px; color: #888; font-size: 13px; }
            .endpoint-box { background: #0a0a0a; padding: 15px; border-radius: 8px; margin: 15px 0; 
                           font-family: monospace; color: #4ade80; overflow-x: auto; }
            .examples { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 20px 0; }
            .example-btn { padding: 10px 16px; background: #2a2a2a; border: 1px solid #333; border-radius: 8px; 
                           color: #fff; cursor: pointer; text-align: center; transition: all 0.2s; }
            .example-btn:hover { border-color: #dc2743; background: #333; }
            .loading { text-align: center; padding: 40px; color: #888; }
            .error { color: #ff4444; text-align: center; padding: 20px; }
            @media (max-width: 600px) {
                .container { padding: 20px; }
                .search-box { flex-direction: column; }
                .examples { grid-template-columns: 1fr 1fr; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎬 Universal Reels Finder</h1>
            <p class="subtitle">Search anything: hashtags, keywords, topics, usernames</p>
            
            <div class="search-box">
                <input type="text" id="searchInput" placeholder="Search anything... (e.g., nature, #travel, @user)" value="nature">
                <select id="searchType">
                    <option value="auto">Auto Detect</option>
                    <option value="hashtag">Hashtag</option>
                    <option value="keyword">Keyword</option>
                    <option value="username">Username</option>
                    <option value="topic">Topic</option>
                </select>
                <button onclick="searchReels()">🔍 Search</button>
            </div>
            
            <div class="examples">
                <div class="example-btn" onclick="quickSearch('nature')">🌿 Nature</div>
                <div class="example-btn" onclick="quickSearch('travel')">✈️ Travel</div>
                <div class="example-btn" onclick="quickSearch('food')">🍕 Food</div>
                <div class="example-btn" onclick="quickSearch('fitness')">💪 Fitness</div>
                <div class="example-btn" onclick="quickSearch('music')">🎵 Music</div>
                <div class="example-btn" onclick="quickSearch('#photography')">📸 Photography</div>
            </div>
            
            <div id="results"></div>
            
            <div style="margin-top: 30px; border-top: 1px solid #333; padding-top: 20px;">
                <h3>📖 API Endpoint</h3>
                <div class="endpoint-box">GET /search?q=QUERY&max=30&type=auto</div>
                <p style="color: #888; font-size: 13px;">Try: <a href="/search?q=nature&max=10" target="_blank" style="color: #4ade80;">/search?q=nature&max=10</a></p>
            </div>
        </div>
        
        <script>
            async function searchReels() {
                const query = document.getElementById('searchInput').value.trim();
                const type = document.getElementById('searchType').value;
                if (!query) return;
                
                const resultsDiv = document.getElementById('results');
                resultsDiv.innerHTML = '<div class="loading">🔍 Searching...</div>';
                
                try {
                    const response = await fetch(`/search?q=${encodeURIComponent(query)}&max=30&type=${type}`);
                    const data = await response.json();
                    
                    if (data.error) {
                        resultsDiv.innerHTML = `<div class="error">❌ ${data.error}</div>`;
                        return;
                    }
                    
                    if (data.reels && data.reels.length > 0) {
                        let html = `<div style="margin-bottom: 15px; color: #888;">Found <strong style="color: #fff;">${data.count}</strong> reels for "<strong style="color: #fff;">${data.query}</strong>"</div>`;
                        data.reels.forEach((reel, index) => {
                            const hashtags = reel.hashtags ? reel.hashtags.map(h => `#${h}`).join(' ') : '';
                            html += `
                                <div class="result-card">
                                    <div><strong style="color: #dc2743;">#${index + 1}</strong></div>
                                    <div class="url">${reel.url}</div>
                                    <div class="meta">
                                        <span>👤 @${reel.username}</span>
                                        <span>❤️ ${reel.likes}</span>
                                        <span>💬 ${reel.comments}</span>
                                        <span>👁️ ${reel.views}</span>
                                    </div>
                                    ${reel.caption && reel.caption !== 'No caption' ? `<div class="caption">${reel.caption.substring(0, 150)}${reel.caption.length > 150 ? '...' : ''}</div>` : ''}
                                    ${hashtags ? `<div class="hashtags">${hashtags}</div>` : ''}
                                    <div class="stats">
                                        <span class="stat">📅 ${new Date(reel.timestamp).toLocaleDateString()}</span>
                                        ${reel.mentioned_users && reel.mentioned_users.length > 0 ? `<span class="stat">👥 ${reel.mentioned_users.length} mentions</span>` : ''}
                                    </div>
                                </div>
                            `;
                        });
                        resultsDiv.innerHTML = html;
                    } else {
                        resultsDiv.innerHTML = '<div style="text-align:center; padding:40px; color:#888;">😕 No reels found. Try a different search term.</div>';
                    }
                } catch (error) {
                    resultsDiv.innerHTML = `<div class="error">❌ Error searching: ${error.message}</div>`;
                }
            }
            
            function quickSearch(query) {
                document.getElementById('searchInput').value = query;
                searchReels();
            }
            
            // Search on Enter key
            document.getElementById('searchInput').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') searchReels();
            });
            
            // Auto-search on load
            window.onload = function() {
                setTimeout(searchReels, 500);
            };
        </script>
    </body>
    </html>
    """)

@app.get("/search")
async def search_reels(
    q: str = Query(..., description="Search query (any text, hashtag, username)"),
    max: int = Query(30, description="Maximum results", ge=1, le=100),
    type: str = Query("auto", description="Search type: auto, hashtag, keyword, username, topic")
):
    """Universal search endpoint - search anything"""
    global scraper
    
    if not scraper:
        raise HTTPException(status_code=503, detail="Scraper not initialized")
    
    if len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Search query must be at least 2 characters")
    
    try:
        reels = await scraper.search(q, max_results=max, search_type=type)
        
        return {
            "success": True,
            "query": q,
            "search_type": type,
            "count": len(reels),
            "reels": [reel.to_dict() for reel in reels],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "Universal Reels Finder API",
        "version": "2.0.0"
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)