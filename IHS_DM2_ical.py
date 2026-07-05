#!/usr/bin/env python3
"""
IHS Diabetes Training Calendar Scraper
Downloads and cleans .ics files from the IHS training page
"""

import requests
import re
import time
from datetime import datetime, time as dt_time
from bs4 import BeautifulSoup
from icalendar import Calendar, Event, vDatetime

# Configuration
IHS_URL = "https://www.ihs.gov/diabetes/training/"
OUTPUT_FILE = "index.ics"
USER_AGENT = "IHS-Calendar-Scraper/1.0 (github.com/matthew-hoctor/IHS-DM2-CME-feed)"

# Standard VTIMEZONE definition for Eastern Time
VTIMEZONE_EASTERN = """BEGIN:VTIMEZONE
TZID:Eastern Time
BEGIN:STANDARD
DTSTART:20061101T020000
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=1SU;BYMONTH=11
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:Standard Time
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:20060301T020000
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=2SU;BYMONTH=3
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:Daylight Savings Time
END:DAYLIGHT
END:VTIMEZONE"""

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
            cal_id_match = re.search(r'calID=([A-F0-9]+)', href)
            if cal_id_match:
                cal_id = cal_id_match.group(1)
                
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
    """Extract just the essential info from the description."""
    if not description:
        return ""
    
    if isinstance(description, bytes):
        description = description.decode('utf-8', errors='ignore')
    
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', str(description))
    
    # Clean up whitespace
    clean = re.sub(r'\s+', ' ', clean)
    clean = clean.strip()
    
    # Try to extract just the webinar access info
    # Look for JOIN WEBEX WEBINAR and what follows
    join_match = re.search(r'(JOIN WEBEX WEBINAR.*?)(?=IMPORTANT NOTICE|$)', clean, re.DOTALL)
    if join_match:
        clean = join_match.group(1).strip()
    else:
        # If we can't find the access info, truncate to reasonable length
        if len(clean) > 500:
            clean = clean[:497] + '...'
    
    # Remove any remaining HTML entities
    clean = clean.replace('&chr(39);', "'")
    clean = clean.replace('&nbsp;', ' ')
    clean = clean.replace('&amp;', '&')
    clean = clean.replace('&lt;', '<')
    clean = clean.replace('&gt;', '>')
    
    # Ensure the description is not too long for a single line
    # The iCalendar spec recommends folding lines longer than 75 characters
    # But we'll keep it as a single line and let the library handle folding
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
        # Get the raw content
        raw_content = response.content
        
        # Try to detect encoding from BOM
        if raw_content.startswith(b'\xff\xfe'):
            text_content = raw_content[2:].decode('utf-16-le')
            print("  Detected UTF-16 LE encoding")
        elif raw_content.startswith(b'\xfe\xff'):
            text_content = raw_content[2:].decode('utf-16-be')
            print("  Detected UTF-16 BE encoding")
        else:
            try:
                text_content = raw_content.decode('utf-8')
            except UnicodeDecodeError:
                text_content = raw_content.decode('utf-16', errors='ignore')
                print("  Detected UTF-16 encoding (no BOM)")
        
        # Remove any stray BOM characters
        text_content = text_content.replace('\ufeff', '')
        
        # Parse the ICS content
        cal = Calendar.from_ical(text_content.encode('utf-8'))
        
        for component in cal.walk():
            if component.name == "VEVENT":
                # Remove HTML version entirely - this crashes some calendar apps
                if 'X-ALT-DESC' in component:
                    del component['X-ALT-DESC']
                
                # Clean up description - shorten to essential info
                if 'DESCRIPTION' in component:
                    component['DESCRIPTION'] = clean_description(component['DESCRIPTION'])
                
                # Fix the time: all events should be 3:00 PM Eastern (12:00 PM Pacific)
                # and 1 hour duration
                if 'DTSTART' in component and 'DTEND' in component:
                    dtstart = component['DTSTART']
                    
                    # Get the date from the existing start time
                    event_date = dtstart.dt.date()
                    
                    # Create datetime objects for the new times
                    new_start = datetime.combine(event_date, dt_time(15, 0, 0))
                    new_end = datetime.combine(event_date, dt_time(16, 0, 0))
                    
                    # Create vDatetime objects
                    vstart = vDatetime(new_start)
                    vend = vDatetime(new_end)
                    
                    # Add TZID parameter to the vDatetime objects
                    vstart.params['TZID'] = ['Eastern Time']
                    vend.params['TZID'] = ['Eastern Time']
                    
                    # Assign the vDatetime objects with parameters
                    component['DTSTART'] = vstart
                    component['DTEND'] = vend
                    
                    print(f"  Standardized to 3:00 PM Eastern (1 hour duration)")
                
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
    
    # Create master calendar
    master_cal = Calendar()
    master_cal.add('prodid', '-//IHS Diabetes Calendar//github.com//')
    master_cal.add('version', '2.0')
    master_cal.add('calscale', 'GREGORIAN')
    master_cal.add('method', 'PUBLISH')
    master_cal.add('x-wr-calname', 'IHS Advancements in Diabetes Training')
    master_cal.add('x-wr-caldesc', 'Calendar of IHS Diabetes training webinars')
    
    # Add the VTIMEZONE component
    tz_cal = Calendar.from_ical(VTIMEZONE_EASTERN)
    for component in tz_cal.walk():
        if component.name == "VTIMEZONE":
            master_cal.add_component(component)
            print("Added VTIMEZONE: Eastern Time")
            break
    
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
    
    # Write the file with CRLF line endings
    try:
        # Generate the ICS content as bytes
        ics_bytes = master_cal.to_ical()
        
        # Convert to text, replace LF with CRLF, then convert back to bytes
        ics_text = ics_bytes.decode('utf-8')
        ics_text = ics_text.replace('\r\n', '\n')  # Standardize to LF
        ics_text = ics_text.replace('\n', '\r\n')  # Convert to CRLF
        
        # Write with CRLF line endings
        with open(OUTPUT_FILE, 'w', encoding='utf-8', newline='\r\n') as f:
            f.write(ics_text)
        
        print(f"\nCalendar written to {OUTPUT_FILE} with CRLF line endings")
    except Exception as e:
        print(f"ERROR writing file: {e}")
    
    print(f"Scraper finished at {datetime.now()}")

if __name__ == "__main__":
    main()
