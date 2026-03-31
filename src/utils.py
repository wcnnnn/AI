"""Utility functions for the AI Paper Recommendation Workflow"""
import os
import yaml
import logging
from datetime import datetime
from pathlib import Path

def load_config(config_path="config.yaml"):
    """Load configuration from YAML file"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def setup_logging(config):
    """Setup logging configuration"""
    log_dir = os.path.dirname(config.get('logging', {}).get('file', 'logs/app.log'))
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logging.basicConfig(
        level=getattr(logging, config.get('logging', {}).get('level', 'INFO')),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(config.get('logging', {}).get('file', 'logs/app.log'), encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def get_papers_dir():
    """Get papers directory path"""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), 'papers')

def ensure_dir(path):
    """Ensure directory exists"""
    Path(path).mkdir(parents=True, exist_ok=True)
    return path

def sanitize_filename(title):
    """Sanitize title for filename"""
    # Remove special characters and limit length
    title = title.replace('/', '-').replace('\\', '-')
    title = title.replace(':', '-').replace('*', '')
    title = title.replace('?', '').replace('"', '')
    title = title.replace('<', '').replace('>', '')
    title = title.replace('|', '').replace('\n', ' ')
    # Limit to 100 characters
    if len(title) > 100:
        title = title[:100]
    return title.strip()

def format_date(date_obj):
    """Format date to YYYY-MM-DD"""
    if isinstance(date_obj, str):
        return date_obj
    return date_obj.strftime('%Y-%m-%d')

def get_year_month():
    """Get current year and month for folder structure"""
    now = datetime.now()
    return now.strftime('%Y'), now.strftime('%m')

def load_json_safe(filepath):
    """Load JSON file safely, return empty list if not exists"""
    import json
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def get_vault_paths(config):
    """
    Get all vault paths from configuration

    Args:
        config: Configuration dictionary

    Returns:
        Dictionary with vault paths
    """
    obsidian = config.get('obsidian', {})
    vault_path = obsidian.get('vault_path', '')

    paths = {
        'vault': vault_path,
        'pdf': os.path.join(vault_path, obsidian.get('pdf_folder', '论文库')),
        'images': os.path.join(vault_path, obsidian.get('images_folder', '论文图片')),
        'notes': os.path.join(vault_path, obsidian.get('notes_folder', 'Papers')),
        'attachments': os.path.join(vault_path, obsidian.get('attachments_folder', '_attachments'))
    }

    # Ensure directories exist
    for key, path in paths.items():
        if path and key != 'vault':
            ensure_dir(path)

    return paths
