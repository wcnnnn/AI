"""Generate Obsidian markdown notes from filtered papers with Mineru content"""
import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
from src.utils import load_config, sanitize_filename, format_date, get_year_month, ensure_dir
from src.filter_papers import load_filtered_papers
from src.parse_paper import process_papers_with_pdfs

logger = logging.getLogger(__name__)


def get_image_relative_path(image_path, vault_path, note_path=None):
    """
    Get relative path for Obsidian image embedding
    计算从笔记文件到图片的相对路径
    """
    if not image_path or not os.path.exists(image_path):
        return None

    try:
        # 如果提供了笔记路径，从笔记位置计算相对路径
        if note_path and os.path.exists(note_path):
            note_dir = os.path.dirname(note_path)
            rel_path = os.path.relpath(image_path, note_dir)
            rel_path = rel_path.replace('\\', '/')
            return rel_path
        elif vault_path and os.path.exists(vault_path):
            # 否则从vault根目录计算，使用 Papers 目录作为基准
            papers_dir = os.path.join(vault_path, 'Papers')
            if os.path.exists(papers_dir):
                rel_path = os.path.relpath(image_path, papers_dir)
            else:
                rel_path = os.path.relpath(image_path, vault_path)
            rel_path = rel_path.replace('\\', '/')
            return rel_path
    except Exception as e:
        logger.warning(f"Failed to calculate relative path: {e}")
        pass

    return None


def generate_frontmatter(paper, parsed_content=None):
    """Generate YAML frontmatter for Obsidian"""
    authors = paper.get('authors', [])
    if isinstance(authors, list):
        authors_str = ', '.join(authors[:5])
        if len(authors) > 5:
            authors_str += f' et al.'
    else:
        authors_str = str(authors)

    categories = paper.get('categories', paper.get('tags', []))
    if not categories:
        categories = ['AI']

    arxiv_id = paper.get('arxiv_id', '')
    conference = paper.get('conference', paper.get('source', ''))

    # Get Chinese summary info
    chinese_summary = parsed_content.get('chinese_summary') if parsed_content else None

    frontmatter = f'''---
title: "{paper.get('title', 'Untitled')}"
authors: "{authors_str}"
date: {paper.get('published', datetime.now().strftime('%Y-%m-%d'))}
source: {paper.get('source', 'Unknown')}
conference: "{conference}"
categories: [{', '.join([f'"{c}"' for c in categories[:5]])}]
arxiv_id: "{arxiv_id}"
url: {paper.get('url', '')}
abstract: |
  {paper.get('abstract', '')[:500]}
---
'''
    return frontmatter


