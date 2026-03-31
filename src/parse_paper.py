"""Parse PDF papers and generate Chinese summary using LLM + Mineru"""
import os
import sys
import json
import logging
import re

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
from src.utils import load_config, ensure_dir

logger = logging.getLogger(__name__)

# PDF extraction libraries
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not available")

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False
    logger.warning("pypdf not available")


def extract_text_from_pdf(pdf_path, max_pages=15):
    """Extract text from PDF, limiting to first max_pages"""
    text = ""
    try:
        if PDFPLUMBER_AVAILABLE:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                pages_to_extract = min(total_pages, max_pages)

                for i in range(pages_to_extract):
                    page = pdf.pages[i]
                    page_text = page.extract_text()
                    if page_text:
                        text += f"\n--- 第{i+1}页 ---\n"
                        text += page_text + "\n"

                logger.info(f"Extracted text from {pages_to_extract} pages ({total_pages} total)")
        elif PYPDF_AVAILABLE:
            reader = PdfReader(pdf_path)
            total_pages = len(reader.pages)
            pages_to_extract = min(total_pages, max_pages)

            for i in range(pages_to_extract):
                page = reader.pages[i]
                text += f"\n--- 第{i+1}页 ---\n"
                text += page.extract_text() + "\n"

            logger.info(f"Extracted text from {pages_to_extract} pages")
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")

    return text


def generate_chinese_summary_from_markdown(markdown_text, config, images=None):
    """Generate Chinese summary using LLM API from Mineru markdown, with image descriptions"""
    llm_config = config.get('llm_api', {})
    api_key = llm_config.get('api_key', '')
    model = llm_config.get('model', 'MiniMax-M2.5')
    base_url = llm_config.get('base_url', 'https://api.minimax.chat/v1')

    if not api_key:
        logger.warning("No LLM API key configured")
        return None

    # Limit text length
    text = markdown_text[:15000]

    # 准备图片信息
    image_info = ""
    if images:
        image_info = f"\n\n## 论文中的图片列表（共{len(images)}张）：\n"
        for i, img in enumerate(images[:10], 1):
            img_name = os.path.basename(img) if img else f"图片{i}"
            image_info += f"- 图片{i}: {img_name}\n"
        image_info += "\n请在阅读论文时识别这些图片的内容，并给出详细解释。"

    prompt = f"""你是一个专业的AI论文阅读助手。请仔细阅读以下论文内容（Markdown格式，已从PDF提取），然后用中文撰写一份详细专业的论文阅读笔记。

论文内容（Markdown格式）：
{text}
{image_info}

请按照以下格式返回JSON格式的阅读笔记：

{{
    "title": "论文标题的简要英文名称",
    "title_zh": "论文中文标题（如果能从内容推断）",
    "authors_summary": "主要作者（用英文逗号分隔，最多5位）",
    "published": "论文发表时间",
    "venue": "发表会议或期刊",
    "core_problem": "论文要解决的核心问题（用2-3句话概括）",
    "core_idea": "核心创新点（用3-5句话概括）",
    "method": "方法详细介绍（5-8句话，包含关键算法步骤）",
    "experiments": "实验设置和主要结果（5-8句话，包含具体数值）",
    "conclusion": "论文结论和贡献（2-3句话）",
    "limitations": "论文局限性（1-2句话）",
    "future_work": "可能的改进方向（1-2句话）",
    "key_figures": [
        {{"id": 1, "name": "图1名称/编号", "description": "这张图片展示的内容和意义，详细描述可视化结果", "file": "图片文件名"}},
        {{"id": 2, "name": "图2名称/编号", "description": "这张图片展示的内容和意义", "file": "图片文件名"}},
        {{"id": 3, "name": "图3名称/编号", "description": "这张图片展示的内容和意义", "file": "图片文件名"}},
        {{"id": 4, "name": "图4名称/编号", "description": "这张图片展示的内容和意义", "file": "图片文件名"}},
        {{"id": 5, "name": "图5名称/编号", "description": "这张图片展示的内容和意义", "file": "图片文件名"}}
    ],
    "key_tables": [
        {{"id": 1, "name": "表1名称", "description": "表格内容和意义"}},
        {{"id": 2, "name": "表2名称", "description": "表格内容和意义"}}
    ]
}}

请只返回JSON，不要有其他内容。"""

    try:
        import requests

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }

        # Map model
        if 'mini' in model.lower() or 'haiku' in model.lower():
            model_to_use = 'abab6.5s-chat'
        elif 'sonnet' in model.lower():
            model_to_use = 'abab6.5g-chat'
        else:
            model_to_use = 'abab6.5s-chat'

        payload = {
            'model': model_to_use,
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.7,
            'max_tokens': 3000
        }

        response = requests.post(
            f'{base_url}/chat/completions',
            headers=headers,
            json=payload,
            timeout=180
        )

        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']

            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                summary = json.loads(json_match.group())
                logger.info("Successfully generated Chinese summary from Mineru markdown")
                return summary
        else:
            logger.error(f"API request failed: {response.status_code}")

    except Exception as e:
        logger.error(f"Error generating summary: {e}")

    return None


