# integrations/web_browser.py - Web Browsing and Search
"""
Web browsing capabilities for Zeilus.
Includes headless browser control and web search.
"""

import logging
import re
import json
import time
from typing import Dict, List, Optional, Any
from pathlib import Path
from urllib.parse import urlencode, quote_plus

# HTTP requests
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    logging.warning("httpx not installed. Some web features disabled.")

# DuckDuckGo search
try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False
    logging.warning("duckduckgo-search not installed. Web search disabled.")

# Playwright for browser automation
try:
    from playwright.sync_api import sync_playwright, Page, Browser
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    logging.warning("playwright not installed. Browser automation disabled.")

logger = logging.getLogger(__name__)


# =============================================================================
# WEB BROWSER
# =============================================================================

class WebBrowser:
    """
    Headless web browser for surfing, searching, and automation.
    """
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._playwright = None
        
        # Screenshot directory
        self._screenshot_dir = Path("screenshots")
        self._screenshot_dir.mkdir(exist_ok=True)
        
        logger.info("WebBrowser initialized")
    
    # -------------------------------------------------------------------------
    # Browser Management
    # -------------------------------------------------------------------------
    
    def start(self) -> bool:
        """Start the browser."""
        if not HAS_PLAYWRIGHT:
            logger.error("Playwright not installed")
            return False
        
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self.headless)
            self._page = self._browser.new_page()
            logger.info("Browser started")
            return True
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            return False
    
    def stop(self):
        """Stop the browser."""
        try:
            if self._page:
                self._page.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
            logger.info("Browser stopped")
        except Exception as e:
            logger.debug(f"Browser stop error: {e}")
    
    def _ensure_browser(self) -> bool:
        """Ensure browser is running."""
        if not self._browser or not self._page:
            return self.start()
        return True
    
    # -------------------------------------------------------------------------
    # Navigation
    # -------------------------------------------------------------------------
    
    def goto(self, url: str, wait_for: str = "domcontentloaded") -> Dict[str, Any]:
        """
        Navigate to a URL.
        
        Args:
            url: URL to navigate to
            wait_for: Wait condition ('domcontentloaded', 'load', 'networkidle')
        """
        if not self._ensure_browser():
            return {"success": False, "error": "Browser not available"}
        
        try:
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            response = self._page.goto(url, wait_until=wait_for)
            
            return {
                "success": True,
                "url": self._page.url,
                "title": self._page.title(),
                "status": response.status if response else None
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_current_url(self) -> str:
        """Get current page URL."""
        if self._page:
            return self._page.url
        return ""
    
    def get_title(self) -> str:
        """Get current page title."""
        if self._page:
            return self._page.title()
        return ""
    
    def go_back(self) -> Dict[str, Any]:
        """Go back in history."""
        if not self._page:
            return {"success": False, "error": "No page"}
        try:
            self._page.go_back()
            return {"success": True, "url": self._page.url}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def go_forward(self) -> Dict[str, Any]:
        """Go forward in history."""
        if not self._page:
            return {"success": False, "error": "No page"}
        try:
            self._page.go_forward()
            return {"success": True, "url": self._page.url}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def refresh(self) -> Dict[str, Any]:
        """Refresh current page."""
        if not self._page:
            return {"success": False, "error": "No page"}
        try:
            self._page.reload()
            return {"success": True, "url": self._page.url}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # Content Extraction
    # -------------------------------------------------------------------------
    
    def get_text(self, selector: str = "body") -> str:
        """Get text content from page or element."""
        if not self._page:
            return ""
        try:
            element = self._page.query_selector(selector)
            if element:
                return element.inner_text()
            return ""
        except Exception as e:
            logger.error(f"Get text error: {e}")
            return ""
    
    def get_html(self, selector: str = "html") -> str:
        """Get HTML content from page or element."""
        if not self._page:
            return ""
        try:
            element = self._page.query_selector(selector)
            if element:
                return element.inner_html()
            return ""
        except Exception as e:
            logger.error(f"Get HTML error: {e}")
            return ""
    
    def get_page_content(self, url: str = None) -> Dict[str, Any]:
        """
        Get structured content from a page.
        
        Returns:
            Dict with title, text, links, etc.
        """
        if url:
            result = self.goto(url)
            if not result.get("success"):
                return result
        
        if not self._page:
            return {"error": "No page loaded"}
        
        try:
            # Extract content
            title = self._page.title()
            
            # Get main text (try article, main, or body)
            text = ""
            for selector in ["article", "main", "[role='main']", "body"]:
                text = self.get_text(selector)
                if text and len(text) > 100:
                    break
            
            # Get links
            links = []
            link_elements = self._page.query_selector_all("a[href]")
            for el in link_elements[:20]:  # Limit to 20 links
                href = el.get_attribute("href")
                link_text = el.inner_text().strip()
                if href and link_text:
                    links.append({"text": link_text[:50], "href": href})
            
            # Get headings
            headings = []
            for tag in ["h1", "h2", "h3"]:
                for el in self._page.query_selector_all(tag)[:5]:
                    headings.append(el.inner_text().strip())
            
            return {
                "success": True,
                "url": self._page.url,
                "title": title,
                "headings": headings,
                "text": text[:5000],  # Limit text length
                "links": links
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # Screenshots
    # -------------------------------------------------------------------------
    
    def screenshot(self, filename: str = None, full_page: bool = False) -> Dict[str, Any]:
        """Take a screenshot of the page."""
        if not self._page:
            return {"success": False, "error": "No page"}
        
        try:
            if not filename:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"web_screenshot_{timestamp}.png"
            
            filepath = self._screenshot_dir / filename
            self._page.screenshot(path=str(filepath), full_page=full_page)
            
            return {"success": True, "path": str(filepath)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # Interactions
    # -------------------------------------------------------------------------
    
    def click(self, selector: str) -> Dict[str, Any]:
        """Click an element."""
        if not self._page:
            return {"success": False, "error": "No page"}
        try:
            self._page.click(selector)
            return {"success": True, "selector": selector}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def type_text(self, selector: str, text: str) -> Dict[str, Any]:
        """Type text into an element."""
        if not self._page:
            return {"success": False, "error": "No page"}
        try:
            self._page.fill(selector, text)
            return {"success": True, "selector": selector, "text_length": len(text)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def press_key(self, key: str) -> Dict[str, Any]:
        """Press a keyboard key."""
        if not self._page:
            return {"success": False, "error": "No page"}
        try:
            self._page.keyboard.press(key)
            return {"success": True, "key": key}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def scroll(self, direction: str = "down", amount: int = 500) -> Dict[str, Any]:
        """Scroll the page."""
        if not self._page:
            return {"success": False, "error": "No page"}
        try:
            if direction == "down":
                self._page.evaluate(f"window.scrollBy(0, {amount})")
            elif direction == "up":
                self._page.evaluate(f"window.scrollBy(0, -{amount})")
            elif direction == "top":
                self._page.evaluate("window.scrollTo(0, 0)")
            elif direction == "bottom":
                self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            return {"success": True, "direction": direction}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def fill_form(self, form_data: Dict[str, str], submit_selector: str = None) -> Dict[str, Any]:
        """
        Fill a form with data.
        
        Args:
            form_data: Dict mapping selectors to values
            submit_selector: Optional selector for submit button
        """
        if not self._page:
            return {"success": False, "error": "No page"}
        
        try:
            for selector, value in form_data.items():
                self._page.fill(selector, value)
            
            if submit_selector:
                self._page.click(submit_selector)
                self._page.wait_for_load_state("domcontentloaded")
            
            return {"success": True, "fields_filled": len(form_data)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # Wait
    # -------------------------------------------------------------------------
    
    def wait_for_selector(self, selector: str, timeout: int = 10000) -> Dict[str, Any]:
        """Wait for an element to appear."""
        if not self._page:
            return {"success": False, "error": "No page"}
        try:
            self._page.wait_for_selector(selector, timeout=timeout)
            return {"success": True, "selector": selector}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def wait_for_navigation(self, timeout: int = 30000) -> Dict[str, Any]:
        """Wait for navigation to complete."""
        if not self._page:
            return {"success": False, "error": "No page"}
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=timeout)
            return {"success": True, "url": self._page.url}
        except Exception as e:
            return {"success": False, "error": str(e)}


# =============================================================================
# WEB SEARCH (No browser needed)
# =============================================================================

class WebSearch:
    """Web search without browser using DuckDuckGo."""
    
    @staticmethod
    def search(query: str, max_results: int = 10) -> List[Dict]:
        """
        Search the web using DuckDuckGo.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            List of results with title, link, snippet
        """
        if not HAS_DDGS:
            return [{"error": "duckduckgo-search not installed"}]
        
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
                
                return [
                    {
                        "title": r.get("title", ""),
                        "link": r.get("href", r.get("link", "")),
                        "snippet": r.get("body", r.get("snippet", ""))
                    }
                    for r in results
                ]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return [{"error": str(e)}]
    
    @staticmethod
    def search_news(query: str, max_results: int = 10) -> List[Dict]:
        """Search news articles."""
        if not HAS_DDGS:
            return [{"error": "duckduckgo-search not installed"}]
        
        try:
            with DDGS() as ddgs:
                results = list(ddgs.news(query, max_results=max_results))
                return [
                    {
                        "title": r.get("title", ""),
                        "link": r.get("url", ""),
                        "source": r.get("source", ""),
                        "date": r.get("date", ""),
                        "snippet": r.get("body", "")
                    }
                    for r in results
                ]
        except Exception as e:
            return [{"error": str(e)}]
    
    @staticmethod
    def search_images(query: str, max_results: int = 10) -> List[Dict]:
        """Search for images."""
        if not HAS_DDGS:
            return [{"error": "duckduckgo-search not installed"}]
        
        try:
            with DDGS() as ddgs:
                results = list(ddgs.images(query, max_results=max_results))
                return [
                    {
                        "title": r.get("title", ""),
                        "image": r.get("image", ""),
                        "thumbnail": r.get("thumbnail", ""),
                        "source": r.get("source", "")
                    }
                    for r in results
                ]
        except Exception as e:
            return [{"error": str(e)}]


# =============================================================================
# SIMPLE PAGE FETCHER (No browser)
# =============================================================================

class PageFetcher:
    """Fetch web pages without a full browser."""
    
    @staticmethod
    def fetch(url: str, timeout: int = 10) -> Dict[str, Any]:
        """
        Fetch a web page and extract text.
        
        Args:
            url: URL to fetch
            timeout: Request timeout in seconds
        """
        if not HAS_HTTPX:
            return {"error": "httpx not installed"}
        
        try:
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.get(url, headers=headers)
                
                content_type = response.headers.get("content-type", "")
                
                if "text/html" in content_type:
                    # Parse HTML
                    html = response.text
                    text = PageFetcher._html_to_text(html)
                    title = PageFetcher._extract_title(html)
                    
                    return {
                        "success": True,
                        "url": str(response.url),
                        "title": title,
                        "text": text[:10000],  # Limit
                        "status": response.status_code
                    }
                else:
                    return {
                        "success": True,
                        "url": str(response.url),
                        "content_type": content_type,
                        "status": response.status_code
                    }
                    
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert HTML to plain text."""
        # Remove script and style elements
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        
        # Remove tags
        text = re.sub(r'<[^>]+>', ' ', html)
        
        # Decode entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    @staticmethod
    def _extract_title(html: str) -> str:
        """Extract title from HTML."""
        match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def web_search(query: str, max_results: int = 10) -> List[Dict]:
    """Quick web search."""
    return WebSearch.search(query, max_results)


def fetch_page(url: str) -> Dict[str, Any]:
    """Quick page fetch."""
    return PageFetcher.fetch(url)


def browse_url(url: str) -> Dict[str, Any]:
    """Browse a URL with full browser and get content."""
    browser = WebBrowser(headless=True)
    try:
        if browser.start():
            return browser.get_page_content(url)
        return {"error": "Failed to start browser"}
    finally:
        browser.stop()
