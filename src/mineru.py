"""
PDF转Markdown模块 - 支持多后端兜底
按优先级: Mineru云 -> Mineru本地 -> pdfplumber(兜底)
"""
import os
import sys
import json
import logging
import warnings
import requests
import time
import re
import base64
from datetime import datetime
from pathlib import Path

# 忽略SSL警告
warnings.filterwarnings('ignore')

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

try:
    from src.utils import load_config, ensure_dir
except ImportError:
    # 模拟缺失函数
    def load_config(path):
        import yaml
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def ensure_dir(path):
        os.makedirs(path, exist_ok=True)

logger = logging.getLogger(__name__)


def get_proxies(config=None):
    """获取代理配置"""
    proxies = {}

    # 先从配置文件获取
    if config:
        proxy_config = config.get('mineru', {}).get('proxy', {})
        http_proxy = proxy_config.get('http', '')
        https_proxy = proxy_config.get('https', '')
        if http_proxy: proxies['http'] = http_proxy
        if https_proxy: proxies['https'] = https_proxy
        if proxies:
            logger.info(f"使用配置文件的代理: {proxies}")
            return proxies

    # 从环境变量获取
    http_proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
    https_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if http_proxy: proxies['http'] = http_proxy
    if https_proxy: proxies['https'] = https_proxy
    if proxies:
        logger.info(f"使用环境变量的代理: {proxies}")

    return proxies if proxies else None


def get_mineru_result(task_id, api_key, proxies, max_retries=60, interval=3):
    """
    轮询获取Mineru解析结果
    新版API: https://mineru.net/api/v4/extract/task/{task_id}

    Returns:
        tuple: (markdown_content, zip_url) - 如果成功返回markdown和zip_url，否则返回(None, None)
    """
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    for i in range(max_retries):
        try:
            response = requests.get(
                f'https://mineru.net/api/v4/extract/task/{task_id}',
                headers=headers,
                proxies=proxies,
                timeout=60,
                verify=False
            )

            if response.status_code == 200:
                data = response.json()
                # 新版API返回的字段是 state
                state = data.get('data', {}).get('state', '')

                # 成功状态是 'done' 或 'completed'
                if state == 'done' or state == 'completed':
                    # 返回markdown内容，或下载zip文件
                    markdown = data.get('data', {}).get('markdown', '')
                    if markdown:
                        return markdown, None

                    # 如果没有直接返回markdown，下载zip文件
                    zip_url = data.get('data', {}).get('full_zip_url', '')
                    if zip_url:
                        logger.info(f"下载zip文件: {zip_url}")

                        # 增加重试机制处理SSL错误
                        max_zip_retries = 5
                        for retry in range(max_zip_retries):
                            try:
                                zip_resp = requests.get(
                                    zip_url,
                                    proxies=proxies,
                                    headers=headers,
                                    timeout=180,
                                    verify=False
                                )
                                if zip_resp.status_code == 200:
                                    # 解压zip获取markdown
                                    import zipfile
                                    import io
                                    with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as z:
                                        # 查找markdown文件
                                        for name in z.namelist():
                                            if name.endswith('.md') or name.endswith('.markdown'):
                                                with z.open(name) as f:
                                                    content = f.read().decode('utf-8')
                                                    logger.info(f"从zip中提取: {name}")
                                                    # 保存zip文件到临时目录
                                                    import tempfile
                                                    temp_dir = tempfile.gettempdir()
                                                    zip_path = os.path.join(temp_dir, f"mineru_{task_id}.zip")
                                                    with open(zip_path, 'wb') as zf:
                                                        zf.write(zip_resp.content)
                                                    logger.info(f"保存zip到: {zip_path}")
                                                    return content, zip_path
                                    logger.error("zip文件中未找到markdown文件")
                                    break
                                else:
                                    logger.error(f"下载zip失败: {zip_resp.status_code}")
                                    break
                            except Exception as e:
                                logger.warning(f"下载zip重试 {retry+1}/{max_zip_retries}: {str(e)[:100]}")
                                if retry < max_zip_retries - 1:
                                    time.sleep(3)
                                continue

                    return None, None

                elif state == 'failed':
                    err_msg = data.get('data', {}).get('err_msg', '未知错误')
                    logger.error(f"Mineru解析失败: {err_msg}")
                    return None
                elif state in ['pending', 'processing', 'running']:
                    logger.info(f"Mineru处理中... ({i+1}/{max_retries}), state={state}")
                    time.sleep(interval)
                    continue
                else:
                    logger.warning(f"Mineru未知状态: {state}, 响应: {data}")

            elif response.status_code == 404:
                logger.error(f"Mineru任务不存在: {task_id}")
                return None
            else:
                logger.warning(f"Mineru状态查询返回: {response.status_code}, {response.text[:100]}")

        except Exception as e:
            logger.error(f"Mineru轮询异常: {str(e)[:200]}")
            time.sleep(interval)

    logger.error(f"Mineru轮询超时，共{max_retries}次")
    return None