def generate_chinese_summary_from_text(text, config):
    """Fallback: Generate Chinese summary from plain text"""
    llm_config = config.get('llm_api', {})
    api_key = llm_config.get('api_key', '')
    model = llm_config.get('model', 'MiniMax-M2.5')
    base_url = llm_config.get('base_url', 'https://api.minimax.chat/v1')

    if not api_key:
        logger.warning("No LLM API key configured")
        return None

    # Limit text length
    text = text[:8000]

    prompt = f"""你是一个专业的AI论文阅读助手。请仔细阅读以下论文内容，然后用中文撰写一份详细的阅读笔记。

论文内容：
{text}

请按照以下格式返回JSON格式的阅读笔记：

{{
    "title": "论文标题",
    "title_zh": "中文标题",
    "authors_summary": "主要作者",
    "published": "发表时间",
    "venue": "发表会议/期刊",
    "core_problem": "核心问题（2-3句话）",
    "core_idea": "核心创新点（3-5句话）",
    "method": "方法介绍（5-8句话）",
    "experiments": "实验结果（5-8句话，包含数值）",
    "conclusion": "结论（2-3句话）",
    "limitations": "局限性（1-2句话）",
    "future_work": "未来工作（1-2句话）",
    "key_figures": ["图1描述", "图2描述", "图3描述"],
    "key_tables": []
}}

请只返回JSON。"""

    try:
        import requests

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }

        if 'mini' in model.lower() or 'haiku' in model.lower():
            model_to_use = 'abab6.5s-chat'
        else:
            model_to_use = 'abab6.5s-chat'

        payload = {
            'model': model_to_use,
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.7,
            'max_tokens': 2000
        }

        response = requests.post(
            f'{base_url}/chat/completions',
            headers=headers,
            json=payload,
            timeout=120
        )

        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']

            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                summary = json.loads(json_match.group())
                return summary

    except Exception as e:
        logger.error(f"Error generating summary: {e}")

    return None


