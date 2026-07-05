import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Event
import re
from io import StringIO

def fetch_and_clean_ics(url):
    """Fetch an ICS file, clean it, and return an icalendar Calendar object."""
    response = requests.get(url)
    response.raise_for_status()
    
    # Parse the calendar
    cal = Calendar.from_ical(response.text)
    
    # Remove the HTML description
    for component in cal.walk():
        if component.name == "VEVENT":
            # Remove the HTML part
            if 'X-ALT-DESC' in component:
                del component['X-ALT-DESC']
            
            # Clean up the plain DESCRIPTION
            if 'DESCRIPTION' in component:
                # Remove any HTML tags
                clean_desc = re.sub(r'<[^>]+>', '', component['DESCRIPTION'])
                component['DESCRIPTION'] = clean_desc
            
    return cal

def main():
    # scrape for .ics links
    main_url = "https://www.ihs.gov/diabetes/training/"
    page = requests.get(main_url)
    soup = BeautifulSoup(page.text, 'html.parser')
    
    ics_links = []
    for link in soup.find_all('a', href=True):
        if link['href'].endswith('.ics'):
            # Ensure we have a full URL
            full_url = link['href']
            if full_url.startswith('/'):
                full_url = 'https://www.ihs.gov' + full_url
            ics_links.append(full_url)
    
    # Process each link and combine into one calendar
    master_cal = Calendar()
    master_cal.add('prodid', '-//IHS Diabetes Calendar//github.com//')
    master_cal.add('version', '2.0')
    
    for ics_url in ics_links:
        try:
            cleaned_cal = fetch_and_clean_ics(ics_url)
            # Add all events from this cleaned calendar to the master
            for component in cleaned_cal.walk():
                if component.name == "VEVENT":
                    master_cal.add_component(component)
        except Exception as e:
            print(f"Error processing {ics_url}: {e}")
    
    # Write the combined calendar to a file
    with open('index.ics', 'wb') as f:
        f.write(master_cal.to_ical())

if __name__ == "__main__":
    main()
