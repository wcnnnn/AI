"""Generate a daily HTML carousel report showing all papers for today"""
import os
import sys
import json
import logging
import base64
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
from src.utils import load_config, ensure_dir

logger = logging.getLogger(__name__)


def _img_to_base64(img_path):
    """Convert image file to base64 data URI."""
    if not img_path or not os.path.exists(img_path):
        return None
    try:
        ext = os.path.splitext(img_path)[1].lower().lstrip('.')
        mime = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'gif': 'gif', 'webp': 'webp'}.get(ext, 'png')
        with open(img_path, 'rb') as f:
            data = base64.b64encode(f.read()).decode('utf-8')
        return f"data:image/{mime};base64,{data}"
    except Exception as e:
        logger.debug(f"Failed to encode image {img_path}: {e}")
        return None


def _get_paper_images(paper, config, max_images=6):
    """Collect image paths for a paper (extracted figures)."""
    images = []
    obsidian_config = config.get('obsidian', {})
    vault_path = obsidian_config.get('vault_path', '')
    images_folder = obsidian_config.get('images_folder', '论文图片')

    # From paper['images'] field
    for img_path in paper.get('images', []):
        if img_path and os.path.exists(img_path) and not img_path.endswith('.pdf'):
            images.append(img_path)
        if len(images) >= max_images:
            break

    # Fallback: scan image directory
    if not images and vault_path:
        title = paper.get('title', '')[:30].replace(' ', '_').replace('/', '-')
        import re
        safe_title = re.sub(r'[<>:"\\|?*]', '_', title)
        img_dir = os.path.join(vault_path, images_folder, safe_title)
        if os.path.exists(img_dir):
            for f in sorted(os.listdir(img_dir)):
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    images.append(os.path.join(img_dir, f))
                if len(images) >= max_images:
                    break

    return images


def _load_parsed_content(paper):
    """Try to load parsed JSON for a paper from papers/parsed/."""
    try:
        arxiv_id = paper.get('arxiv_id', '')
        title = paper.get('title', '')[:30].replace(' ', '_')
        paper_id = arxiv_id if arxiv_id else title

        parsed_dir = os.path.join(project_root, 'papers', 'parsed')
        candidates = []
        if arxiv_id:
            candidates.append(os.path.join(parsed_dir, f"{arxiv_id}.json"))
            base_id = arxiv_id.split('v')[0] if 'v' in arxiv_id else arxiv_id
            candidates.append(os.path.join(parsed_dir, f"{base_id}.json"))

        for path in candidates:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
    except Exception as e:
        logger.debug(f"Could not load parsed content: {e}")
    return {}


def _preprocess_latex(text):
    """Convert common LaTeX text macros to HTML equivalents."""
    import re
    # Escaped special chars
    text = text.replace(r'\%', '%').replace(r'\&', '&amp;').replace(r'\$', '$')
    text = text.replace(r'\_', '_').replace(r'\#', '#').replace(r'\~', '~')
    text = text.replace(r'\textbackslash', '\\')
    # \textsc{X} -> <span style="font-variant:small-caps">X</span>
    text = re.sub(r'\\textsc\{([^}]*)\}', lambda m: m.group(1).upper(), text)
    # \emph{X} -> <em>X</em>
    text = re.sub(r'\\emph\{([^}]*)\}', r'<em>\1</em>', text)
    # \textbf{X} -> <strong>X</strong>
    text = re.sub(r'\\textbf\{([^}]*)\}', r'<strong>\1</strong>', text)
    # \textit{X} -> <em>X</em>
    text = re.sub(r'\\textit\{([^}]*)\}', r'<em>\1</em>', text)
    # \text{X} -> X
    text = re.sub(r'\\text\{([^}]*)\}', r'\1', text)
    # \cite{X} -> [X]
    text = re.sub(r'\\cite\{([^}]*)\}', r'[\1]', text)
    # \url{X} -> <a href="X">X</a>
    text = re.sub(r'\\url\{([^}]*)\}', r'<a href="\1" target="_blank">\1</a>', text)
    # Remove remaining unknown \cmd{} wrappers gracefully
    text = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', text)
    # Remove lone \cmd
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)
    return text


