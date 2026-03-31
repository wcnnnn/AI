"""Download and extract images from papers for Obsidian notes"""
import os
import sys
import json
import logging
import requests
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
from src.utils import load_config, ensure_dir

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


def download_pdf_to_vault(paper, config):
    """
    Download paper PDF to Obsidian vault

    Args:
        paper: Paper dictionary
        config: Configuration dictionary

    Returns:
        Path to downloaded PDF file
    """
    pdf_url = paper.get('pdf_url', '')
    if not pdf_url:
        return None

    obsidian_config = config.get('obsidian', {})
    vault_path = obsidian_config.get('vault_path', '')
    pdf_folder = obsidian_config.get('pdf_folder', '论文库')

    if not vault_path:
        logger.warning("Vault path not configured")
        return None

    # Create PDF directory
    pdf_dir = os.path.join(vault_path, pdf_folder)
    ensure_dir(pdf_dir)

    # Determine filename
    arxiv_id = paper.get('arxiv_id', '')
    title = paper.get('title', 'untitled')[:50]

    if arxiv_id:
        pdf_filename = f"{arxiv_id}.pdf"
    else:
        # Sanitize title for filename
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)
        safe_title = safe_title.replace(' ', '_')[:50]
        pdf_filename = f"{safe_title}.pdf"

    pdf_path = os.path.join(pdf_dir, pdf_filename)

    # Check if already downloaded
    if os.path.exists(pdf_path):
        logger.debug(f"PDF already exists: {pdf_filename}")
        return pdf_path

    try:
        logger.info(f"Downloading PDF: {pdf_filename}")
        response = requests.get(pdf_url, headers=HEADERS, timeout=120, stream=True)

        if response.status_code == 200:
            with open(pdf_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Downloaded: {pdf_filename}")
            return pdf_path
        else:
            logger.warning(f"Failed to download PDF: {response.status_code}")
    except Exception as e:
        logger.error(f"Error downloading PDF: {e}")

    return None


def extract_main_figure_pymupdf(pdf_path, output_dir, prefix="fig"):
    """
    Extract main figures from PDF using PyMuPDF (fitz).
    Renders each page and extracts the largest image block as the main figure.

    Args:
        pdf_path: Path to PDF file
        output_dir: Directory to save extracted images
        prefix: Filename prefix for extracted images

    Returns:
        List of extracted image paths
    """
    extracted_images = []
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)

        def _is_icon_like(width, height, img_bytes):
            """判断是否为图标/装饰图（非论文主图）"""
            # 图标通常接近正方形且尺寸不大
            if width < 500 and height < 500:
                ratio = max(width, height) / max(min(width, height), 1)
                if ratio < 1.5:  # 宽高比接近1:1
                    return True
            # 图片过小
            if width * height < 150000:
                return True
            return False

        def _page_has_figures(page):
            """检测页面是否包含有意义的图形内容"""
            # 统计路径数量（矢量图）
            drawings = page.get_drawings()
            if len(drawings) > 10:
                return True
            # 统计嵌入位图
            images = page.get_images()
            if images:
                for img in images:
                    xref = img[0]
                    try:
                        base_image = doc.extract_image(xref)
                        w = base_image.get("width", 0)
                        h = base_image.get("height", 0)
                        if w > 300 and h > 200 and not _is_icon_like(w, h, None):
                            return True
                    except Exception:
                        pass
            return False

        # 方案A：提取页面中嵌入的位图图片（原始分辨率，非矢量）
        for page_num in range(min(len(doc), 8)):  # 只处理前8页
            page = doc[page_num]
            image_list = page.get_images(full=True)
            best_img = None
            best_size = 0

            for img_index, img in enumerate(image_list):
                xref = img[0]
                try:
                    base_image = doc.extract_image(xref)
                    img_bytes = base_image["image"]
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    size = width * height
                    # 跳过小图和图标类图片
                    if _is_icon_like(width, height, img_bytes):
                        continue
                    if size > best_size:
                        best_size = size
                        best_img = (img_bytes, base_image["ext"])
                except Exception:
                    continue

            if best_img:
                img_bytes, ext = best_img
                if ext in ('jpeg', 'jpg'):
                    ext = 'jpg'
                elif ext not in ('png', 'gif', 'webp'):
                    ext = 'png'
                img_filename = f"{prefix}_p{page_num+1}_main.{ext}"
                img_path = os.path.join(output_dir, img_filename)
                with open(img_path, 'wb') as f:
                    f.write(img_bytes)
                if os.path.getsize(img_path) > 5000:
                    extracted_images.append(img_path)
                    logger.debug(f"Extracted main figure from page {page_num+1} (embedded bitmap)")

        # 方案B：渲染含有图形内容的页面（适用于矢量图，或方案A失败时）
        if len(extracted_images) < 2:
            # 找出含有图形内容的页面，优先渲染
            figure_pages = []
            for page_num in range(min(len(doc), 10)):
                page = doc[page_num]
                if _page_has_figures(page):
                    figure_pages.append(page_num)

            # 如果没找到含图页面，fallback到第1-5页
            if not figure_pages:
                figure_pages = list(range(1, min(len(doc), 6)))

            for page_num in figure_pages[:5]:
                page = doc[page_num]
                mat = fitz.Matrix(2.0, 2.0)  # 2x缩放 = 约144 DPI
                pix = page.get_pixmap(matrix=mat)
                img_filename = f"{prefix}_p{page_num+1}_render.png"
                img_path = os.path.join(output_dir, img_filename)
                pix.save(img_path)
                if os.path.exists(img_path) and os.path.getsize(img_path) > 30000:
                    extracted_images.append(img_path)
                    logger.debug(f"Rendered page {page_num+1} as figure (has drawings)")
                if len(extracted_images) >= 5:
                    break

        doc.close()

        if extracted_images:
            logger.info(f"Extracted {len(extracted_images)} main figures using PyMuPDF")
    except ImportError:
        logger.debug("PyMuPDF not installed, skipping fitz method")
    except Exception as e:
        logger.debug(f"PyMuPDF method failed: {e}")

    return extracted_images


