"""Provider-neutral URL discovery. Basic Tavily calls use one credit, not advanced mode."""
import os
from .http import FetchError

SEARCH_KEYS = {'tavily': 'TAVILY_API_KEY', 'brave': 'BRAVE_SEARCH_API_KEY'}


def configured_search_providers():
    configured = os.getenv('SEARCH_PROVIDERS', 'tavily,brave').split(',')
    return list(dict.fromkeys(p.strip().lower() for p in configured if p.strip().lower() in SEARCH_KEYS
                             and os.getenv(SEARCH_KEYS[p.strip().lower()], '').strip()))


def search_urls(client, provider, query, page=0):
    key = os.environ[SEARCH_KEYS[provider]].strip()
    if provider == 'tavily':
        body = client.post_json('https://api.tavily.com/search', headers={'Authorization': 'Bearer ' + key},
            body={'query': query, 'search_depth': 'basic', 'max_results': 20,
                  'include_answer': False, 'include_raw_content': False, 'auto_parameters': False})
        rows = body.get('results') if isinstance(body, dict) else None
        field = 'url'
    else:
        body = client.json('https://api.search.brave.com/res/v1/web/search',
            params={'q': query, 'count': 20, 'offset': page % 10},
            headers={'X-Subscription-Token': key}, retries=0)
        rows = (body.get('web') or {}).get('results', []) if isinstance(body, dict) else None
        field = 'url'
    if not isinstance(rows, list):
        raise FetchError('unexpected search response')
    return [row[field] for row in rows if isinstance(row, dict) and isinstance(row.get(field), str)]
