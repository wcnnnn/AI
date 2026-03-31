#!/usr/bin/env python
"""
AI Paper Recommendation Workflow - Main Entry Point

This workflow:
1. Fetches latest papers from arXiv
2. Fetches ModelScope/魔搭社区 Papers
3. Filters papers based on user interests (limit to max_papers_per_day)
4. Downloads PDFs and extracts images
5. Parses PDF content with Chinese summary
6. Generates Obsidian notes with embedded images
"""

import os
import sys
import argparse
import logging
from datetime import datetime

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from src.utils import load_config, setup_logging, ensure_dir, get_papers_dir
from src.fetch_papers import fetch_arxiv_papers, save_papers as save_arxiv_papers
from src.fetch_modelscope import fetch_modelscope_daily_papers, save_modelscope_papers
from src.filter_papers import filter_papers, save_filtered_papers, load_filtered_papers
from src.download_images import process_all_papers_images
from src.parse_paper import process_papers_with_pdfs
from src.generate_note import generate_all_notes


def run_workflow(config, args):
    """
    Run the complete paper recommendation workflow

    Args:
        config: Configuration dictionary
        args: Command line arguments
    """
    logger = logging.getLogger(__name__)

    # Get max papers per day from config
    max_papers = config.get('max_papers_per_day', 8)
    # Get paper distribution: 5 from arXiv + 3 from ModelScope
    arxiv_limit = config.get('arxiv_limit', 5)
    modelscope_limit = config.get('modelscope_limit', 3)

    # Step 1: Fetch arXiv papers
    if args.fetch_arxiv or args.all:
        logger.info("=" * 50)
        logger.info("Step 1: Fetching arXiv papers...")
        logger.info("=" * 50)
        papers = fetch_arxiv_papers(config, days_back=7, max_results=80)
        save_arxiv_papers(papers)
        logger.info(f"Fetched {len(papers)} arXiv papers")

    # Step 2: Fetch ModelScope/魔搭社区 Papers
    if args.fetch_modelscope or args.all:
        logger.info("=" * 50)
        logger.info("Step 2: Fetching ModelScope/魔搭社区 Papers...")
        logger.info("=" * 50)
        ms_papers = fetch_modelscope_daily_papers(config, max_papers=20)
        save_modelscope_papers(ms_papers)
        logger.info(f"Fetched {len(ms_papers)} ModelScope papers")

    # Step 3: Filter papers
    if args.filter or args.all:
        logger.info("=" * 50)
        logger.info("Step 3: Filtering papers based on interests...")
        logger.info(f"         Target: {arxiv_limit} arXiv + {modelscope_limit} ModelScope")
        logger.info("=" * 50)
        filtered = filter_papers(config, arxiv_limit=arxiv_limit, modelscope_limit=modelscope_limit)

        save_filtered_papers(filtered)
        logger.info(f"Filtered to {len(filtered)} relevant papers")

        logger.info(f"\nTop {len(filtered)} relevant papers:")
        for i, paper in enumerate(filtered):
            source = paper.get('source_type', 'Unknown')
            logger.info(f"  {i+1}. [{source}] {paper.get('title', '')[:50]}...")
            logger.info(f"     Keywords: {', '.join(paper.get('matched_keywords', []))}")
            logger.info(f"     Score: {paper.get('relevance', 0):.2f}")

    # Step 4: Download PDFs and images
    if args.download or args.all:
        logger.info("=" * 50)
        logger.info("Step 4: Downloading PDFs and extracting images...")
        logger.info("=" * 50)
        papers = load_filtered_papers()

        papers = process_all_papers_images(config, papers)
        save_filtered_papers(papers)  # Save with updated image paths
        logger.info("Downloaded PDFs and extracted images")

    # Step 5: Parse PDF content with Chinese summary
    if args.parse or args.all:
        logger.info("=" * 50)
        logger.info("Step 5: Parsing PDF content with Chinese summary...")
        logger.info("=" * 50)
        papers = load_filtered_papers()

        parsed = process_papers_with_pdfs(config, papers)
        logger.info(f"Parsed {len(parsed)} papers with Chinese summaries")

    # Step 6: Generate Obsidian notes
    if args.notes or args.all:
        logger.info("=" * 50)
        logger.info("Step 6: Generating Obsidian notes...")
        logger.info("=" * 50)
        papers = load_filtered_papers()

        notes = generate_all_notes(config, papers, parse_pdfs=True)
        logger.info(f"Generated {len(notes)} Obsidian notes")

    # Step 7: Generate daily HTML report
    if args.html or args.all:
        logger.info("=" * 50)
        logger.info("Step 7: Generating daily HTML report...")
        logger.info("=" * 50)
        from src.generate_html import generate_daily_html
        papers = load_filtered_papers()
        html_path = generate_daily_html(config, papers)
        if html_path:
            logger.info(f"HTML report: {html_path}")

    # Step 8: Generate shareable HTML and push to GitHub Pages
    if args.share:
        logger.info("=" * 50)
        logger.info("Step 8: Generating shareable HTML for GitHub Pages...")
        logger.info("=" * 50)
        import subprocess
        from src.generate_html import generate_daily_html

        papers = load_filtered_papers()
        html_path = generate_daily_html(config, papers, share_mode=True)
        if not html_path:
            logger.error("Failed to generate shareable HTML")
        else:
            logger.info(f"Share HTML generated: {html_path}")
            share_dir = os.path.join(project_root, 'output', 'share')

            # Also write an index.html pointing to today's file
            today = datetime.now().strftime('%Y-%m-%d')
            index_path = os.path.join(share_dir, 'index.html')
            with open(index_path, 'w', encoding='utf-8') as f:
                f.write(f'<!DOCTYPE html><html><head><meta charset="UTF-8">'
                        f'<meta http-equiv="refresh" content="0;url=daily_{today}.html">'
                        f'</head><body><a href="daily_{today}.html">'
                        f'AI论文日报 {today}</a></body></html>')

            # Push output/share/ contents to gh-pages branch using worktree
            # (never touches the current working directory / main branch files)
            import shutil
            worktree_dir = os.path.join(project_root, '.gh-pages-worktree')
            try:
                def run_git(cmd, cwd=project_root):
                    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8')
                    if result.returncode != 0:
                        raise RuntimeError(result.stderr.strip())
                    return result.stdout.strip()

                # Clean up any leftover worktree from a previous failed run
                if os.path.exists(worktree_dir):
                    run_git(['git', 'worktree', 'remove', '--force', worktree_dir])

                # Check if gh-pages branch already exists
                all_branches = run_git(['git', 'branch', '-a'])
                gh_pages_exists = 'gh-pages' in all_branches

                if not gh_pages_exists:
                    # Create orphan gh-pages branch with an empty commit so worktree can use it
                    logger.info("Creating gh-pages branch...")
                    run_git(['git', 'checkout', '--orphan', 'gh-pages'])
                    run_git(['git', 'reset', '--hard'])
                    run_git(['git', 'commit', '--allow-empty', '-m', 'init gh-pages'])
                    run_git(['git', 'checkout', 'main'])

                # Add worktree for gh-pages in a temp dir outside the main tree
                run_git(['git', 'worktree', 'add', worktree_dir, 'gh-pages'])

                # Copy share files into the worktree
                for fname in os.listdir(share_dir):
                    shutil.copy2(os.path.join(share_dir, fname), os.path.join(worktree_dir, fname))

                # Commit and push from inside the worktree
                run_git(['git', 'add', '-A'], cwd=worktree_dir)
                run_git(['git', 'commit', '-m', f'Daily report {today}'], cwd=worktree_dir)
                run_git(['git', 'push', 'origin', 'gh-pages'], cwd=worktree_dir)

                # Clean up worktree
                run_git(['git', 'worktree', 'remove', '--force', worktree_dir])

                repo_url = run_git(['git', 'remote', 'get-url', 'origin'])
                repo_url_clean = repo_url.split('@')[-1] if '@' in repo_url else repo_url
                if 'github.com' in repo_url_clean:
                    repo_slug = repo_url_clean.split('github.com/')[-1].replace('.git', '').strip('/')
                    parts = repo_slug.split('/')
                    pages_url = f'https://{parts[0]}.github.io/{parts[1]}/' if len(parts) >= 2 else repo_url_clean
                else:
                    pages_url = '(open GitHub repo → Settings → Pages → branch: gh-pages)'

                logger.info("=" * 50)
                logger.info(f"✅ Pushed to gh-pages!")
                logger.info(f"🌐 URL: {pages_url}")
                logger.info("=" * 50)
            except Exception as e:
                logger.error(f"Git push failed: {e}")
                # Clean up worktree if it exists
                if os.path.exists(worktree_dir):
                    try:
                        run_git(['git', 'worktree', 'remove', '--force', worktree_dir])
                    except Exception:
                        pass
                logger.info(f"Share HTML is at: {html_path}")
                logger.info("You can manually push the output/share/ folder to your gh-pages branch.")

    logger.info("=" * 50)
    logger.info("Workflow complete!")
    logger.info("=" * 50)