def extract_images_from_pdf_advanced(pdf_path, output_dir, prefix="fig"):
    """
    Extract images from PDF using multiple methods

    Args:
        pdf_path: Path to PDF file
        output_dir: Directory to save extracted images
        prefix: Filename prefix for extracted images

    Returns:
        List of extracted image paths
    """
    extracted_images = []

    if not os.path.exists(pdf_path):
        logger.warning(f"PDF not found: {pdf_path}")
        return extracted_images

    ensure_dir(output_dir)

    # Try method 0: PyMuPDF (best quality, no external tools needed)
    extracted_images = extract_main_figure_pymupdf(pdf_path, output_dir, prefix)
    if extracted_images:
        return extracted_images

    # Try method 1: Using pdfimages (poppler-utils command line tool)
    try:
        import subprocess
        cmd = ['pdfimages', '-j', '-png', pdf_path, os.path.join(output_dir, prefix)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            # Check for extracted images
            for f in os.listdir(output_dir):
                if f.startswith(prefix) and f.endswith('.png'):
                    img_path = os.path.join(output_dir, f)
                    # Skip very small images (likely icons)
                    if os.path.getsize(img_path) > 5000:
                        extracted_images.append(img_path)
            if extracted_images:
                logger.info(f"Extracted {len(extracted_images)} images using pdfimages")
                return extracted_images
    except Exception as e:
        logger.debug(f"pdfimages method failed: {e}")

    # Try method 2: Using pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)

        for page_num, page in enumerate(reader.pages):
            if '/XObject' in page['/Resources']:
                xObjects = page['/Resources']['/XObject'].get_object()
                for obj in xObjects:
                    if xObjects[obj]['/Subtype'] == '/Image':
                        try:
                            # Get image data
                            data = xObjects[obj].get_data()

                            # Determine image format
                            if '/Filter' in xObjects[obj]:
                                filter_type = xObjects[obj]['/Filter']
                                if '/DCTDecode' in filter_type:
                                    ext = '.jpg'
                                elif '/JPXDecode' in filter_type:
                                    ext = '.jp2'
                                elif '/FlateDecode' in filter_type:
                                    ext = '.png'
                                else:
                                    ext = '.png'
                            else:
                                ext = '.png'

                            img_filename = f"{prefix}_{page_num+1}_{len(extracted_images)}{ext}"
                            img_path = os.path.join(output_dir, img_filename)

                            with open(img_path, 'wb') as f:
                                f.write(data)

                            if os.path.getsize(img_path) > 5000:
                                extracted_images.append(img_path)
                        except Exception as e:
                            logger.debug(f"Error extracting image from page {page_num}: {e}")
                            continue

        if extracted_images:
            logger.info(f"Extracted {len(extracted_images)} images using pypdf")
            return extracted_images

    except Exception as e:
        logger.debug(f"pypdf method failed: {e}")

    # Try method 3: Using pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                images = page.images
                for img_idx, img in enumerate(images):
                    try:
                        # Get image bbox
                        x0, top, x1, bottom = img['x0'], img['top'], img['x1'], img['bottom']
                        width = int(x1 - x0)
                        height = int(bottom - top)

                        # Skip very small images
                        if width < 200 or height < 200:
                            continue

                        # Crop and save the image
                        crop = page.crop((x0, top, x1, bottom))
                        img_obj = crop.to_image(resolution=150)

                        if img_obj:
                            img_filename = f"{prefix}_{page_num+1}_{img_idx}.png"
                            img_path = os.path.join(output_dir, img_filename)
                            img_obj.save(img_path)

                            if os.path.exists(img_path) and os.path.getsize(img_path) > 5000:
                                extracted_images.append(img_path)
                    except Exception as e:
                        logger.debug(f"Error extracting image from page {page_num}: {e}")
                        continue

        if extracted_images:
            logger.info(f"Extracted {len(extracted_images)} images using pdfplumber")
            return extracted_images

    except Exception as e:
        logger.debug(f"pdfplumber method failed: {e}")

    # If no images extracted, create a thumbnail from first page as fallback
    if not extracted_images:
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) > 0:
                    first_page = pdf.pages[0]
                    img_obj = first_page.to_image(resolution=100)

                    if img_obj:
                        thumb_filename = f"{prefix}_cover.png"
                        thumb_path = os.path.join(output_dir, thumb_filename)
                        img_obj.save(thumb_path)

                        if os.path.exists(thumb_path):
                            extracted_images.append(thumb_path)
                            logger.info("Created cover thumbnail as fallback")
        except Exception as e:
            logger.debug(f"Fallback thumbnail failed: {e}")

    logger.info(f"Total images extracted: {len(extracted_images)}")
    return extracted_images