def convert_with_mineru_cloud(pdf_path, config, paper=None):
    """
    方法1: Mineru云API (异步，需轮询)
    新版API: https://mineru.net/api/v4/extract/task
    只支持URL方式，不支持文件上传

    Args:
        pdf_path: 本地PDF路径（仅用于备用）
        config: 配置
        paper: 论文信息（包含arxiv_id）
    """
    try:
        logger.info(">>> 尝试方法1: Mineru云API...")

        api_key = config.get('mineru', {}).get('api_key', '')
        if not api_key:
            logger.info("未配置Mineru API密钥，跳过")
            return None

        proxies = get_proxies(config)

        # Mineru云API只支持URL方式
        pdf_url = None

        # 1. 优先从paper中获取arxiv_id
        if paper and paper.get('arxiv_id'):
            arxiv_id = paper.get('arxiv_id')
            # 去掉版本号，如 2602.23193v1 -> 2602.23193
            if 'v' in arxiv_id:
                arxiv_id = arxiv_id.split('v')[0]
            pdf_url = f'https://arxiv.org/pdf/{arxiv_id}.pdf'

        # 2. 从config中获取
        if not pdf_url:
            pdf_url = config.get('mineru', {}).get('pdf_url', '')

        if not pdf_url:
            logger.error("无法获取PDF URL，跳过Mineru云API")
            return None

        logger.info(f"使用PDF URL: {pdf_url}")

        # 用URL方式提交
        payload = {
            'url': pdf_url,
            'model_version': 'vlm'
        }
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        response = requests.post(
            'https://mineru.net/api/v4/extract/task',
            json=payload,
            headers=headers,
            proxies=proxies,
            timeout=120
        )

        if response.status_code != 200:
            logger.error(f"Mineru提交失败: {response.status_code}, {response.text[:200]}")
            return None

        # 解析返回的任务ID
        data = response.json()
        task_id = None

        # 可能的返回格式
        if data.get('data', {}).get('task_id'):
            task_id = data['data']['task_id']
        elif data.get('task_id'):
            task_id = data['task_id']
        elif data.get('data', {}).get('id'):
            task_id = data['data']['id']

        if not task_id:
            # 可能同步返回了结果
            if data.get('data', {}).get('markdown'):
                logger.info("✓ Mineru云成功(同步返回)!")
                return data['data']['markdown']
            logger.error(f"Mineru未返回task_id: {data}")
            return None

        logger.info(f"Mineru任务已提交: {task_id}, 开始轮询...")

        # 第二步: 轮询获取结果 (返回markdown和zip路径)
        markdown, zip_path = get_mineru_result(task_id, api_key, proxies)
        if markdown:
            logger.info("✓ Mineru云成功!")
            # 返回(markdown, zip路径)
            return (markdown, zip_path)

    except requests.exceptions.Timeout:
        logger.error(f"Mineru超时")
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Mineru连接失败: {str(e)[:200]}")
    except Exception as e:
        logger.error(f"Mineru异常: {str(e)[:200]}")

    return None