def generate_markdown(paper, parsed_content=None, config=None, note_path=None):
    """
    Generate complete markdown note for a paper with Chinese summary
    """
    title = paper.get('title', 'Untitled')
    authors = paper.get('authors', [])
    if isinstance(authors, list):
        authors_str = ', '.join(authors[:5])
        if len(authors) > 5:
            authors_str += f' et al. ({len(authors)} authors)'
    else:
        authors_str = str(authors)

    published = paper.get('published', 'Unknown')
    source = paper.get('source', 'Unknown')
    conference = paper.get('conference', '')
    arxiv_id = paper.get('arxiv_id', '')
    url = paper.get('url', '')
    pdf_url = paper.get('pdf_url', '')

    # Get vault path and note path
    vault_path = ''
    obsidian_config = config.get('obsidian', {}) if config else {}
    vault_path = obsidian_config.get('vault_path', '')

    # Get note directory for relative path calculation
    note_dir = ''
    if note_path:
        # note_path 可能还不存在（新建的笔记），但我们可以从它的目录计算路径
        note_dir = os.path.dirname(note_path)
    elif vault_path and os.path.exists(vault_path):
        # 默认使用 vault 根目录下的 Papers 目录
        note_dir = os.path.join(vault_path, obsidian_config.get('notes_folder', 'Papers'))

    # Get Chinese summary
    chinese_summary = parsed_content.get('chinese_summary') if parsed_content else None
    images = parsed_content.get('images', []) if parsed_content else []
    tables = parsed_content.get('tables', []) if parsed_content else []

    markdown_parts = []

    # Title
    if chinese_summary and chinese_summary.get('title_zh'):
        markdown_parts.append(f"# {title}\n\n**中文标题**: {chinese_summary.get('title_zh')}\n")
    else:
        markdown_parts.append(f"# {title}\n")

    # Basic info
    markdown_parts.append("## 基本信息")
    markdown_parts.append(f"- **作者**: {authors_str}")
    markdown_parts.append(f"- **来源**: {source}")
    if conference:
        markdown_parts.append(f"- **会议/期刊**: {conference}")
    markdown_parts.append(f"- **日期**: {published}")
    if arxiv_id:
        markdown_parts.append(f"- **arXiv**: {arxiv_id}")
    markdown_parts.append(f"- **链接**: [论文]({url}) [PDF]({pdf_url})")

    # Original abstract
    markdown_parts.append("\n## 摘要 (英文)")
    markdown_parts.append(paper.get('abstract', 'No abstract available.'))

    # Chinese summary
    if chinese_summary:
        markdown_parts.append("\n---\n\n## 📖 论文精读 (中文)\n")

        if chinese_summary.get('core_problem'):
            markdown_parts.append("### 🔍 核心问题")
            markdown_parts.append(chinese_summary['core_problem'])

        if chinese_summary.get('core_idea'):
            markdown_parts.append("\n### 💡 核心创新点")
            markdown_parts.append(chinese_summary['core_idea'])

        if chinese_summary.get('method'):
            markdown_parts.append("\n### 🔧 方法介绍")
            markdown_parts.append(chinese_summary['method'])

        if chinese_summary.get('experiments'):
            markdown_parts.append("\n### 📊 实验结果")
            markdown_parts.append(chinese_summary['experiments'])

        if chinese_summary.get('conclusion'):
            markdown_parts.append("\n### ✅ 结论")
            markdown_parts.append(chinese_summary['conclusion'])

        if chinese_summary.get('limitations'):
            markdown_parts.append("\n### ⚠️ 局限性")
            markdown_parts.append(chinese_summary['limitations'])

        if chinese_summary.get('future_work'):
            markdown_parts.append("\n### 🚀 未来工作")
            markdown_parts.append(chinese_summary['future_work'])

    # Reading progress
    markdown_parts.append("\n---\n\n## 📋 阅读进度")
    markdown_parts.append("- [ ] 待阅读")
    markdown_parts.append("- [ ] 阅读中")
    markdown_parts.append("- [ ] 已理解")
    markdown_parts.append("- [ ] 已笔记")

    # Key figures from summary
    # 移除旧的key_figures展示，让图片在图表展示部分统一展示

    # Images section
    # 优先使用AI识别的图片描述
    key_figures = []
    # 获取AI识别的图片描述
    key_figures = []
    if chinese_summary and chinese_summary.get('key_figures'):
        key_figures = chinese_summary['key_figures']

    # 创建多种索引方式的映射
    file_to_figure = {}  # file字段 -> figure
    name_to_figure = {}  # name字段 -> figure

    if key_figures:
        for fig in key_figures:
            if isinstance(fig, dict):
                # 通过file字段索引
                filename = fig.get('file', '')
                if filename:
                    file_to_figure[filename] = fig
                    # 也去掉扩展名后匹配
                    file_to_figure[os.path.splitext(filename)[0]] = fig

                # 通过name字段索引
                name = fig.get('name', '')
                if name:
                    name_to_figure[name] = fig

    if images or key_figures:
        markdown_parts.append("\n---\n\n## 🖼️ 论文图表")

        # Add PDF link
        pdf_path = paper.get('pdf_path', '')
        if pdf_path and os.path.exists(pdf_path) and vault_path:
            pdf_rel = get_image_relative_path(pdf_path, vault_path)
            if pdf_rel:
                markdown_parts.append(f"- [📄 论文PDF]({pdf_rel})")

        markdown_parts.append("\n### 📈 图表展示（AI精读）")

        # 展示所有提取的图片
        for i, img_path in enumerate(images[:10]):
            if not img_path:
                continue

            img_ext = os.path.splitext(img_path)[1].lower()
            if img_ext == '.pdf':
                continue

            if not os.path.exists(img_path):
                continue

            img_filename = os.path.basename(img_path)
            img_name_without_ext = os.path.splitext(img_filename)[0]

            # 计算相对路径 - 从笔记所在目录计算
            rel_path = None
            if note_dir and os.path.exists(note_dir):
                try:
                    rel_path = os.path.relpath(img_path, note_dir)
                    rel_path = rel_path.replace('\\', '/')
                except:
                    rel_path = img_path
            elif vault_path and os.path.exists(vault_path):
                try:
                    # 使用vault路径，计算从Papers目录到图片的路径
                    papers_dir = os.path.join(vault_path, 'Papers')
                    rel_path = os.path.relpath(img_path, papers_dir)
                    rel_path = rel_path.replace('\\', '/')
                except:
                    rel_path = img_path

            if not rel_path:
                rel_path = img_path

            if rel_path:
                # 尝试多种方式匹配AI描述
                ai_desc = None

                # 1. 通过完整文件名匹配
                if img_filename in file_to_figure:
                    ai_desc = file_to_figure[img_filename]
                # 2. 通过去掉扩展名的文件名匹配
                elif img_name_without_ext in file_to_figure:
                    ai_desc = file_to_figure[img_name_without_ext]
                # 3. 通过序号匹配（如"图1", "Figure 1"等）
                else:
                    fig_num = i + 1
                    for name, fig in name_to_figure.items():
                        # 检查名称中是否包含数字
                        if str(fig_num) in name or f"Figure {fig_num}" in name or f"fig. {fig_num}" in name.lower():
                            ai_desc = fig
                            break

                # 如果都没匹配到，使用默认名称
                if not ai_desc:
                    ai_desc = {'name': f'图{i+1}', 'description': ''}

                fig_name = ai_desc.get('name', f'图{i+1}')
                fig_desc = ai_desc.get('description', '')

                markdown_parts.append(f"\n**{fig_name}**")
                if fig_desc:
                    markdown_parts.append(f"> {fig_desc}")
                markdown_parts.append(f"![{fig_name}]({rel_path})")

        # 如果有AI描述但没有对应图片，展示文字描述
        if key_figures:
            markdown_parts.append("\n### 📋 其他重要图表（文字描述）")
            for fig in key_figures[:5]:
                if isinstance(fig, dict):
                    markdown_parts.append(f"\n**{fig.get('name', '未知')}:**")
                    markdown_parts.append(f"- {fig.get('description', '无描述')}")

    # Tables section
    if tables:
        markdown_parts.append("\n### 📋 重要表格")

        # Show up to 3 tables
        for i, table in enumerate(tables[:3]):
            markdown_parts.append(f"\n**表 {i+1}:**")
            markdown_parts.append(table)
            markdown_parts.append("")

    # Notes section
    markdown_parts.append("\n---\n\n## 📝 阅读笔记\n\n> 在此添加您的阅读笔记...\n")

    # Footer
    markdown_parts.append(f"\n---\n*由AI论文推荐工作流自动生成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    return '\n'.join(markdown_parts)


def create_note(paper, vault_path, notes_folder, parsed_content=None, config=None):
    """Create an Obsidian note for a paper"""
    paper_date = paper.get('published', datetime.now().strftime('%Y-%m-%d'))

    try:
        date_parts = paper_date.split('-')
        year = date_parts[0]
        month = date_parts[1] if len(date_parts) > 1 else '01'
    except:
        year, month = get_year_month()

    paper_date_str = paper_date.replace('-', '')

    folder_path = os.path.join(vault_path, notes_folder, year, month)
    ensure_dir(folder_path)

    safe_title = sanitize_filename(paper.get('title', 'Untitled'))
    filename = f"{paper_date_str}_{safe_title}.md"
    filepath = os.path.join(folder_path, filename)

    # 传入note的路径，以便计算正确的相对路径
    content = generate_frontmatter(paper, parsed_content) + "\n\n"
    content += generate_markdown(paper, parsed_content, config, note_path=filepath)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    logger.info(f"Created note: {filename}")
    return filepath


def generate_all_notes(config, papers=None, parse_pdfs=True):
    """Generate notes for all filtered papers"""
    obsidian_config = config.get('obsidian', {})
    vault_path = obsidian_config.get('vault_path', '')

    if not vault_path:
        logger.error("Obsidian vault path not configured")
        return []

    notes_folder = obsidian_config.get('notes_folder', 'Papers')

    if not papers:
        papers = load_filtered_papers()

    logger.info(f"Generating notes for {len(papers)} papers...")

    # Process PDFs with Mineru and generate Chinese summaries
    parsed_contents = {}
    if parse_pdfs:
        parsed_list = process_papers_with_pdfs(config, papers)
        for parsed in parsed_list:
            paper_id = parsed.get('paper_id', '')
            parsed_contents[paper_id] = parsed

    # Generate posters and create notes
    created_notes = []
    for paper in papers:
        try:
            paper_id = paper.get('arxiv_id') or paper.get('title', '')[:30]
            parsed_content = parsed_contents.get(paper_id)

            filepath = create_note(paper, vault_path, notes_folder, parsed_content, config)
            created_notes.append(filepath)
        except Exception as e:
            logger.error(f"Error creating note for {paper.get('title', 'Unknown')}: {e}")

    logger.info(f"Created {len(created_notes)} notes")
    return created_notes


def main():
    """Main function for standalone execution"""
    config = load_config('config.yaml')
    setup_logging = __import__('src.utils', fromlist=['setup_logging']).setup_logging
    setup_logging(config)

    logger.info("Generating Obsidian notes with Mineru content...")

    papers = load_filtered_papers()
    logger.info(f"Loaded {len(papers)} filtered papers")

    notes = generate_all_notes(config, papers, parse_pdfs=True)

    logger.info(f"Generated {len(notes)} notes")
    print(f"\nCreated {len(notes)} notes in Obsidian")


if __name__ == '__main__':
    main()