def download_project_page_images(paper, config):
    """
    Try to download images from project page

    Args:
        paper: Paper dictionary
        config: Configuration dictionary

    Returns:
        List of image paths
    """
    images = []
    obsidian_config = config.get('obsidian', {})
    vault_path = obsidian_config.get('vault_path', '')
    images_folder = obsidian_config.get('images_folder', '论文图片')

    if not vault_path:
        return images

    # Create images directory
    img_dir = os.path.join(vault_path, images_folder)
    ensure_dir(img_dir)

    # Try to find project page URL
    project_urls = []

    # Check comment field
    comment = paper.get('comment', '')
    if comment:
        urls = re.findall(r'https?://[^\s<>"]+', comment)
        project_urls.extend(urls)

    # Try arXiv project page
    arxiv_id = paper.get('arxiv_id', '')
    if arxiv_id:
        try:
            arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
            response = requests.get(arxiv_url, headers=HEADERS, timeout=10)
            if response.status_code == 200:
                # Look for project page link
                project_match = re.search(r'https?://[^\s<>"]+\.github\.io[^\s<>"]*', response.text)
                if project_match:
                    project_urls.append(project_match.group())

                project_match2 = re.search(r'https?://[^\s<>"]+\.github\.com/[^\s<>"]+', response.text)
                if project_match2:
                    project_urls.append(project_match2.group())
        except Exception as e:
            logger.debug(f"Error fetching arXiv page: {e}")

    # Fetch images from project pages
    for project_url in project_urls[:1]:
        try:
            logger.info(f"Fetching project page: {project_url}")
            response = requests.get(project_url, headers=HEADERS, timeout=10)
            if response.status_code == 200:
                # Find image URLs
                img_patterns = re.findall(r'https?://[^\s<>"]+\.(?:png|jpg|jpeg|gif|webp)[^\s<>"]*', response.text)

                paper_title = paper.get('title', 'paper')[:30].replace(' ', '_')
                for idx, img_url in enumerate(img_patterns[:3]):
                    img_filename = f"{paper_title}_{idx+1}.{img_url.split('.')[-1]}"
                    img_path = os.path.join(img_dir, img_filename)

                    if os.path.exists(img_path):
                        images.append(img_path)
                        continue

                    try:
                        img_response = requests.get(img_url, headers=HEADERS, timeout=30)
                        if img_response.status_code == 200:
                            with open(img_path, 'wb') as f:
                                f.write(img_response.content)
                            images.append(img_path)
                            logger.info(f"Downloaded project image: {img_filename}")
                    except Exception as e:
                        logger.debug(f"Error downloading project image: {e}")
        except Exception as e:
            logger.debug(f"Error fetching project page: {e}")

    return images


