"""Run the development web app and a managed worker thread together.
Production uses a separate worker process; see Dockerfile and compose.yaml.
"""
import argparse
import os
from pathlib import Path
import threading


def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    env_file = root / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    parser = argparse.ArgumentParser(description='Run JobSearch locally with hosted AI support.')
    parser.add_argument('--demo', action='store_true', help='Use labelled fictional jobs; no offline model is involved')
    parser.add_argument('--port', type=int, default=8000)
    options = parser.parse_args()
    if not 1 <= options.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if options.demo:
        os.environ['DEMO_MODE'] = 'true'
        os.environ.setdefault('DATA_DIR', str(root / 'data' / 'demo'))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'platform_config.settings')
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import close_old_connections, connections
    from careers.services.queue import claim, execute
    call_command('migrate', interactive=False, verbosity=0)
    if os.getenv('DEMO_MODE', '').lower() == 'true':
        call_command('load_demo')
    stop = threading.Event()
    def worker_loop():
        try:
            while not stop.is_set():
                close_old_connections()
                try:
                    task = claim()
                    if task:
                        execute(task)
                        continue
                except Exception:
                    # A transient SQLite lock must not silently kill the demo worker.
                    pass
                stop.wait(1)
        finally:
            connections.close_all()
    worker = threading.Thread(target=worker_loop, name='JobSearch-development-worker', daemon=True)
    worker.start()
    print(f'\nJobSearch: http://127.0.0.1:{options.port}\nCreate an account, answer the search questionnaire, then add master resumes. Ctrl+C stops the app and worker.\n', flush=True)
    try:
        call_command('runserver', f'127.0.0.1:{options.port}', use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        worker.join(timeout=5)
        connections.close_all()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