def _build_paper_card(index, paper, config, total):
    """Build HTML for a single paper card."""
    title = paper.get('title', 'Untitled')
    authors = paper.get('authors', [])
    if isinstance(authors, list):
        authors_str = ', '.join(authors[:5])
        if len(authors) > 5:
            authors_str += ' et al.'
    else:
        authors_str = str(authors)

    source = paper.get('source', paper.get('source_type', ''))
    published = paper.get('published', '')[:10]
    arxiv_id = paper.get('arxiv_id', '')
    url = paper.get('url', '')
    abstract = _preprocess_latex(paper.get('abstract', ''))
    keywords = paper.get('matched_keywords', [])

    # Load parsed content
    parsed = _load_parsed_content(paper)
    chinese_summary = parsed.get('chinese_summary') or {}
    title_zh = chinese_summary.get('title_zh', '')
    core_problem = _preprocess_latex(chinese_summary.get('core_problem', ''))
    core_idea = _preprocess_latex(chinese_summary.get('core_idea', ''))
    method = _preprocess_latex(chinese_summary.get('method', ''))
    conclusion = _preprocess_latex(chinese_summary.get('conclusion', ''))

    # PDF path for iframe
    pdf_path = paper.get('pdf_path', '')
    pdf_file_url = ''
    if pdf_path and os.path.exists(pdf_path):
        # Convert Windows backslashes, make file:/// URL
        pdf_file_url = 'file:///' + pdf_path.replace('\\', '/')

    source_cls = 'badge-arxiv' if 'arxiv' in source.lower() else 'badge-ms'
    active_cls = 'active' if index == 0 else ''

    has_summary = bool(core_problem or core_idea)

    summary_html = ''
    if has_summary:
        if core_problem:
            summary_html += f'<div class="summary-section"><span class="summary-label">🔍 核心问题</span><p>{core_problem}</p></div>'
        if core_idea:
            summary_html += f'<div class="summary-section"><span class="summary-label">💡 核心创新</span><p>{core_idea}</p></div>'
        if method:
            summary_html += f'<div class="summary-section"><span class="summary-label">🔧 方法</span><p>{method}</p></div>'
        if conclusion:
            summary_html += f'<div class="summary-section"><span class="summary-label">✅ 结论</span><p>{conclusion}</p></div>'

    summary_tab_btn = f'<button class="tab-btn" onclick="switchTab({index}, \'summary\')">中文精读</button>' if has_summary else ''
    summary_tab_div = f'<div class="tab-content hidden" id="tab-{index}-summary">{summary_html}</div>' if has_summary else ''

    kw_badges = ''.join(f'<span class="badge badge-kw">{kw}</span>' for kw in keywords[:4])
    title_link = f'<a href="{url}" target="_blank">{title}</a>' if url else title
    title_zh_html = f'<p class="title-zh">{title_zh}</p>' if title_zh else ''

    safe_title_attr = title.replace('"', '&quot;').replace("'", '&#39;')
    safe_authors_attr = authors_str.replace('"', '&quot;')
    safe_kw_attr = ' '.join(keywords).replace('"', '&quot;')

    return f'''
<div class="paper-card {active_cls}" id="card-{index}"
     data-title="{safe_title_attr}" data-authors="{safe_authors_attr}" data-kw="{safe_kw_attr}">
  <div class="card-header">
    <div class="card-meta">
      <span class="badge {source_cls}">{source}</span>
      <span class="badge badge-date">{published}</span>
      {kw_badges}
    </div>
    <div style="display:flex;align-items:center;gap:8px;">
      <button class="fav-btn" id="fav-{index}" onclick="toggleFav({index})" title="\u6536\u85cf">☆</button>
      <div class="card-counter">{index + 1} / {total}</div>
    </div>
  </div>
  <div class="card-content">
    <h2 class="paper-title">{title_link}</h2>
    {title_zh_html}
    <p class="authors">✍️ {authors_str}</p>
    <div class="section-tabs">
      <button class="tab-btn active" onclick="switchTab({index}, \'abstract\')">摘要</button>
      {summary_tab_btn}
    </div>
    <div class="tab-content" id="tab-{index}-abstract">
      <div class="abstract-box"><p>{abstract}</p></div>
    </div>
    {summary_tab_div}
  </div>
</div>'''