def process_paper_images(paper, config):
    """
    Process all images for a single paper

    Args:
        paper: Paper dictionary
        config: Configuration dictionary

    Returns:
        Dictionary with paths to PDF and images
    """
    obsidian_config = config.get('obsidian', {})
    vault_path = obsidian_config.get('vault_path', '')
    images_folder = obsidian_config.get('images_folder', '论文图片')

    result = {
        'pdf_path': None,
        'extracted_images': [],
        'project_images': []
    }

    if not vault_path:
        return result

    # Download PDF
    pdf_path = download_pdf_to_vault(paper, config)
    result['pdf_path'] = pdf_path

    if not pdf_path:
        return result

    # Create image output directory using paper title
    paper_title = paper.get('title', 'paper')[:30].replace(' ', '_').replace('/', '-')
    safe_title = re.sub(r'[<>:"\\|?*]', '_', paper_title)
    img_dir = os.path.join(vault_path, images_folder, safe_title)
    ensure_dir(img_dir)

    # Extract images from PDF
    result['extracted_images'] = extract_images_from_pdf_advanced(pdf_path, img_dir, prefix="fig")

    # Try to get project page images
    result['project_images'] = download_project_page_images(paper, config)

    return result


def process_all_papers_images(config, papers):
    """
    Process images for all papers

    Args:
        config: Configuration dictionary
        papers: List of paper dictionaries

    Returns:
        Updated list of papers with image paths
    """
    for paper in papers:
        logger.info(f"Processing images for: {paper.get('title', '')[:40]}...")

        image_result = process_paper_images(paper, config)

        # Store paths in paper object
        all_images = []
        if image_result.get('pdf_path'):
            all_images.append(image_result['pdf_path'])
        all_images.extend(image_result.get('extracted_images', []))
        all_images.extend(image_result.get('project_images', []))

        paper['pdf_path'] = image_result.get('pdf_path')
        paper['images'] = all_images

    logger.info(f"Processed images for {len(papers)} papers")
    return papers