def convert_with_mineru_local(pdf_path, config):
    """
    方法2: Mineru本地部署
    """
    try:
        logger.info(">>> 尝试方法2: Mineru本地...")

        local_url = config.get('mineru', {}).get('local_url', 'http://localhost:8000')
        proxies = get_proxies(config)

        with open(pdf_path, 'rb') as f:
            data = {
                'is_ocr': 'true',
                'is_parse': 'true',
                'output_format': 'markdown'
            }
            files = {
                'file': (os.path.basename(pdf_path), f, 'application/pdf')
            }
            response = requests.post(
                f'{local_url}/v1/convert/file',
                data=data,
                files=files,
                proxies=proxies,
                timeout=180
            )

        if response.status_code == 200:
            data = response.json()
            # 尝试多种返回格式
            if data.get('data', {}).get('markdown'):
                logger.info("✓ Mineru本地成功!")
                return data['data']['markdown']
            elif data.get('markdown'):
                logger.info("✓ Mineru本地成功!")
                return data['markdown']
            elif data.get('data', {}).get('content'):
                logger.info("✓ Mineru本地成功!")
                return data['data']['content']

        logger.error(f"Mineru本地返回: {response.status_code}, {response.text[:100]}")

    except requests.exceptions.ConnectionError as e:
        logger.error(f"Mineru本地连接失败: {str(e)[:200]}")
    except Exception as e:
        logger.error(f"Mineru本地异常: {str(e)[:200]}")

    return None


def convert_with_pdfplumber(pdf_path, config):
    """
    方法3: pdfplumber兜底 (纯文本，无格式)
    这是兜底方案
    """
    try:
        logger.info(">>> 尝试方法3: pdfplumber兜底...")

        import pdfplumber

        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages[:15]):  # 限制15页
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"\n--- 第{i+1}页 ---\n")
                    text_parts.append(page_text)

        if text_parts:
            result = "".join(text_parts)
            logger.info("✓ pdfplumber成功!(纯文本)")
            return result

    except ImportError:
        logger.error("pdfplumber未安装")
    except Exception as e:
        logger.error(f"pdfplumber失败: {str(e)[:200]}")

    return None


def convert_pdf_to_markdown(pdf_path, config, paper=None):
    """
    多后端兜底转换 - 按优先级尝试

    Args:
        pdf_path: 本地PDF路径
        config: 配置
        paper: 论文信息（包含arxiv_id，用于Mineru云API）

    Returns:
        tuple: (markdown, zip_file_path) - markdown内容和zip文件路径（如果有）
    """
    # 按优先级尝试各个方法
    methods = [
        ("Mineru云", lambda: convert_with_mineru_cloud(pdf_path, config, paper)),
        ("Mineru本地", lambda: convert_with_mineru_local(pdf_path, config)),
        ("pdfplumber兜底", lambda: convert_with_pdfplumber(pdf_path, config)),
    ]

    for name, method in methods:
        try:
            logger.info(f"尝试 {name}...")
            result = method()

            # 处理返回值 (可能是tuple或string)
            if isinstance(result, tuple):
                markdown, zip_path = result
            else:
                markdown = result
                zip_path = None

            if markdown and len(markdown) > 100:  # 确保返回有效内容
                logger.info(f"✓ {name} 成功转换!")
                # 返回(markdown, zip路径)
                return markdown, zip_path
            else:
                logger.warning(f"{name} 返回内容太少，跳过")
        except Exception as e:
            logger.error(f"{name} 抛出异常: {str(e)[:200]}")

    logger.error("✗ 所有转换方法都失败了!")
    return None, None


def get_next_image_index(output_dir, prefix):
    """
    获取下一个图片的编号，避免文件名重复
    """
    if not os.path.exists(output_dir):
        return 1

    existing = []
    for f in os.listdir(output_dir):
        if f.startswith(prefix) and f.endswith(('.png', '.jpg', '.gif', '.webp')):
            try:
                # 提取编号 - 处理 prefix001.png 格式（无下划线）
                remainder = f[len(prefix):]
                if remainder and remainder[0].isdigit():
                    # 直接提取数字部分
                    num_str = ''
                    for c in remainder:
                        if c.isdigit():
                            num_str += c
                        else:
                            break
                    if num_str:
                        existing.append(int(num_str))
            except (ValueError, IndexError):
                pass

    if existing:
        return max(existing) + 1
    return 1


