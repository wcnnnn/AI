"""Filter papers based on user interests using keyword matching and optional LLM"""
import os
import sys
import json
import logging
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
from src.utils import load_config, get_papers_dir
from src.fetch_papers import load_papers as load_arxiv_papers
from src.fetch_modelscope import load_modelscope_papers

logger = logging.getLogger(__name__)

def calculate_keyword_score(paper, keywords, exclude_keywords=None):
    """
    Calculate relevance score based on keyword matching

    Args:
        paper: Paper dictionary
        keywords: List of positive keywords
        exclude_keywords: List of negative keywords

    Returns:
        Tuple of (score, matched_keywords)
    """
    if exclude_keywords is None:
        exclude_keywords = []

    text = (paper.get('title', '') + ' ' + paper.get('abstract', '')).lower()

    # Check for exclusion keywords
    for exclude in exclude_keywords:
        if exclude.lower() in text:
            return 0.0, []

    # Count positive keyword matches
    matched = []
    for keyword in keywords:
        if keyword.lower() in text:
            matched.append(keyword)

    # Calculate score based on matches
    if not keywords:
        return 0.5, []

    score = len(matched) / len(keywords)

    # Boost score if keyword appears in title
    title = paper.get('title', '').lower()
    for keyword in matched:
        if keyword.lower() in title:
            score += 0.1

    # Cap at 1.0
    score = min(score, 1.0)

    return score, matched

def calculate_llm_score(paper, config):
    """
    Calculate relevance score using LLM API

    This is optional and requires API configuration
    """
    llm_config = config.get('llm_api', {})
    api_key = llm_config.get('api_key', '')

    if not api_key:
        return None, None

    provider = llm_config.get('provider', 'openai')
    model = llm_config.get('model', 'gpt-3.5-turbo')
    keywords = config.get('keywords', [])

    prompt = f"""Based on the following research keywords: {', '.join(keywords)}

Title: {paper.get('title', '')}
Abstract: {paper.get('abstract', '')[:1000]}

Rate the relevance of this paper to the research interests on a scale of 0 to 1.
Return only the score as a decimal (e.g., 0.85)."""

    try:
        if provider == 'openai':
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=10
            )
            score_text = response.choices[0].message.content.strip()
            score = float(score_text)
            return score, ["LLM evaluated"]

        elif provider == 'anthropic':
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model,
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}]
            )
            score_text = response.content[0].text.strip()
            score = float(score_text)
            return score, ["LLM evaluated"]

    except Exception as e:
        logger.error(f"LLM scoring error: {e}")

    return None, None

def filter_papers(config, papers=None, arxiv_limit=5, modelscope_limit=3):
    """
    Filter papers based on relevance to user interests

    Args:
        config: Configuration dictionary
        papers: Optional list of papers (if None, loads from files)
        arxiv_limit: Max papers to include from arXiv
        modelscope_limit: Max papers to include from ModelScope

    Returns:
        List of filtered papers with relevance scores
    """
    keywords = config.get('keywords', [])
    exclude_keywords = config.get('exclude_keywords', [])
    threshold = config.get('relevance_threshold', 0.05)
    use_llm = False  # 只使用关键词过滤，不使用LLM评分

    if not papers:
        # Load papers from files (only arXiv and ModelScope)
        arxiv_papers = load_arxiv_papers()
        modelscope_papers = load_modelscope_papers()

        # Add source type for tracking
        for p in arxiv_papers:
            p['source_type'] = 'arXiv'
        for p in modelscope_papers:
            p['source_type'] = 'ModelScope'

        papers = arxiv_papers + modelscope_papers

    # Deduplicate by arxiv_id (keep highest relevance if same paper appears twice)
    seen_ids = {}
    deduped = []
    for p in papers:
        pid = p.get('arxiv_id', '').strip()
        if pid:
            if pid not in seen_ids:
                seen_ids[pid] = True
                deduped.append(p)
        else:
            deduped.append(p)
    if len(deduped) < len(papers):
        logger.info(f"Removed {len(papers) - len(deduped)} duplicate papers")
    papers = deduped

    logger.info(f"Filtering {len(papers)} papers with threshold {threshold}")

    filtered = []
    for paper in papers:
        # Keyword-based scoring
        score, matched_keywords = calculate_keyword_score(
            paper, keywords, exclude_keywords
        )

        # If score is high enough, add directly
        if score >= threshold:
            paper['relevance'] = score
            paper['matched_keywords'] = matched_keywords
            filtered.append(paper)
            continue

        # Optional LLM scoring for borderline cases
        if use_llm and score > 0.2:
            llm_score, llm_notes = calculate_llm_score(paper, config)
            if llm_score:
                paper['relevance'] = llm_score
                paper['matched_keywords'] = llm_notes + matched_keywords
                if llm_score >= threshold:
                    filtered.append(paper)

    # Sort by relevance score
    filtered.sort(key=lambda x: x.get('relevance', 0), reverse=True)

    # Separate by source type and apply limits
    arxiv_filtered = [p for p in filtered if p.get('source_type') == 'arXiv']
    modelscope_filtered = [p for p in filtered if p.get('source_type') == 'ModelScope']

    # Take top papers from each source
    arxiv_result = arxiv_filtered[:arxiv_limit]
    modelscope_result = modelscope_filtered[:modelscope_limit]

    # Combine results (arXiv first, then ModelScope)
    filtered = arxiv_result + modelscope_result

    logger.info(f"Filtered: {len(arxiv_result)} arXiv + {len(modelscope_result)} ModelScope = {len(filtered)} total")
    return filtered

def load_filtered_papers(filepath=None):
    """Load filtered papers from JSON file"""
    if filepath is None:
        filepath = os.path.join(get_papers_dir(), 'filtered_papers.json')

    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_filtered_papers(papers, filepath=None):
    """Save filtered papers to JSON file"""
    if filepath is None:
        filepath = os.path.join(get_papers_dir(), 'filtered_papers.json')

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved {len(papers)} filtered papers to {filepath}")
    return filepath

def main():
    """Main function for standalone execution"""
    config = load_config('config.yaml')
    setup_logging = __import__('src.utils', fromlist=['setup_logging']).setup_logging
    setup_logging(config)

    logger.info("Starting paper filtering...")

    filtered = filter_papers(config)
    save_filtered_papers(filtered)

    logger.info(f"Filtered to {len(filtered)} relevant papers")
    print(f"\nTop 5 relevant papers:")
    for i, paper in enumerate(filtered[:5]):
        print(f"{i+1}. {paper['title'][:60]}...")
        print(f"   Score: {paper['relevance']:.2f}")
        print(f"   Keywords: {', '.join(paper.get('matched_keywords', []))}")
        print()

if __name__ == '__main__':
    main()
