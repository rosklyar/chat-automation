"""Citation extraction from ChatGPT responses."""

import logging
import re
from typing import Optional
from playwright.sync_api import Page, Locator

from ..models import Citation

logger = logging.getLogger(__name__)


class CitationExtractor:
    """
    Extracts citations/sources from ChatGPT responses.

    Uses multiple strategies to locate and parse citations:
    1. Click "Sources/Джерела" button to open panel
    2. Find citations panel (avoiding navigation sidebar)
    3. Extract links and metadata from citations
    """

    SOURCES_BUTTON_LABELS = ["Sources", "Джерела"]

    def extract(self, page: Page) -> list[Citation]:
        """
        Extract citations from current ChatGPT response.

        Args:
            page: Playwright page object

        Returns:
            List of Citation objects (may be empty)
        """
        citations = []

        try:
            # Find sources button
            sources_button = self._find_sources_button(page)
            if not sources_button:
                return citations

            # Count asides before clicking
            asides_before = page.locator('aside').count()

            # Click to open panel
            sources_button.click()
            page.wait_for_timeout(3000)

            # Find citations panel
            panel = self._find_citations_panel(page, asides_before)
            if not panel:
                self._close_panel(page)
                return citations

            # Wait for panel content
            try:
                panel.locator('a').first.wait_for(state="visible", timeout=5000)
            except Exception:
                page.wait_for_timeout(2000)

            # Extract citations
            citations = self._extract_from_panel(panel, page)

            # Close panel
            self._close_panel(page)

            if not citations:
                logger.warning("No sources extracted")

        except Exception as e:
            logger.error(f"Source extraction error: {e}")
            self._close_panel(page)

        return citations

    def _find_sources_button(self, page: Page) -> Optional[Locator]:
        """Find the sources button."""
        # Try by role with label
        for label in self.SOURCES_BUTTON_LABELS:
            try:
                btn = page.get_by_role("button", name=label)
                if btn.count() > 0:
                    return btn
            except Exception:
                pass

        # Fallback: text search
        try:
            btn = page.locator('button:has-text("Джерела"), button:has-text("Sources")').last
            if btn.count() > 0:
                return btn
        except Exception:
            pass

        return None

    def _find_citations_panel(self, page: Page, asides_before: int) -> Optional[Locator]:
        """Find the citations panel (not navigation sidebar)."""
        panel = None

        # Strategy 1: Look for container by structure
        panel = self._find_by_css_structure(page)
        if panel:
            return panel

        # Strategy 2: Look for container with citation header + links
        panel = self._find_by_content_structure(page)
        if panel:
            return panel

        # Strategy 3: Look for new aside on right side
        try:
            page.wait_for_function(
                f'document.querySelectorAll("aside").length > {asides_before}',
                timeout=5000
            )
        except Exception:
            pass

        # Search asides for citations panel
        asides = page.locator('aside').all()

        for idx, aside in enumerate(asides):
            try:
                box = aside.bounding_box()
                text = aside.inner_text()

                # Skip navigation sidebar
                if "New chat" in text or "Library" in text:
                    continue

                # Check HTML for navigation elements
                try:
                    html = aside.inner_html()
                    if "create-new-chat-button" in html or "sidebar-item-library" in html:
                        continue
                except Exception:
                    pass

                # Citations panel is on right side (x > 600)
                if box and box['x'] > 600 and len(text) > 50:
                    # Verify it has citation-like content
                    has_citations = (
                        "Citations" in text or
                        "Цитування" in text or
                        "http" in text or
                        len(text) > 100
                    )
                    if has_citations:
                        return aside

            except Exception:
                continue

        # Fallback: use last aside if not navigation
        if len(asides) > 0:
            last_aside = asides[-1]
            try:
                text_check = last_aside.inner_text()
                if "New chat" not in text_check:
                    return last_aside
            except Exception:
                pass

        return None

    def _find_by_css_structure(self, page: Page) -> Optional[Locator]:
        """Find citations container by specific CSS classes."""
        try:
            containers = page.locator('div.bg-token-bg-primary.flex.w-full.flex-col').all()
            for container in containers:
                text = container.inner_text()
                if any(header in text for header in ["Цитати", "Citations", "Джерела", "Цитування"]):
                    links_count = container.locator('a[target="_blank"][href^="http"]').count()
                    if links_count >= 2:
                        return container
        except Exception:
            pass
        return None

    def _find_by_content_structure(self, page: Page) -> Optional[Locator]:
        """Find container with citation header and multiple external links."""
        try:
            all_divs = page.locator('div').all()
            for div in all_divs:
                try:
                    text = div.inner_text()
                    has_citation_header = any(h in text for h in ["Цитати", "Citations", "Джерела", "Цитування"])

                    if has_citation_header:
                        links_count = div.locator('a[target="_blank"][href^="http"]').count()
                        if links_count >= 2:
                            return div
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _extract_from_panel(self, panel: Locator, page: Page) -> list[Citation]:
        """Extract citations from the panel using multiple strategies."""
        citations = []

        # Strategy 0: Direct ul > li > a structure
        citations = self._extract_from_list_structure(panel)
        if citations:
            return citations

        # Strategy 1-8: Various link selectors
        link_strategies = [
            ('a[href^="http"]', "href starts with http"),
            ('a[target="_blank"]', "target=_blank"),
            ('a[href*="utm_source=chatgpt"]', "chatgpt utm"),
            ('ul a[href^="http"]', "ul links"),
            ('a[href]', "any href"),
            ('a', "all links"),
            ('li a, [role="listitem"] a', "list item links"),
            ('[href], [role="link"]', "href or role=link"),
        ]

        for selector, name in link_strategies:
            try:
                links = panel.locator(selector).all()
                if links:
                    citations = self._parse_links(links)
                    if citations:
                        return citations
            except Exception:
                continue

        # Strategy 9: Manual text parsing as last resort
        citations = self._extract_from_text(panel)

        return citations

    def _extract_from_list_structure(self, panel: Locator) -> list[Citation]:
        """Extract from ul > li > a structure."""
        citations = []

        try:
            # Try various link patterns
            link_patterns = [
                'ul > li > a[href^="http"]',
                'a[target="_blank"]',
                'a[href*="utm_source=chatgpt"]',
                'ul a[href^="http"]',
            ]

            links = []
            for pattern in link_patterns:
                links = panel.locator(pattern).all()
                if links:
                    break

            if not links:
                return citations

            for idx, link in enumerate(links, 1):
                try:
                    url = link.get_attribute('href') or ""

                    # Get text from nested divs
                    divs = link.locator('div').all()
                    text_parts = []

                    for div in divs:
                        try:
                            text = div.inner_text().strip()
                            if text and not text.startswith('http') and len(text) > 1:
                                text_parts.append(text)
                        except Exception:
                            continue

                    # Build citation text
                    name = text_parts[0] if len(text_parts) > 0 else f"Source {idx}"
                    title = text_parts[1] if len(text_parts) > 1 else ""
                    description = text_parts[2] if len(text_parts) > 2 else ""

                    # Combine into text
                    text_combined = " - ".join(filter(None, [name, title, description]))
                    if not text_combined:
                        text_combined = f"Source {idx}"

                    citations.append(Citation(url=url, text=text_combined, number=idx))

                except Exception:
                    pass

        except Exception:
            pass

        return citations

    def _parse_links(self, links: list[Locator]) -> list[Citation]:
        """Parse a list of link elements into citations."""
        citations = []

        for idx, link in enumerate(links, 1):
            try:
                url = link.get_attribute('href') or ""

                # Handle relative URLs
                if url and not url.startswith('http'):
                    if url.startswith('/'):
                        url = f"https://chatgpt.com{url}"

                text = link.inner_text().strip()

                # Extract name from first line
                lines = text.split('\n')
                name = lines[0] if lines else text[:100]

                if len(name) > 100:
                    name = name[:97] + "..."

                citations.append(Citation(url=url, text=name, number=idx))

            except Exception:
                continue

        return citations

    def _extract_from_text(self, panel: Locator) -> list[Citation]:
        """Fallback: extract citations by parsing panel text."""
        citations = []

        try:
            panel_text = panel.inner_text()

            # Find URLs in text
            urls = re.findall(r'https?://[^\s\)]+', panel_text)

            # Parse structured entries
            lines = panel_text.split('\n')
            current_citation = {}
            citations_parsed = []

            for line in lines:
                line = line.strip()
                if not line:
                    if current_citation and 'name' in current_citation:
                        citations_parsed.append(current_citation)
                        current_citation = {}
                    continue

                # Check if line contains a URL
                if 'http' in line:
                    url_match = re.search(r'https?://[^\s\)]+', line)
                    if url_match:
                        if 'url' not in current_citation:
                            current_citation['url'] = url_match.group()
                        text_without_url = line.replace(url_match.group(), '').strip()
                        if text_without_url and 'description' not in current_citation:
                            current_citation['description'] = text_without_url
                else:
                    # Short lines are likely names
                    if len(line) < 50 and 'name' not in current_citation:
                        current_citation['name'] = line
                    else:
                        if 'description' not in current_citation:
                            current_citation['description'] = line
                        else:
                            current_citation['description'] += ' ' + line

            # Add last citation
            if current_citation and 'name' in current_citation:
                citations_parsed.append(current_citation)


            # Create Citation objects
            for idx, citation_data in enumerate(citations_parsed, 1):
                name = citation_data.get('name', f'Source {idx}')
                description = citation_data.get('description', '')
                url = citation_data.get('url', '')

                text = f"{name} - {description[:200]}" if description else name

                citations.append(Citation(
                    url=url if url else 'No URL found',
                    text=text,
                    number=idx
                ))

            # Fallback to URL-based extraction
            if not citations and urls:
                for idx, url in enumerate(urls, 1):
                    name = f"Source {idx}"

                    # Try to find name near URL
                    url_pos = panel_text.find(url)
                    if url_pos > 0:
                        text_before = panel_text[max(0, url_pos-150):url_pos].strip()
                        text_lines = text_before.split('\n')
                        if text_lines:
                            potential_name = text_lines[-1].strip()
                            if potential_name and len(potential_name) < 100:
                                name = potential_name

                    citations.append(Citation(url=url, text=name, number=idx))

        except Exception as e:
            logger.warning(f"Manual parsing failed: {e}")

        return citations

    def _close_panel(self, page: Page) -> None:
        """Close the citations panel."""
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass
