"""Offline-first Windows readiness checks; no fetching or paid LLM calls."""
import argparse
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-config', action='store_true', help='Use before copying .env and restoring data')
    args = parser.parse_args()
    from dotenv import dotenv_values
    from convert_latex_to_pdf import compile_latex
    config = dotenv_values(ROOT / '.env')
    if not args.skip_config:
        from automation.migrate_local import database_path
        if not database_path(ROOT).is_file():
            raise RuntimeError('Restore your migration archive before starting the app.')
        if not config.get('OPENAI_API_KEY'):
            raise RuntimeError('Copy your private .env into the repository root first. No key was printed.')
        if config.get('PORTAL_SCHEDULER_ENABLED', 'false').lower() not in {'false', '0', 'no'}:
            raise RuntimeError('Set PORTAL_SCHEDULER_ENABLED=false in .env.')
        if not str(config.get('DATABASE_URL', '')).startswith('sqlite:///'):
            raise RuntimeError('Set DATABASE_URL=sqlite:///data/career_pilot.db for the local restored database.')
    ZoneInfo('Asia/Kolkata')
    if not shutil.which('pdflatex'):
        raise RuntimeError('pdflatex is missing. Install MiKTeX, then reopen PowerShell and retry.')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        for options in [{'channel': 'chrome'}, {}]:
            browser = playwright.chromium.launch(headless=True, **options)
            page = browser.new_page()
            page.set_content('<title>Career Pilot browser check</title>')
            assert page.title() == 'Career Pilot browser check'
            browser.close()
    with tempfile.TemporaryDirectory() as temporary:
        result = compile_latex(ROOT / 'main.tex', Path(temporary) / 'resume-check.pdf', 'pdflatex')
        if result:
            raise RuntimeError('LaTeX check failed. Install missing packages in MiKTeX Console and retry.')
    print('Ready: Chrome, Chromium, India timezone and resume PDF compilation passed. No jobs fetched or LLM calls made.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