def generate_daily_html(config, papers, share_mode=False):
    """
    Generate a daily carousel HTML report for all papers.

    Args:
        config: Config dict
        papers: List of paper dicts
        share_mode: If True, generate a self-contained shareable HTML
                    (no local file:/// paths, PDF pane replaced with arXiv link)

    Returns:
        Path to generated HTML file
    """
    if not papers:
        logger.warning("No papers to generate HTML for")
        return None

    obsidian_config = config.get('obsidian', {})
    vault_path = obsidian_config.get('vault_path', '')
    if share_mode:
        output_dir = os.path.join(project_root, 'output', 'share')
    else:
        output_dir = os.path.join(vault_path, 'Papers', 'daily') if vault_path else os.path.join(project_root, 'output')
    ensure_dir(output_dir)

    today = datetime.now().strftime('%Y-%m-%d')
    filename = f"daily_{today}.html"
    output_path = os.path.join(output_dir, filename)

    total = len(papers)
    cards_html = '\n'.join(_build_paper_card(i, p, config, total) for i, p in enumerate(papers))

    # Build PDF URL array for JS
    # In share_mode use arXiv abstract/PDF URLs instead of local file:/// paths
    pdf_urls = []
    arxiv_urls = []
    for paper in papers:
        arxiv_id = paper.get('arxiv_id', '')
        arxiv_url = paper.get('url', '')
        arxiv_pdf = f'https://arxiv.org/pdf/{arxiv_id}' if arxiv_id else ''
        arxiv_urls.append({'url': arxiv_url, 'pdf': arxiv_pdf, 'id': arxiv_id})
        if share_mode:
            pdf_urls.append('')
        else:
            pdf_path = paper.get('pdf_path', '')
            if pdf_path and os.path.exists(pdf_path):
                pdf_urls.append('file:///' + pdf_path.replace('\\', '/'))
            else:
                pdf_urls.append('')
    pdf_urls_js = json.dumps(pdf_urls)
    arxiv_urls_js = json.dumps(arxiv_urls)

    html = f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI论文日报 · {today}</title>