def check_pdf_image_quality(pdf_url, timeout=30):
    """
    Quick pre-check: download only the first ~200KB of a PDF and count
    embedded bitmap images. Returns a score 0-3:
      0 = no detectable bitmaps (likely all-vector / hard to extract)
      1 = only icon-like small bitmaps
      2 = has at least one real figure bitmap
      3 = has multiple real figure bitmaps
    """
    score = 0
    try:
        import fitz
        import tempfile

        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(pdf_url, headers=headers, timeout=timeout,
                                stream=True)
        if response.status_code != 200:
            return score

        # Read only first 300 KB to keep it fast
        chunk_size = 300 * 1024
        data = b""
        for chunk in response.iter_content(chunk_size=8192):
            data += chunk
            if len(data) >= chunk_size:
                break
        response.close()

        if len(data) < 1024:
            return score

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            import io, contextlib
            # Suppress MuPDF stderr noise from truncated PDF
            with contextlib.redirect_stderr(io.StringIO()):
                doc = fitz.open(tmp_path)
            try:
                fitz.TOOLS.mupdf_warnings()  # flush warning buffer silently
            except Exception:
                pass
            real_bitmaps = 0
            icon_bitmaps = 0
            for page_num in range(min(len(doc), 5)):
                page = doc[page_num]
                for img in page.get_images(full=True):
                    xref = img[0]
                    try:
                        base_image = doc.extract_image(xref)
                        w = base_image.get("width", 0)
                        h = base_image.get("height", 0)
                        if w * h < 150000 or (w < 500 and h < 500 and
                                              max(w, h) / max(min(w, h), 1) < 1.5):
                            icon_bitmaps += 1
                        else:
                            real_bitmaps += 1
                    except Exception:
                        continue
            doc.close()

            if real_bitmaps >= 2:
                score = 3
            elif real_bitmaps == 1:
                score = 2
            elif icon_bitmaps > 0:
                score = 1
            else:
                score = 0
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    except ImportError:
        score = 1  # fitz not available, can't check
    except Exception as e:
        logger.debug(f"PDF quality check failed for {pdf_url}: {e}")

    return score


def select_papers_by_image_quality(candidates, arxiv_limit, modelscope_limit,
                                   config, timeout=25):
    """
    From a larger candidate list, download-peek each PDF and rank by image
    quality, then return the best arxiv_limit arXiv + modelscope_limit
    ModelScope papers.

    Args:
        candidates: List of paper dicts (already relevance-sorted)
        arxiv_limit: How many arXiv papers to keep
        modelscope_limit: How many ModelScope papers to keep
        config: Config dict (unused here, kept for signature consistency)
        timeout: Seconds for each HEAD request

    Returns:
        Selected list of papers
    """
    logger.info(f"Pre-checking image quality for {len(candidates)} candidate papers...")

    arxiv_candidates = [p for p in candidates if p.get('source_type') == 'arXiv']
    ms_candidates = [p for p in candidates if p.get('source_type') != 'arXiv']

    def score_group(group, limit):
        if len(group) <= limit:
            return group  # nothing to trim

        scored = []
        for paper in group:
            pdf_url = paper.get('pdf_url', '')
            if not pdf_url:
                scored.append((0, paper))
                continue
            q = check_pdf_image_quality(pdf_url, timeout=timeout)
            logger.info(f"  Image quality {q}/3: {paper.get('title', '')[:55]}...")
            scored.append((q, paper))

        # Sort by (quality DESC, relevance DESC)
        scored.sort(key=lambda x: (x[0], x[1].get('relevance', 0)), reverse=True)
        return [p for _, p in scored[:limit]]

    arxiv_result = score_group(arxiv_candidates, arxiv_limit)
    ms_result = score_group(ms_candidates, modelscope_limit)

    selected = arxiv_result + ms_result
    logger.info(f"Selected {len(arxiv_result)} arXiv + {len(ms_result)} ModelScope after quality check")
    return selected


def main():
    """Main function for testing"""
    config = load_config('config.yaml')
    setup_logging = __import__('src.utils', fromlist=['setup_logging']).setup_logging
    setup_logging(config)

    # Test with a sample paper
    test_paper = {
        'title': 'Test Paper',
        'arxiv_id': '',
        'pdf_url': '',
        'comment': ''
    }

    result = process_paper_images(test_paper, config)
    print(f"Result: {result}")


if __name__ == '__main__':
    main()