def main():
    """Main entry point"""
    # Load configuration
    config_path = os.path.join(project_root, 'config.yaml')
    config = load_config(config_path)

    # Setup logging
    logger = setup_logging(config)

    # Parse arguments
    parser = argparse.ArgumentParser(
        description='AI Paper Recommendation Workflow'
    )
    parser.add_argument('--all', action='store_true',
                       help='Run all workflow steps')
    parser.add_argument('--fetch-arxiv', action='store_true',
                       help='Fetch arXiv papers')
    parser.add_argument('--fetch-modelscope', action='store_true',
                       help='Fetch ModelScope/魔搭社区 Papers')
    parser.add_argument('--filter', action='store_true',
                       help='Filter papers by relevance')
    parser.add_argument('--download', action='store_true',
                       help='Download PDFs and extract images')
    parser.add_argument('--parse', action='store_true',
                       help='Parse PDF content with Chinese summary')
    parser.add_argument('--notes', action='store_true',
                       help='Generate Obsidian notes')
    parser.add_argument('--html', action='store_true',
                       help='Generate daily HTML report')
    parser.add_argument('--share', action='store_true',
                       help='Generate shareable HTML and push to GitHub Pages (gh-pages branch)')

    args = parser.parse_args()

    # If no arguments, run full workflow
    if not any([args.all, args.fetch_arxiv, args.fetch_modelscope, args.filter,
                args.download, args.parse, args.notes, args.html, args.share]):
        args.all = True

    # Print welcome message
    max_papers = config.get('max_papers_per_day', 5)

    logger.info("=" * 60)
    logger.info("AI Paper Recommendation Workflow")
    logger.info("=" * 60)
    logger.info(f"Vault: {config.get('obsidian', {}).get('vault_path', 'Not configured')}")
    logger.info(f"Keywords: {', '.join(config.get('keywords', [])[:5])}...")
    logger.info(f"Max papers per day: {max_papers}")
    logger.info("=" * 60)

    # Run workflow
    try:
        run_workflow(config, args)
    except Exception as e:
        logger.error(f"Workflow error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
