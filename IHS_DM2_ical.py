#!/usr/bin/env python3
"""
IHS Diabetes Training Calendar Scraper
Downloads and cleans .ics files from the IHS training page
"""

import requests
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup
from icalendar import Calendar, Event

# Configuration
IHS_URL = "https://www.ihs.gov/diabetes/training/"
OUTPUT_FILE = "index.ics"
USER_AGENT = "IHS-DM2-CME-feed/0.1 (github.com/matthew-hoctor/IHS-DM2-CME-feed)"

def fetch_page_with_retry(url, max_retries=3):
    """Fetch a page with retry logic."""
    headers = {'User-Agent': USER_AGENT}
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                raise
    return None

def find_calendar_links(html_content, base_url):
    """Extract all calendar links from the page HTML."""
    soup = BeautifulSoup(html_content, 'html.parser')
    calendar_links = []
    
    # Find all anchor tags
    for link in soup.find_all('a', href=True):
        href = link['href']
        
        # Look for calendar links with calID parameter
        if '/diabetes/calendar/?calID=' in href:
            # Extract the calID value
            cal_id_match = re.search(r'calID=([A-F0-9]+)', href)
            if cal_id_match:
                cal_id = cal_id_match.group(1)
                
                # Check if this is actually an ICS link (look for nearby text)
                parent = link.parent
                if parent:
                    parent_text = parent.get_text()
                    if 'ICS' in parent_text or 'ics' in parent_text.lower():
                        full_url = href
                        if full_url.startswith('/'):
                            full_url = base_url + full_url
                        
                        calendar_links.append({
                            'url': full_url,
                            'cal_id': cal_id,
                            'text': link.get_text(strip=True)
                        })
                        
                        print(f"Found calendar link: {full_url}")
    
    # Remove duplicates by calID
    seen = set()
    unique_links = []
    for link in calendar_links:
        if link['cal_id'] not in seen:
            seen.add(link['cal_id'])
            unique_links.append(link)
    
    return unique_links

def clean_description(description):
    """Remove HTML tags and clean up the description text."""
    if not description:
        return ""
    
    if isinstance(description, bytes):
        description = description.decode('utf-8', errors='ignore')
    
    clean = re.sub(r'<[^>]+>', '', str(description))
    clean = re.sub(r'\s+', ' ', clean)
    clean = clean.strip()
    
    return clean

def fetch_and_clean_ics(url):
    """Download, parse, and clean a single ICS file."""
    headers = {'User-Agent': USER_AGENT}
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        print(f"  Downloaded: {url}")
    except Exception as e:
        print(f"  ERROR downloading {url}: {e}")
        return None
    
    try:
        # Get the raw content and detect encoding
        raw_content = response.content
        
        # Try to decode as UTF-8 with BOM removal
        try:
            # First try: UTF-8 with BOM removal
            if raw_content.startswith(b'\xef\xbb\xbf'):
                text_content = raw_content[3:].decode('utf-8')
                print("  Stripped UTF-8 BOM")
            else:
                # Try to detect encoding
                import chardet
                detected = chardet.detect(raw_content)
                encoding = detected.get('encoding', 'utf-8')
                text_content = raw_content.decode(encoding, errors='ignore')
        except:
            # Fallback: decode with UTF-8, ignoring errors
            text_content = raw_content.decode('utf-8', errors='ignore')
        
        # Remove any remaining BOM characters from the text
        text_content = text_content.replace('\ufeff', '')
        
        # Also handle the case where BOM is in the line itself
        lines = text_content.split('\n')
        cleaned_lines = []
        for line in lines:
            # Remove BOM from individual lines if present
            cleaned_lines.append(line.replace('\ufeff', ''))
        text_content = '\n'.join(cleaned_lines)
        
        # Convert back to bytes for the parser
        cleaned_bytes = text_content.encode('utf-8')
        
        # Parse the cleaned content
        cal = Calendar.from_ical(cleaned_bytes)
        
        for component in cal.walk():
            if component.name == "VEVENT":
                if 'X-ALT-DESC' in component:
                    del component['X-ALT-DESC']
                
                if 'DESCRIPTION' in component:
                    component['DESCRIPTION'] = clean_description(component['DESCRIPTION'])
                
                print(f"  Cleaned event: {component.get('SUMMARY', 'Untitled')}")
        
        return cal
        
    except Exception as e:
        print(f"  ERROR parsing ICS from {url}: {e}")
        return None

def main():
    print(f"IHS Calendar Scraper started at {datetime.now()}")
    print(f"Fetching page: {IHS_URL}")
    
    try:
        response = fetch_page_with_retry(IHS_URL)
        if not response:
            print("ERROR: Could not fetch main page")
            return
    except Exception as e:
        print(f"ERROR: {e}")
        return
    
    print("Scanning for calendar links...")
    calendar_links = find_calendar_links(response.text, "https://www.ihs.gov")
    
    if not calendar_links:
        print("ERROR: No calendar links found")
        print("  The page structure might have changed. Check the URL manually.")
        return
    
    print(f"Found {len(calendar_links)} unique calendar links")
    
    master_cal = Calendar()
    master_cal.add('prodid', '-//IHS Diabetes Calendar//github.com//')
    master_cal.add('version', '2.0')
    master_cal.add('calscale', 'GREGORIAN')
    master_cal.add('method', 'PUBLISH')
    master_cal.add('x-wr-calname', 'IHS Advancements in Diabetes Training')
    master_cal.add('x-wr-caldesc', 'Calendar of IHS Diabetes training webinars')
    
    events_added = 0
    for i, link_info in enumerate(calendar_links, 1):
        ics_url = link_info['url']
        print(f"\nProcessing {i}/{len(calendar_links)}: {link_info['cal_id']}")
        print(f"  URL: {ics_url}")
        
        if i > 1:
            time.sleep(1)
        
        cleaned_cal = fetch_and_clean_ics(ics_url)
        
        if cleaned_cal:
            for component in cleaned_cal.walk():
                if component.name == "VEVENT":
                    master_cal.add_component(component)
                    events_added += 1
    
    print(f"\nAdded {events_added} events to calendar")
    
    try:
        with open(OUTPUT_FILE, 'wb') as f:
            f.write(master_cal.to_ical())
        print(f"\nCalendar written to {OUTPUT_FILE}")
    except Exception as e:
        print(f"ERROR writing file: {e}")
    
    print(f"Scraper finished at {datetime.now()}")

if __name__ == "__main__":
    main()