def parse_paper(paper, pdf_path, config):
    """
    Parse a paper PDF:
    1. Try Mineru to convert PDF to Markdown
    2. Use LLM to generate Chinese summary from Markdown
    3. Extract images from Mineru result
    """
    result = {
        'paper_id': paper.get('arxiv_id') or paper.get('title', '')[:30].replace(' ', '_'),
        'pdf_path': pdf_path,
        'markdown': '',
        'chinese_summary': None,
        'images': [],
        'tables': [],
        'mineru_success': False
    }

    logger.info(f"Parsing paper: {paper.get('title', '')[:50]}...")

    # Step 1: Try Mineru to convert PDF to Markdown
    from src.mineru import process_paper_with_mineru

    logger.info("Step 1: Trying Mineru to convert PDF to Markdown...")
    mineru_result = process_paper_with_mineru(paper, pdf_path, config)

    if mineru_result and mineru_result.get('mineru_success'):
        # Mineru succeeded!
        markdown = mineru_result.get('markdown', '')
        if markdown:
            result['markdown'] = markdown
            result['images'] = mineru_result.get('images', [])
            result['tables'] = mineru_result.get('tables', [])
            result['mineru_success'] = True

            # Step 2: Generate Chinese summary from Mineru markdown
            logger.info("Step 2: Generating Chinese summary from Mineru markdown...")
            images = mineru_result.get('images', [])
            summary = generate_chinese_summary_from_markdown(markdown, config, images)
            if summary:
                result['chinese_summary'] = summary
                logger.info("Chinese summary generated from Mineru content")
                return result
            else:
                logger.warning("Failed to generate summary from Mineru markdown")

    # Fallback: Use plain text extraction + LLM summary
    logger.info("Fallback: Using plain text extraction + LLM summary...")
    text = extract_text_from_pdf(pdf_path)
    result['markdown'] = text

    summary = generate_chinese_summary_from_text(text, config)
    if summary:
        result['chinese_summary'] = summary
        logger.info("Chinese summary generated from plain text")

    return result


def save_parsed_paper(parsed_paper, output_path=None):
    """Save parsed paper content to JSON"""
    if output_path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(project_root, 'papers', 'parsed')
        ensure_dir(output_dir)
        paper_id = parsed_paper.get('paper_id', 'unknown')
        output_path = os.path.join(output_dir, f"{paper_id}.json")

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(parsed_paper, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved parsed paper to {output_path}")
    return output_path


def process_papers_with_pdfs(config, papers):
    """Process papers: Mineru -> LLM summary -> Extract images"""
    obsidian_config = config.get('obsidian', {})
    vault_path = obsidian_config.get('vault_path', '')
    pdf_folder = obsidian_config.get('pdf_folder', '论文库')

    if not vault_path:
        logger.error("Vault path not configured")
        return []

    parsed_papers = []

    for paper in papers:
        if not paper.get('pdf_url'):
            continue

        arxiv_id = paper.get('arxiv_id', '')

        possible_paths = []

        if arxiv_id:
            pdf_filename = f"{arxiv_id}.pdf"
            pdf_path = os.path.join(vault_path, pdf_folder, pdf_filename)
            possible_paths.append(pdf_path)

            if 'v' in arxiv_id:
                arxiv_id_no_version = arxiv_id.split('v')[0] + '.pdf'
                pdf_path2 = os.path.join(vault_path, pdf_folder, arxiv_id_no_version)
                possible_paths.append(pdf_path2)

        # Search for PDF
        pdf_dir = os.path.join(vault_path, pdf_folder)
        if os.path.exists(pdf_dir):
            title = paper.get('title', '')[:30].replace(' ', '_').replace('/', '-')
            for f in os.listdir(pdf_dir):
                if f.endswith('.pdf'):
                    if arxiv_id and arxiv_id in f:
                        possible_paths.append(os.path.join(pdf_dir, f))

        pdf_path = None
        for path in possible_paths:
            if os.path.exists(path):
                pdf_path = path
                logger.info(f"Found PDF: {path}")
                break

        if not pdf_path:
            logger.debug(f"PDF not found for: {paper.get('title', '')[:30]}")
            continue

        try:
            parsed = parse_paper(paper, pdf_path, config)
            parsed['original_paper'] = paper
            parsed_papers.append(parsed)

            save_parsed_paper(parsed)

        except Exception as e:
            logger.error(f"Error parsing paper {paper.get('title', '')[:30]}: {e}")

    logger.info(f"Processed {len(parsed_papers)} papers with Chinese summaries")
    return parsed_papers


def main():
    config = load_config('config.yaml')
    setup_logging = __import__('src.utils', fromlist=['setup_logging']).setup_logging
    setup_logging(config)

    from src.filter_papers import load_filtered_papers
    papers = load_filtered_papers()

    if papers:
        parsed = process_papers_with_pdfs(config, papers[:1])
        if parsed:
            print(f"Parsed: {parsed[0].get('chinese_summary')}")


if __name__ == '__main__':
    main()
