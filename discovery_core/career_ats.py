"""Public career APIs. Bounded SmartRecruiters snapshots never close absent jobs."""
from .fetch import Job, strip_html
from .sources import SourceResult
from .http import FetchError


def fetch_board(board, client):
    jobs = []
    if board.ats == 'recruitee':
        body = client.json(f'https://{board.slug}.recruitee.com/api/offers/')
        rows = body.get('offers') if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise FetchError('unexpected Recruitee payload; previous snapshot retained')
        for row in rows:
            if not isinstance(row, dict) or not row.get('id') or not row.get('title') or not row.get('careers_url'):
                raise FetchError('incomplete Recruitee payload; previous snapshot retained')
            location = row.get('location') or ', '.join(str(row.get(k) or '') for k in ['city', 'country']).strip(', ')
            description = strip_html(row.get('description'))
            jobs.append(Job(job_id=f"recruitee:{board.slug}:{row['id']}", ats='recruitee', company=board.name or board.slug,
                            title=row['title'], location=location, url=row['careers_url'], description=description,
                            posted_at=row.get('published_at') or row.get('created_at'), remote=bool(row.get('remote')),
                            description_complete=bool(description)))
        return SourceResult(board.key, jobs, authoritative=True)
    base = f'https://api.smartrecruiters.com/v1/companies/{board.slug}/postings'
    body = client.json(base, params={'limit': 100, 'offset': 0})
    rows = body.get('content') if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise FetchError('unexpected SmartRecruiters payload; previous snapshot retained')
    # Bound network work per board; discovery rotates sources on subsequent runs.
    for row in rows[:20]:
        if not isinstance(row, dict) or not row.get('id') or not row.get('name'):
            raise FetchError('incomplete SmartRecruiters payload; previous snapshot retained')
        item = client.json(base + '/' + str(row['id']))
        if not isinstance(item, dict) or not item.get('name'):
            raise FetchError('unexpected SmartRecruiters job detail')
        location = item.get('location') or row.get('location') or {}
        sections = (item.get('jobAd') or {}).get('sections') or {}
        description = strip_html('\n'.join(str(section.get('text') or '') for section in sections.values() if isinstance(section, dict)))
        target = item.get('postingUrl') or item.get('applyUrl') or f"https://jobs.smartrecruiters.com/{board.slug}/{row['id']}"
        jobs.append(Job(job_id=f"smartrecruiters:{board.slug}:{row['id']}", ats='smartrecruiters',
                        company=(item.get('company') or {}).get('name') or board.name or board.slug,
                        title=item['name'], location=', '.join(str(location.get(k) or '') for k in ['city', 'region', 'country']).strip(', '),
                        url=target, application_url=item.get('applyUrl') or target, description=description,
                        posted_at=item.get('releasedDate'), remote=bool(location.get('remote')), description_complete=bool(description)))
    return SourceResult(board.key, jobs, authoritative=False)
