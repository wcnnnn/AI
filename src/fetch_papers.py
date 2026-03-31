"""Fetch papers from arXiv API using direct HTTP requests"""
import os
import sys
import json
import logging
import requests
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
from src.utils import load_config, get_papers_dir, ensure_dir

logger = logging.getLogger(__name__)

ARXIV_API_URL = "http://export.arxiv.org/api/query"

def fetch_arxiv_papers(config, days_back=7, max_results=50):
    """
    Fetch papers from arXiv using direct API calls

    Args:
        config: Configuration dictionary
        days_back: Number of days to look back
        max_results: Maximum number of results per category

    Returns:
        List of paper dictionaries
    """
    categories = config.get('arxiv', {}).get('categories', ['cs.AI', 'cs.LG', 'cs.CV'])
    max_results_per_cat = config.get('arxiv', {}).get('max_results', max_results)

    papers = []
    cutoff_date = datetime.now() - timedelta(days=days_back)

    for category in categories:
        logger.info(f"Fetching arXiv papers from category: {category}")

        # Build query
        query = f"cat:{category}"
        params = {
            'search_query': query,
            'start': 0,
            'max_results': max_results_per_cat,
            'sortBy': 'submittedDate',
            'sortOrder': 'descending'
        }

        try:
            response = requests.get(ARXIV_API_URL, params=params, timeout=60)
            response.raise_for_status()

            # Parse XML response
            root = ET.fromstring(response.content)

            # Use simple namespace handling - arXiv uses Atom namespace
            # We'll find entries without namespace prefixes
            ns = {
                'atom': 'http://www.w3.org/2005/Atom'
            }

            for entry in root.findall('atom:entry', ns):
                try:
                    # Get published date
                    published_str = entry.find('atom:published', ns).text
                    published = datetime.fromisoformat(published_str.replace('Z', '+00:00'))

                    # Check date
                    if published.replace(tzinfo=None) < cutoff_date:
                        continue

                    # Extract paper info
                    title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
                    summary = entry.find('atom:summary', ns).text.strip().replace('\n', ' ')

                    # Authors
                    authors = []
                    for author in entry.findall('atom:author', ns):
                        name = author.find('atom:name', ns)
                        if name is not None:
                            authors.append(name.text)

                    # arXiv ID
                    arxiv_id = entry.find('atom:id', ns).text.split('/')[-1]

                    # Links
                    url = entry.find('atom:id', ns).text
                    pdf_url = ''
                    for link in entry.findall('atom:link', ns):
                        if link.get('title') == 'pdf':
                            pdf_url = link.get('href')
                            break

                    # Categories - find without namespace prefix
                    categories_list = []
                    for cat in entry.findall('category'):
                        term = cat.get('term')
                        if term:
                            categories_list.append(term)

                    # Comment - find without namespace
                    comment = ''
                    for elem in entry:
                        if elem.tag.endswith('comment'):
                            comment = elem.text or ''
                            break

                    paper = {
                        'title': title,
                        'authors': authors,
                        'abstract': summary,
                        'published': published.strftime('%Y-%m-%d'),
                        'arxiv_id': arxiv_id,
                        'url': url,
                        'pdf_url': pdf_url,
                        'categories': categories_list,
                        'comment': comment,
                        'source': 'arXiv'
                    }
                    papers.append(paper)
                    logger.debug(f"Found paper: {title[:50]}...")

                except Exception as e:
                    logger.warning(f"Error parsing entry: {e}")
                    continue

        except requests.RequestException as e:
            logger.error(f"Error fetching from {category}: {e}")
            continue

    logger.info(f"Total arXiv papers fetched: {len(papers)}")
    return papers

def save_papers(papers, filepath=None):
    """Save papers to JSON file"""
    if filepath is None:
        filepath = os.path.join(get_papers_dir(), 'arxiv_papers.json')

    ensure_dir(os.path.dirname(filepath))

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved {len(papers)} papers to {filepath}")
    return filepath

def load_papers(filepath=None):
    """Load papers from JSON file"""
    if filepath is None:
        filepath = os.path.join(get_papers_dir(), 'arxiv_papers.json')

    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def main():
    """Main function for standalone execution"""
    config = load_config('config.yaml')
    setup_logging = __import__('src.utils', fromlist=['setup_logging']).setup_logging
    setup_logging(config)

    logger.info("Starting arXiv paper fetch...")

    papers = fetch_arxiv_papers(config, days_back=7)
    save_papers(papers)

    logger.info(f"Fetched and saved {len(papers)} papers")

if __name__ == '__main__':
    main()