def download_images_from_markdown(markdown_text, output_dir, paper_id):
    """
    从Markdown下载图片到本地
    Windows兼容处理
    """
    ensure_dir(output_dir)

    # 生成安全的文件名前缀
    safe_prefix = re.sub(r'[<>:"\\|?*]', '_', paper_id)[:20]
    downloaded_images = []

    # 匹配Markdown图片语法
    img_pattern = r'!\[([^\]]*)\]\(([^\)]+)\)'

    # 获取起始编号
    start_index = get_next_image_index(output_dir, safe_prefix)

    def download_single(match):
        nonlocal downloaded_images
        alt_text = match.group(1)
        img_url = match.group(2)

        # 跳过非HTTP链接
        if not img_url.startswith('http'):
            # 处理base64图片
            if img_url.startswith('data:'):
                try:
                    header, b64data = img_url.split(',', 1)
                    ext = '.png'
                    if 'jpeg' in header: ext = '.jpg'
                    elif 'gif' in header: ext = '.gif'

                    img_data = base64.b64decode(b64data)

                    idx = start_index + len(downloaded_images)
                    filename = f"{safe_prefix}_{idx:03d}{ext}"
                    filepath = os.path.join(output_dir, filename)

                    with open(filepath, 'wb') as f:
                        f.write(img_data)

                    downloaded_images.append(filepath)
                    logger.info(f"保存Base64图片: {filename}")
                    return f"![{alt_text}](./{filename})"
                except Exception as e:
                    logger.error(f"Base64图片处理失败: {str(e)[:100]}")

            logger.warning(f"跳过非HTTP图片: {img_url[:50]}")
            return match.group(0)

        try:
            proxies = get_proxies()
            resp = requests.get(img_url, proxies=proxies, timeout=30, stream=True)
            if resp.status_code == 200:
                ext = '.png'
                content_type = resp.headers.get('Content-Type', '')
                if 'jpeg' in content_type or 'jpg' in content_type:
                    ext = '.jpg'
                elif 'gif' in content_type:
                    ext = '.gif'
                elif 'webp' in content_type:
                    ext = '.webp'
                elif 'svg' in content_type:
                    ext = '.svg'

                idx = start_index + len(downloaded_images)
                filename = f"{safe_prefix}_{idx:03d}{ext}"
                filepath = os.path.join(output_dir, filename)

                with open(filepath, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)

                downloaded_images.append(filepath)
                logger.info(f"下载图片成功: {filename}")
                return f"![{alt_text}](./{filename})"
            else:
                logger.error(f"图片下载失败 HTTP {resp.status_code}: {img_url[:50]}")

        except Exception as e:
            logger.error(f"图片下载异常: {str(e)[:100]}")

        return match.group(0)

    # 替换所有图片URL
    updated_markdown = re.sub(img_pattern, download_single, markdown_text)
    return updated_markdown, downloaded_images


def extract_tables_from_markdown(markdown_text):
    """提取表格"""
    tables = []
    pattern = r'(\|(?:.+\|)\n\|[-:\s|]+\|\n(?:\|.+\|\n?)+)'
    for match in re.findall(pattern, markdown_text):
        tables.append(match)
    return tables


def extract_images_from_zip(zip_path, output_dir, paper_id):
    """
    从zip文件中提取图片
    限制最多10张，排除公式相关图片
    """
    import zipfile
    import shutil

    extracted_images = []
    safe_prefix = re.sub(r'[<>:"\\|?*]', '_', paper_id)[:20]

    # 公式相关的关键词，需要排除
    formula_keywords = ['equation', 'formula', 'math', 'eq_', '_eq', 'symbol']

    # 用于跟踪已处理的图片（避免重复）
    seen_images = set()
    max_images = 10

    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            # 查找images目录
            for name in z.namelist():
                # 检查是否是图片文件
                if name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')):
                    # 跳过公式相关的图片
                    name_lower = name.lower()
                    is_formula = any(kw in name_lower for kw in formula_keywords)
                    if is_formula:
                        logger.info(f"跳过公式图片: {name}")
                        continue

                    # 跳过已处理的图片（通过图片内容hash去重）
                    try:
                        img_data = z.read(name)
                        img_hash = hash(img_data)
                        if img_hash in seen_images:
                            continue
                        seen_images.add(img_hash)
                    except:
                        pass

                    # 限制最多10张
                    if len(extracted_images) >= max_images:
                        logger.info(f"已达到最大图片数量 {max_images}，停止提取")
                        break

                    try:
                        # 提取文件
                        ext = os.path.splitext(name)[1]
                        idx = len([f for f in os.listdir(output_dir) if f.startswith(safe_prefix)]) + 1
                        filename = f"{safe_prefix}_{idx:03d}{ext}"
                        filepath = os.path.join(output_dir, filename)

                        # 写入文件
                        with z.open(name) as src:
                            with open(filepath, 'wb') as dst:
                                shutil.copyfileobj(src, dst)

                        extracted_images.append(filepath)
                        logger.info(f"从zip提取图片: {filename}")
                    except Exception as e:
                        logger.warning(f"提取图片失败 {name}: {str(e)[:50]}")

    except Exception as e:
        logger.error(f"解压zip失败: {str(e)[:100]}")

    return extracted_images