<style>
  /* ── Warm color tokens ──
     bg:        #fdf6ee  (warm cream)
     surface:   #fff8f0  (light warm white)
     surface2:  #fef3e2  (pale amber)
     border:    #e8d5b7  (warm tan)
     accent:    #c2660a  (amber-brown)
     accent2:   #e8963a  (amber)
     text:      #3d2b1f  (dark brown)
     muted:     #8a6a50  (warm gray-brown)
  */
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, "Microsoft YaHei", "PingFang SC", sans-serif;
    background: #f5ebe0;
    color: #3d2b1f;
    display: flex;
    flex-direction: column;
  }}
  /* ── Header ── */
  .site-header {{
    background: linear-gradient(135deg, #7c4a1e 0%, #a0522d 100%);
    border-bottom: 1px solid #c8956a;
    padding: 12px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
    gap: 12px;
    z-index: 100;
    box-shadow: 0 2px 12px rgba(124,74,30,.25);
  }}
  .site-header h1 {{ font-size: 1.1rem; color: #fde8c8; letter-spacing: .03em; white-space: nowrap; }}
  .site-header .subtitle {{ font-size: .78rem; color: #f5cfa0; white-space: nowrap; }}
  .header-right {{
    display: flex;
    gap: 8px;
    align-items: center;
    flex-shrink: 1;
    min-width: 0;
  }}
  .header-right span {{
    font-size: .78rem;
    color: #f5cfa0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  /* ── Full-viewport split layout ── */
  body {{ overflow: hidden; height: 100vh; }}
  .split-container {{
    display: flex;
    height: 100vh;
    overflow: hidden;
  }}
  /* Left pane */
  .left-pane {{
    display: flex;
    flex-direction: column;
    width: 50%;
    min-width: 300px;
    overflow: hidden;
    background: #f5ebe0;
  }}
  .left-pane .site-header {{
    flex-shrink: 0;
  }}
  /* Divider */
  .divider {{
    width: 5px;
    background: #e8d5b7;
    cursor: col-resize;
    flex-shrink: 0;
    transition: background .15s;
    position: relative;
  }}
  .divider:hover, .divider.dragging {{ background: #c2660a; }}
  .divider::after {{
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 3px;
    height: 40px;
    background: #a07850;
    border-radius: 2px;
    opacity: .5;
  }}
  /* Right pane */
  .right-pane {{
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 200px;
    background: #f0e6d8;
    overflow: hidden;
  }}
  .pdf-toolbar {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 7px 16px;
    background: #fef3e2;
    border-bottom: 1px solid #e8d5b7;
    flex-shrink: 0;
  }}
  .pdf-label {{ font-size: .8rem; color: #8a6a50; }}
  .pdf-open-btn {{
    font-size: .78rem;
    color: #c2660a;
    text-decoration: none;
    padding: 4px 12px;
    border: 1px solid #e8963a;
    border-radius: 12px;
    transition: all .2s;
    font-weight: 600;
  }}
  .pdf-open-btn:hover {{ background: #e8963a; color: #fff; }}
  .pdf-iframe {{
    flex: 1;
    width: 100%;
    border: none;
    background: #fff;
  }}
  .no-pdf {{
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #c8a882;
    font-size: 1rem;
  }}
  /* ── Left pane inner ── */
  .left-inner {{
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
  }}
  .paper-card {{
    display: none;
    flex-direction: column;
    height: 100%;
    animation: fadeIn .25s ease;
  }}
  .paper-card.active {{ display: flex; }}
  @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
  /* ── Card header ── */
  .card-header {{
    padding: 14px 24px;
    background: #fef3e2;
    border-bottom: 1px solid #e8d5b7;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .card-meta {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: .75rem;
    font-weight: 600;
  }}
  .badge-arxiv {{ background: #fde8c8; color: #7c4a1e; border: 1px solid #e8963a; }}
  .badge-ms {{ background: #e8f5e8; color: #2d6a2d; border: 1px solid #7ec87e; }}
  .badge-date {{ background: #f5e6d8; color: #8a4a1e; border: 1px solid #c8956a; }}
  .badge-kw {{ background: #fef0dc; color: #a0522d; border: 1px solid #e8b87a; }}
  .card-counter {{ font-size: .8rem; color: #8a6a50; font-weight: 600; }}
  /* ── Card content (left pane only) ── */
  .card-content {{
    padding: 20px 24px 16px;
    flex: 1;
    overflow-y: auto;
  }}
  .paper-title {{
    font-size: 1.25rem;
    font-weight: 700;
    line-height: 1.5;
    color: #3d2b1f;
    margin-bottom: 6px;
  }}
  .paper-title a {{ color: #7c4a1e; text-decoration: none; }}
  .paper-title a:hover {{ color: #c2660a; text-decoration: underline; }}
  .title-zh {{ font-size: 1rem; color: #8a6a50; margin-bottom: 10px; }}
  .authors {{ font-size: .85rem; color: #a07850; margin-bottom: 18px; }}
  /* ── Tabs ── */
  .section-tabs {{ display: flex; gap: 8px; margin-bottom: 16px; }}
  .tab-btn {{
    padding: 6px 18px;
    border-radius: 20px;
    border: 1px solid #e8d5b7;
    background: #fef3e2;
    color: #8a6a50;
    cursor: pointer;
    font-size: .85rem;
    transition: all .2s;
  }}
  .tab-btn.active {{ background: #c2660a; color: #fff8f0; border-color: #c2660a; }}
  .tab-btn:hover:not(.active) {{ background: #fde8c8; border-color: #e8963a; }}
  .tab-content {{ animation: fadeIn .25s ease; }}
  .tab-content.hidden {{ display: none; }}
  .abstract-box {{
    background: #fef3e2;
    border-left: 3px solid #e8963a;
    border-radius: 0 8px 8px 0;
    padding: 14px 18px;
    font-size: .9rem;
    line-height: 1.8;
    color: #4a3020;
  }}
  .summary-section {{ margin-bottom: 18px; }}
  .summary-label {{
    display: inline-block;
    font-size: .78rem;
    font-weight: 700;
    color: #c2660a;
    margin-bottom: 6px;
    letter-spacing: .05em;
    text-transform: uppercase;
  }}
  .summary-section p {{
    font-size: .9rem;
    line-height: 1.8;
    color: #4a3020;
    background: #fef3e2;
    padding: 10px 14px;
    border-radius: 8px;
    border: 1px solid #e8d5b7;
  }}
  /* ── Bottom navigation bar (inside left pane) ── */
  .nav-bar {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px;
    background: #fef3e2;
    border-top: 1px solid #e8d5b7;
    flex-shrink: 0;
    gap: 8px;
  }}
  .nav-btn {{
    padding: 6px 18px;
    border-radius: 6px;
    border: 1px solid #e8963a;
    background: #fff8f0;
    color: #7c4a1e;
    cursor: pointer;
    font-size: .85rem;
    font-weight: 700;
    transition: all .2s;
  }}
  .nav-btn:hover:not(:disabled) {{ background: #e8963a; color: #fff; }}
  .nav-btn:disabled {{ opacity: .3; cursor: default; }}
  .nav-center {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    flex: 1;
    min-width: 0;
  }}
  .nav-dots {{
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    justify-content: center;
  }}
  .nav-dot {{
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #e8d5b7;
    cursor: pointer;
    transition: all .2s;
    border: 2px solid transparent;
    flex-shrink: 0;
  }}
  .nav-dot.active {{ background: #c2660a; border-color: #c2660a; transform: scale(1.2); }}
  .paper-index {{
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    justify-content: center;
    max-height: 56px;
    overflow-y: auto;
  }}
  .index-btn {{
    padding: 3px 10px;
    border-radius: 4px;
    border: 1px solid #e8d5b7;
    background: #fff8f0;
    color: #8a6a50;
    cursor: pointer;
    font-size: .75rem;
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    transition: all .15s;
  }}
  .index-btn:hover, .index-btn.active {{
    background: #c2660a;
    color: #fff8f0;
    border-color: #c2660a;
  }}
  /* \u2500\u2500 Reading progress bar \u2500\u2500 */
  .progress-bar {{
    height: 3px;
    background: linear-gradient(90deg, #c2660a, #e8963a);
    width: 0%;
    transition: width .1s;
    flex-shrink: 0;
  }}
  /* \u2500\u2500 Search box \u2500\u2500 */
  .search-bar {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    background: #fef3e2;
    border-bottom: 1px solid #e8d5b7;
    flex-shrink: 0;
  }}
  .search-input {{
    flex: 1;
    padding: 5px 12px;
    border-radius: 20px;
    border: 1px solid #e8d5b7;
    background: #fff8f0;
    color: #3d2b1f;
    font-size: .85rem;
    outline: none;
    transition: border .2s;
  }}
  .search-input:focus {{ border-color: #c2660a; }}
  .search-input::placeholder {{ color: #c8a882; }}
  .search-count {{ font-size: .75rem; color: #8a6a50; white-space: nowrap; }}
  /* \u2500\u2500 Favorite button \u2500\u2500 */
  .fav-btn {{
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1.1rem;
    padding: 2px 6px;
    border-radius: 6px;
    transition: transform .15s;
    line-height: 1;
  }}
  .fav-btn:hover {{ transform: scale(1.2); }}
  .fav-btn.starred {{ filter: drop-shadow(0 0 4px #e8963a); }}
  /* \u2500\u2500 Dark mode \u2500\u2500 */
  body.dark {{
    background: #1a1208;
    color: #e8d5b7;
  }}
  body.dark .left-pane {{ background: #1a1208; }}
  body.dark .paper-card {{ background: #241a0e; }}
  body.dark .card-header {{ background: #1e1409; border-color: #3d2b1f; }}
  body.dark .card-content {{ background: #241a0e; }}
  body.dark .abstract-box {{ background: #1e1409; border-color: #7c4a1e; color: #d4b896; }}
  body.dark .summary-section p {{ background: #1e1409; border-color: #3d2b1f; color: #d4b896; }}
  body.dark .nav-bar {{ background: #1e1409; border-color: #3d2b1f; }}
  body.dark .nav-btn {{ background: #241a0e; color: #e8963a; border-color: #7c4a1e; }}
  body.dark .nav-dot {{ background: #3d2b1f; }}
  body.dark .index-btn {{ background: #241a0e; color: #c8a882; border-color: #3d2b1f; }}
  body.dark .tab-btn {{ background: #1e1409; color: #c8a882; border-color: #3d2b1f; }}
  body.dark .search-bar {{ background: #1e1409; border-color: #3d2b1f; }}
  body.dark .search-input {{ background: #241a0e; color: #e8d5b7; border-color: #3d2b1f; }}
  body.dark .divider {{ background: #3d2b1f; }}
  body.dark .paper-title a {{ color: #e8963a; }}
  body.dark .title-zh {{ color: #c8a882; }}
  body.dark .authors {{ color: #a07850; }}
  /* \u2500\u2500 Dark mode toggle btn \u2500\u2500 */
  .dark-toggle {{
    background: rgba(255,255,255,.15);
    border: 1px solid rgba(255,255,255,.25);
    border-radius: 20px;
    padding: 3px 10px;
    cursor: pointer;
    font-size: .78rem;
    color: #fde8c8;
    transition: all .2s;
    white-space: nowrap;
  }}
  .dark-toggle:hover {{ background: rgba(255,255,255,.25); }}
  /* \u2500\u2500 No-results message \u2500\u2500 */
  .no-results {{
    display: none;
    padding: 40px 20px;
    text-align: center;
    color: #a07850;
    font-size: .95rem;
  }}
  /* \u2500\u2500 Share mode arXiv pane \u2500\u2500 */
  .share-arxiv-pane {{
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #f0e6d8;
  }}
  .share-arxiv-inner {{
    text-align: center;
    padding: 32px 24px;
    max-width: 360px;
  }}
  .share-arxiv-icon {{
    font-size: 3rem;
    margin-bottom: 16px;
  }}
  .share-arxiv-title {{
    font-size: .95rem;
    color: #3d2b1f;
    font-weight: 600;
    line-height: 1.5;
    margin-bottom: 24px;
  }}
  .share-arxiv-btns {{
    display: flex;
    flex-direction: column;
    gap: 12px;
    align-items: center;
  }}
  .share-btn-primary {{
    display: inline-block;
    padding: 10px 28px;
    border-radius: 24px;
    background: #c2660a;
    color: #fff8f0;
    text-decoration: none;
    font-weight: 700;
    font-size: .9rem;
    transition: background .2s;
    width: 100%;
  }}
  .share-btn-primary:hover {{ background: #a0520a; }}
  .share-btn-secondary {{
    display: inline-block;
    padding: 9px 28px;
    border-radius: 24px;
    border: 1px solid #e8963a;
    color: #7c4a1e;
    text-decoration: none;
    font-size: .9rem;
    font-weight: 600;
    transition: all .2s;
    width: 100%;
    background: #fff8f0;
  }}
  .share-btn-secondary:hover {{ background: #fde8c8; }}
  body.dark .share-arxiv-pane {{ background: #1a1208; }}
  body.dark .share-arxiv-title {{ color: #e8d5b7; }}
  body.dark .share-btn-secondary {{ background: #241a0e; color: #e8963a; border-color: #7c4a1e; }}
</style>
<!-- MathJax for LaTeX rendering -->
<script>
  MathJax = {{
    tex: {{
      inlineMath: [['$', '$'], ['\\(', '\\)']],
      displayMath: [['$$', '$$'], ['\\[', '\\]']],
      packages: {{'[+]': ['textmacros']}}
    }},
    options: {{ skipHtmlTags: ['script','noscript','style','textarea','pre'] }},
    startup: {{ typeset: false }}
  }};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js" async></script>
</head>
<body>
<div class="split-container">
  <!-- Left pane: paper info carousel (header inside) -->
  <div class="left-pane" id="left-pane">
    <header class="site-header">
      <div>
        <h1>📄 AI 论文日报</h1>
        <div class="subtitle">{today} · {total} 篇精选论文</div>
      </div>
      <div class="header-right">
        <span>关键词: {', '.join(config.get('keywords', [])[:4])}</span>
        <button class="dark-toggle" onclick="toggleDark()" id="dark-btn">&#127769; 暗色</button>
      </div>
    </header>
    <!-- Reading progress bar -->
    <div class="progress-bar" id="progress-bar"></div>
    <!-- Search bar -->
    <div class="search-bar">
      <input class="search-input" id="search-input" type="text" placeholder="🔍 搜索论文标题、作者、关键词…" oninput="doSearch(this.value)">
      <span class="search-count" id="search-count">{total} 篇</span>
    </div>
    <div class="no-results" id="no-results">🔍 没有找到匹配的论文</div>
    <div class="left-inner" id="left-inner">
      {cards_html}
    </div>
    <!-- Bottom nav -->
    <div class="nav-bar">
      <button class="nav-btn" id="btn-prev" onclick="navigate(-1)">← 上一篇</button>
      <div class="nav-center">
        <div class="nav-dots" id="nav-dots">
          {''.join(f'<div class="nav-dot {"active" if i == 0 else ""}" onclick="goTo({i})" title="{papers[i].get(chr(116)+chr(105)+chr(116)+chr(108)+chr(101),chr(80))[:30]}"></div>' for i in range(total))}
        </div>
        <div class="paper-index">
          {''.join(f'<button class="index-btn {"active" if i == 0 else ""}" id="idx-{i}" onclick="goTo({i})">{i+1}. {papers[i].get(chr(116)+chr(105)+chr(116)+chr(108)+chr(101),"")[:28]}{"…" if len(papers[i].get(chr(116)+chr(105)+chr(116)+chr(108)+chr(101),""))>28 else ""}</button>' for i in range(total))}
        </div>
      </div>
      <button class="nav-btn" id="btn-next" onclick="navigate(1)">下一篇 →</button>
    </div>
  </div>

  <!-- Draggable divider -->
  <div class="divider" id="divider"></div>

  <!-- Right pane: full-height PDF (local) or arXiv link panel (share mode) -->
  <div class="right-pane" id="right-pane">
    {'<div class="share-arxiv-pane" id="share-arxiv-pane"><div class="share-arxiv-inner"><div class="share-arxiv-icon">📄</div><p class="share-arxiv-title" id="share-arxiv-title"></p><div class="share-arxiv-btns"><a class="share-btn-primary" id="share-btn-abs" href="#" target="_blank">🔗 查看摘要页</a><a class="share-btn-secondary" id="share-btn-pdf" href="#" target="_blank">⬇ 下载 PDF</a></div></div></div>' if share_mode else '<iframe id="pdf-iframe" class="pdf-iframe" src="" title="PDF Preview"></iframe><div class="no-pdf" id="no-pdf" style="display:none">📄 该论文 PDF 未找到</div>'}
  </div>
</div>

<script>
  var current = 0;
  var total = {total};
  var pdfUrls = {pdf_urls_js};
  var arxivUrls = {arxiv_urls_js};
  var shareMode = {'true' if share_mode else 'false'};
  var visibleCards = [];  // indices of cards visible after search

  // ── PDF / arXiv pane ──
  function loadPdf(n) {{
    if (shareMode) {{
      var info = arxivUrls[n] || {{}};
      var titleEl = document.getElementById('share-arxiv-title');
      var absBtn = document.getElementById('share-btn-abs');
      var pdfBtn = document.getElementById('share-btn-pdf');
      var card = document.getElementById('card-' + n);
      if (titleEl) titleEl.textContent = card ? (card.dataset.title || '') : '';
      if (absBtn) absBtn.href = info.url || '#';
      if (pdfBtn) pdfBtn.href = info.pdf || '#';
      return;
    }}
    var url = pdfUrls[n] || '';
    var iframe = document.getElementById('pdf-iframe');
    var noPdf = document.getElementById('no-pdf');
    if (url) {{
      iframe.style.display = 'block';
      noPdf.style.display = 'none';
      iframe.src = url;
    }} else {{
      iframe.style.display = 'none';
      noPdf.style.display = 'flex';
    }}
  }}

  // ── Navigation ──
  function goTo(n) {{
    document.getElementById('card-' + current).classList.remove('active');
    var prevDot = document.querySelectorAll('.nav-dot')[current];
    if (prevDot) prevDot.classList.remove('active');
    var idx = document.getElementById('idx-' + current);
    if (idx) idx.classList.remove('active');

    current = n;
    document.getElementById('card-' + current).classList.add('active');
    var newDot = document.querySelectorAll('.nav-dot')[current];
    if (newDot) newDot.classList.add('active');
    var idxNew = document.getElementById('idx-' + current);
    if (idxNew) {{ idxNew.classList.add('active'); idxNew.scrollIntoView({{behavior:'smooth',block:'nearest',inline:'center'}}); }}

    var pos = visibleCards.indexOf(n);
    document.getElementById('btn-prev').disabled = (pos <= 0);
    document.getElementById('btn-next').disabled = (pos < 0 || pos >= visibleCards.length - 1);

    loadPdf(n);
    updateProgress();
    if (window.MathJax && MathJax.typesetPromise) {{
      MathJax.typesetPromise([document.getElementById('card-' + n)]).catch(function(){{}});
    }}
  }}

  function navigate(dir) {{
    var pos = visibleCards.indexOf(current);
    if (pos < 0) return;
    var next = pos + dir;
    if (next >= 0 && next < visibleCards.length) goTo(visibleCards[next]);
  }}

  function switchTab(cardIdx, tab) {{
    var card = document.getElementById('card-' + cardIdx);
    card.querySelectorAll('.tab-content').forEach(function(t) {{ t.classList.add('hidden'); }});
    var el = document.getElementById('tab-' + cardIdx + '-' + tab);
    if (el) el.classList.remove('hidden');
    card.querySelectorAll('.tab-btn').forEach(function(b) {{ b.classList.remove('active'); }});
    event.target.classList.add('active');
  }}

  // ── Progress bar ──
  function updateProgress() {{
    var pos = visibleCards.indexOf(current);
    var pct = visibleCards.length > 1 ? (pos / (visibleCards.length - 1)) * 100 : 100;
    document.getElementById('progress-bar').style.width = pct + '%';
  }}

  // ── Search ──
  var allCards = [];
  document.querySelectorAll('.paper-card').forEach(function(c, i) {{ allCards.push(i); }});
  visibleCards = allCards.slice();

  function doSearch(q) {{
    q = q.trim().toLowerCase();
    var matched = [];
    for (var i = 0; i < total; i++) {{
      var card = document.getElementById('card-' + i);
      var title = (card.dataset.title || '').toLowerCase();
      var authors = (card.dataset.authors || '').toLowerCase();
      var kw = (card.dataset.kw || '').toLowerCase();
      if (!q || title.includes(q) || authors.includes(q) || kw.includes(q)) {{
        matched.push(i);
      }}
    }}
    visibleCards = matched;
    document.getElementById('search-count').textContent = matched.length + ' 篇';
    document.getElementById('no-results').style.display = matched.length === 0 ? 'block' : 'none';
    document.getElementById('left-inner').style.display = matched.length === 0 ? 'none' : '';

    // Update index buttons visibility
    for (var j = 0; j < total; j++) {{
      var btn = document.getElementById('idx-' + j);
      if (btn) btn.style.display = matched.indexOf(j) >= 0 ? '' : 'none';
    }}

    if (matched.length > 0) {{
      var target = matched.indexOf(current) >= 0 ? current : matched[0];
      goTo(target);
    }}
  }}

  // ── Favorites (localStorage) ──
  var FAV_KEY = 'paper_favs_{today}';
  var favs = JSON.parse(localStorage.getItem(FAV_KEY) || '[]');

  function toggleFav(n) {{
    var btn = document.getElementById('fav-' + n);
    var pos = favs.indexOf(n);
    if (pos >= 0) {{
      favs.splice(pos, 1);
      btn.textContent = '☆';
      btn.classList.remove('starred');
      btn.title = '\u6536\u85cf';
    }} else {{
      favs.push(n);
      btn.textContent = '★';
      btn.classList.add('starred');
      btn.title = '\u5df2\u6536\u85cf\uff0c\u70b9\u51fb\u53d6\u6d88';
    }}
    localStorage.setItem(FAV_KEY, JSON.stringify(favs));
  }}

  function restoreFavs() {{
    favs.forEach(function(n) {{
      var btn = document.getElementById('fav-' + n);
      if (btn) {{ btn.textContent = '★'; btn.classList.add('starred'); }}
    }});
  }}

  // ── Dark mode ──
  var darkKey = 'paper_dark_mode';
  function toggleDark() {{
    var isDark = document.body.classList.toggle('dark');
    localStorage.setItem(darkKey, isDark ? '1' : '0');
    document.getElementById('dark-btn').innerHTML = isDark ? '&#9728;&#65039; \u4eae\u8272' : '&#127769; \u6697\u8272';
  }}
  function restoreDark() {{
    if (localStorage.getItem(darkKey) === '1') {{
      document.body.classList.add('dark');
      document.getElementById('dark-btn').innerHTML = '&#9728;&#65039; \u4eae\u8272';
    }}
  }}

  // ── Draggable divider ──
  var divider = document.getElementById('divider');
  var leftPane = document.getElementById('left-pane');
  var container = document.querySelector('.split-container');
  var isDragging = false;

  divider.addEventListener('mousedown', function(e) {{
    isDragging = true;
    divider.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  }});
  document.addEventListener('mousemove', function(e) {{
    if (!isDragging) return;
    var rect = container.getBoundingClientRect();
    var newLeft = Math.max(280, Math.min(rect.width - 280, e.clientX - rect.left));
    leftPane.style.width = newLeft + 'px';
  }});
  document.addEventListener('mouseup', function() {{
    if (!isDragging) return;
    isDragging = false;
    divider.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }});

  // ── Keyboard ──
  document.addEventListener('keydown', function(e) {{
    if (document.getElementById('search-input') === document.activeElement) return;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') navigate(1);
    if (e.key === 'ArrowLeft'  || e.key === 'ArrowUp')   navigate(-1);
  }});

  // ── Init ──
  restoreDark();
  restoreFavs();
  updateProgress();
  document.getElementById('btn-prev').disabled = true;
  if (total <= 1) document.getElementById('btn-next').disabled = true;
  loadPdf(0);
  window.addEventListener('load', function() {{
    if (window.MathJax && MathJax.typesetPromise) {{
      MathJax.typesetPromise([document.getElementById('card-0')]).catch(function(){{}});
    }}
  }});
</script>
</body>
</html>'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    logger.info(f"Generated daily HTML report: {output_path}")
    return output_path


def main():
    config = load_config(os.path.join(project_root, 'config.yaml'))
    setup_logging = __import__('src.utils', fromlist=['setup_logging']).setup_logging
    setup_logging(config)

    from src.filter_papers import load_filtered_papers
    papers = load_filtered_papers()
    path = generate_daily_html(config, papers)
    if path:
        print(f"HTML report generated: {path}")


if __name__ == '__main__':
    main()
