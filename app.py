"""
Reels URL Extractor - Web Interface for Render Deployment
Runs as a web service with API endpoints
"""

import asyncio
import re
import json
import logging
import sys
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
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

app = FastAPI(title="Reels Finder API", version="1.0.0")

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
    thumbnail_url: str
    profile_pic: str = ""
    is_video: bool = True
    duration: int = 0
    
    def to_dict(self):
        return asdict(self)


class ReelsFinderPlaywright:
    """Extracts Reel URLs using Playwright automation"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser = None
        self.page = None
        self.playwright = None
        
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
    
    async def search_reels(self, query: str, max_results: int = 50) -> List[ReelData]:
        """Search for reels and extract URLs with metadata"""
        reels = []
        seen_shortcodes = set()
        
        try:
            logger.info(f"Searching for: {query}")
            
            await self.page.goto('https://reelsfinder.satishyadav.com/#gsc.tab=0')
            await self.page.wait_for_load_state('networkidle')
            
            try:
                await self.page.wait_for_selector('#gsc-i-id1', timeout=10000)
                await self.page.click('#gsc-i-id1')
                await self.page.fill('#gsc-i-id1', query)
                
                await self.page.press('#gsc-i-id1', 'Enter')
                await self.page.wait_for_load_state('networkidle')
                
            except Exception as e:
                logger.error(f"Search input error: {e}")
                await self.page.goto(f'https://reelsfinder.satishyadav.com/#gsc.tab=0&gsc.q={query}')
                await self.page.wait_for_load_state('networkidle')
            
            await asyncio.sleep(2)
            
            # Scroll to load more results
            for _ in range(5):
                await self.page.mouse.wheel(0, 500)
                await asyncio.sleep(1)
            
            # Extract links with metadata
            links = await self.page.evaluate('''
                () => {
                    const links = [];
                    const elements = document.querySelectorAll('a');
                    elements.forEach(el => {
                        if (el.href && el.href.includes('instagram.com/reel/')) {
                            let parent = el.parentElement;
                            let container = el;
                            for (let i = 0; i < 5 && parent; i++) {
                                if (parent.textContent && parent.textContent.length > 50) {
                                    container = parent;
                                    break;
                                }
                                parent = parent.parentElement;
                            }
                            
                            const text = container.textContent || '';
                            const usernameMatch = text.match(/@([A-Za-z0-9_.]+)/);
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
                            
                            links.push({
                                href: el.href,
                                text: text,
                                username: usernameMatch ? usernameMatch[1] : '',
                                caption: captionMatch ? captionMatch[1].trim() : '',
                                likes: extractNumber(/([\\d.]+[KM]?)\s*(?:likes|❤️|♥)/i),
                                comments: extractNumber(/([\\d.]+[KM]?)\s*(?:comments|💬)/i),
                                views: extractNumber(/([\\d.]+[KM]?)\s*(?:views|👁️)/i)
                            });
                        }
                    });
                    return links;
                }
            ''')
            
            for link_data in links:
                href = link_data.get('href', '')
                shortcode_match = re.search(r'instagram\.com/reel/([A-Za-z0-9_-]+)', href)
                
                if shortcode_match:
                    shortcode = shortcode_match.group(1)
                    if shortcode not in seen_shortcodes:
                        seen_shortcodes.add(shortcode)
                        
                        reel = ReelData(
                            url=href,
                            shortcode=shortcode,
                            username=link_data.get('username', 'unknown'),
                            caption=link_data.get('caption', 'No caption'),
                            likes=link_data.get('likes', 0),
                            comments=link_data.get('comments', 0),
                            views=link_data.get('views', 0),
                            timestamp=datetime.now().isoformat(),
                            thumbnail_url="",
                            profile_pic="",
                            is_video=True,
                            duration=0
                        )
                        reels.append(reel)
                        
                        if len(reels) >= max_results:
                            break
            
            logger.info(f"Captured {len(reels)} reels")
            
        except Exception as e:
            logger.error(f"Error during search: {e}")
            
        return reels


# Global scraper instance
scraper = None

@app.on_event("startup")
async def startup_event():
    """Initialize scraper on startup"""
    global scraper
    scraper = ReelsFinderPlaywright(headless=True)
    await scraper.initialize()
    logger.info("Scraper initialized")

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
        <title>Reels Finder API</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; background: #0a0a0a; color: #fff; }
            .container { background: #1a1a1a; padding: 30px; border-radius: 12px; }
            h1 { color: #dc2743; }
            input, button { padding: 12px; margin: 10px 0; border-radius: 8px; border: none; }
            input { width: 70%; background: #2a2a2a; color: #fff; }
            button { background: #dc2743; color: #fff; cursor: pointer; font-weight: bold; }
            button:hover { background: #bc1888; }
            .result { background: #2a2a2a; padding: 15px; margin: 10px 0; border-radius: 8px; }
            .url { color: #4ade80; word-break: break-all; }
            .meta { color: #888; font-size: 14px; }
            .endpoint { background: #2a2a2a; padding: 10px; border-radius: 6px; margin: 10px 0; font-family: monospace; }
            a { color: #dc2743; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎬 Reels Finder API</h1>
            <p>Search and extract Instagram Reel URLs</p>
            
            <h3>📖 API Endpoints</h3>
            <div class="endpoint">
                <strong>GET</strong> /search?q=query&max=30
            </div>
            
            <h3>🔍 Try It Now</h3>
            <input type="text" id="searchInput" placeholder="Enter hashtag or keyword..." value="nature">
            <button onclick="searchReels()">Search Reels</button>
            
            <div id="results"></div>
            
            <h3>📊 Example Usage</h3>
            <div class="endpoint">
                <a href="/search?q=nature&max=10" target="_blank">/search?q=nature&max=10</a>
            </div>
        </div>
        
        <script>
            async function searchReels() {
                const query = document.getElementById('searchInput').value;
                if (!query) return;
                
                const resultsDiv = document.getElementById('results');
                resultsDiv.innerHTML = '<p>Searching...</p>';
                
                try {
                    const response = await fetch(`/search?q=${encodeURIComponent(query)}&max=20`);
                    const data = await response.json();
                    
                    if (data.reels && data.reels.length > 0) {
                        let html = `<h3>✅ Found ${data.count} reels</h3>`;
                        data.reels.forEach((reel, index) => {
                            html += `
                                <div class="result">
                                    <div><strong>#${index + 1}</strong></div>
                                    <div class="url">${reel.url}</div>
                                    <div class="meta">
                                        @${reel.username} • ❤️ ${reel.likes} • 💬 ${reel.comments} • 👁️ ${reel.views}
                                    </div>
                                    <div class="meta">${reel.caption.substring(0, 100)}...</div>
                                </div>
                            `;
                        });
                        resultsDiv.innerHTML = html;
                    } else {
                        resultsDiv.innerHTML = '<p>No reels found</p>';
                    }
                } catch (error) {
                    resultsDiv.innerHTML = '<p>Error searching</p>';
                }
            }
        </script>
    </body>
    </html>
    """)

@app.get("/search")
async def search_reels(
    q: str = Query(..., description="Search query (hashtag, keyword, or username)"),
    max: int = Query(30, description="Maximum results", ge=1, le=100)
):
    """Search for reels and return results"""
    global scraper
    
    if not scraper:
        raise HTTPException(status_code=503, detail="Scraper not initialized")
    
    try:
        reels = await scraper.search_reels(q, max_results=max)
        
        return {
            "success": True,
            "query": q,
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
        "service": "Reels Finder API"
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)