def process_paper_with_mineru(paper, pdf_path, config):
    """
    处理单篇论文的完整流程
    """
    result = {
        'markdown': '',
        'images': [],
        'tables': [],
        'image_markdown': '',
        'mineru_success': False,
        'method_used': None
    }

    enabled = config.get('mineru', {}).get('enabled', False)
    if not enabled:
        logger.info("PDF转换未启用")
        return result

    paper_title = paper.get('title', 'paper')[:50]
    paper_id = paper.get('arxiv_id', '') or paper_title.replace(' ', '_')[:30]
    logger.info(f"\n========== 处理论文: {paper_id} ==========")

    # 步骤1: 转换为Markdown
    logger.info("步骤1: 尝试转换为Markdown...")
    markdown, zip_path = convert_pdf_to_markdown(pdf_path, config, paper)

    if not markdown or len(markdown) < 100:
        logger.error("✗ PDF转换失败，无法继续")
        return result

    result['markdown'] = markdown
    result['mineru_success'] = True
    result['method_used'] = 'pdfplumber' if len(markdown) < 1000 else 'mineru'

    # 步骤2: 提取表格
    logger.info("步骤2: 提取表格...")
    result['tables'] = extract_tables_from_markdown(markdown)
    logger.info(f"提取到 {len(result['tables'])} 个表格")

    # 步骤3: 下载/提取图片
    logger.info("步骤3: 下载图片...")

    vault_path = config.get('obsidian', {}).get('vault_path', '')
    images_folder = config.get('obsidian', {}).get('images_folder', '论文图片')

    safe_title = re.sub(r'[<>:"\\|?*]', '_', paper_id)
    output_dir = os.path.join(vault_path, images_folder, safe_title)
    ensure_dir(output_dir)

    # 如果有zip文件，先从中提取图片
    if zip_path and os.path.exists(zip_path):
        logger.info(f"从zip文件提取图片: {zip_path}")
        zip_images = extract_images_from_zip(zip_path, output_dir, paper_id)
        logger.info(f"从zip提取了 {len(zip_images)} 张图片")

    # 然后处理markdown中的图片（HTTP和base64）
    updated_md, images = download_images_from_markdown(markdown, output_dir, paper_id)

    # 合并所有图片（去重）
    all_images = images
    if zip_path and os.path.exists(zip_path):
        # 重新扫描目录获取所有图片
        all_images = []
        for f in os.listdir(output_dir):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                all_images.append(os.path.join(output_dir, f))
    result['image_markdown'] = updated_md
    result['images'] = all_images
    logger.info(f"共获取 {len(all_images)} 张图片")

    logger.info(f"✓ 论文处理完成! 使用方法: {result['method_used']}")

    return result


def main():
    config_path = os.path.join(os.path.dirname(project_root), 'config.yaml')
    config = load_config(config_path)

    print("=" * 50)
    print("PDF转换模块测试")
    print("=" * 50)

    mineru_cfg = config.get('mineru', {})
    print(f"启用状态: {mineru_cfg.get('enabled', False)}")
    print(f"API密钥: {'已设置' if mineru_cfg.get('api_key') else '未设置'}")
    print(f"代理: {get_proxies(config)}")
    print(f"Mineru本地: {mineru_cfg.get('local_url', '未设置')}")


if __name__ == '__main__':
    main()
