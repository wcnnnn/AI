"""
魔搭社区(ModelScope) 论文获取模块
获取每日精选论文或最新发布的高评价论文
"""
import os
import sys
import json
import logging
import requests
import re
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
from src.utils import load_config, get_papers_dir, ensure_dir

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
}


def fetch_modelscope_daily_papers(config, max_papers=30):
    """
    从魔搭社区获取每日论文

    Returns:
        List of paper dictionaries
    """
    papers = []

    # 方法1: 从ModelScope API获取论文
    try:
        logger.info("从魔搭社区获取论文...")

        # ModelScope 论文列表API
        url = "https://modelscope.cn/api/v1/models"

        params = {
            'PageSize': max_papers,
            'SortBy': 'latest_created',  # 按创建时间排序
        }

        response = requests.get(url, params=params, headers=HEADERS, timeout=30)

        if response.status_code == 200:
            data = response.json()
            models = data.get('Data', [])

            for model in models:
                try:
                    # 提取论文相关信息
                    title = model.get('name', '')
                    if not title:
                        continue

                    # 过滤掉非论文的模型
                    if any(kw in title.lower() for kw in ['model', 'checkpoint', '权重', '模型']):
                        continue

                    # 获取模型详情
                    model_id = model.get('ModelId', '')
                    if not model_id:
                        continue

                    # 获取arXiv链接
                    pdf_url = ''
                    arxiv_id = ''

                    # 查找论文相关字段
                    for tag in model.get('Tags', []):
                        if 'arxiv' in tag.get('Name', '').lower():
                            pdf_url = f"https://arxiv.org/pdf/{tag.get('Name', '').split('arxiv:')[-1]}"
                            arxiv_id = tag.get('Name', '').split('arxiv:')[-1]

                    # 从README获取更多信息
                    readme = model.get('Readme', {})

                    paper = {
                        'title': title,
                        'authors': [model.get('Owner', '')],
                        'abstract': model.get('Description', '')[:2000],
                        'published': model.get('CreatedAt', datetime.now().strftime('%Y-%m-%d')),
                        'arxiv_id': arxiv_id,
                        'url': f"https://modelscope.cn/models/{model_id}",
                        'pdf_url': pdf_url,
                        'source': 'ModelScope',
                        'conference': '魔搭社区',
                    }

                    papers.append(paper)
                    logger.debug(f"Found paper: {title[:50]}...")

                except Exception as e:
                    logger.debug(f"Error parsing model: {e}")
                    continue

    except Exception as e:
        logger.error(f"Error fetching from ModelScope: {e}")

    # 方法2: 备用 - 从arxiv获取最新论文
    if not papers:
        logger.info("尝试备用方案: 获取arXiv最新论文")
        papers = fetch_arxiv_latest(config, max_papers)

    logger.info(f"从魔搭社区获取了 {len(papers)} 篇论文")
    return papers


def fetch_arxiv_latest(config, max_papers=10):
    """
    从arXiv获取最新论文作为备选
    """
    papers = []

    try:
        # 使用arXiv API获取最新论文
        import xml.etree.ElementTree as ET

        # 获取机器学习相关最新论文
        search_query = 'cat:cs.LG+OR+cat:cs.AI+OR+cat:cs.CV+OR+cat:cs.CL'
        url = f'http://export.arxiv.org/api/query?search_query={search_query}&sortBy=submittedDate&sortOrder=descending&max_results={max_papers}'

        response = requests.get(url, timeout=30)

        if response.status_code == 200:
            root = ET.fromstring(response.content)

            # 处理命名空间
            namespace = {'atom': 'http://www.w3.org/2005/Atom'}

            for entry in root.findall('atom:entry', namespace):
                try:
                    title = entry.find('atom:title', namespace)
                    title = title.text.strip() if title is not None else ''

                    authors = []
                    for author in entry.findall('atom:author', namespace):
                        name = author.find('atom:name', namespace)
                        if name is not None:
                            authors.append(name.text.strip())

                    summary = entry.find('atom:summary', namespace)
                    abstract = summary.text.strip() if summary is not None else ''

                    # 获取arXiv ID
                    id_elem = entry.find('atom:id', namespace)
                    arxiv_id = ''
                    if id_elem is not None:
                        url_text = id_elem.text.strip()
                        arxiv_match = re.search(r'(\d+\.\d+)', url_text)
                        if arxiv_match:
                            arxiv_id = arxiv_match.group(1)

                    # 获取PDF链接
                    pdf_url = ''
                    for link in entry.findall('atom:link', namespace):
                        if link.get('title') == 'pdf':
                            pdf_url = link.get('href', '')

                    published = entry.find('atom:published', namespace)
                    published_date = ''
                    if published is not None:
                        published_date = published.text[:10]

                    paper = {
                        'title': title,
                        'authors': authors[:5],
                        'abstract': abstract[:2000],
                        'published': published_date,
                        'arxiv_id': arxiv_id,
                        'url': f'https://arxiv.org/abs/{arxiv_id}',
                        'pdf_url': pdf_url,
                        'source': 'arXiv',
                        'conference': 'arXiv最新',
                    }

                    papers.append(paper)

                except Exception as e:
                    logger.debug(f"Error parsing entry: {e}")
                    continue

    except Exception as e:
        logger.error(f"Error fetching from arXiv: {e}")

    return papers


def save_modelscope_papers(papers, filepath=None):
    """保存魔搭社区论文到JSON文件"""
    if filepath is None:
        filepath = os.path.join(get_papers_dir(), 'modelscope_papers.json')

    ensure_dir(os.path.dirname(filepath))

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)

    logger.info(f"保存了 {len(papers)} 篇魔搭社区论文到 {filepath}")
    return filepath


def load_modelscope_papers(filepath=None):
    """加载魔搭社区论文"""
    if filepath is None:
        filepath = os.path.join(get_papers_dir(), 'modelscope_papers.json')

    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def main():
    config = load_config('config.yaml')

    logger.info("开始获取魔搭社区论文...")

    papers = fetch_modelscope_daily_papers(config, max_papers=10)
    save_modelscope_papers(papers)

    logger.info(f"获取了 {len(papers)} 篇论文")


if __name__ == '__main__':
    main()
