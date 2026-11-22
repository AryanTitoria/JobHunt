"""Conservative resume structure with stable, verbatim source references."""
import re

HEADINGS = {
 'Summary': ['summary','professional summary','professional profile','profile','objective','career objective','about me'],
 'Skills': ['skills','technical skills','core skills','technical competencies','technologies','competencies'],
 'Experience': ['experience','work experience','employment','professional experience','employment history','relevant experience','employment experience'],
 'Internships': ['internships','internship experience','industrial training'],
 'Projects': ['projects','personal projects','academic projects','selected projects','project experience'],
 'Education': ['education','academic qualifications','educational qualifications','academic background','educational details','academic details'],
 'Certifications': ['certifications','certificates','licenses','certifications and licenses'],
}
LOOKUP = {label: name for name, labels in HEADINGS.items() for label in labels}
DATE = r'(?:19|20)\d{2}|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b'


def structure_resume(text, master_id='M1'):
    sections = {name: [] for name in HEADINGS}
    sources, unclassified = {}, []
    section, item, fresh = None, None, True
    for line_number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            fresh = True
            continue
        label, colon, suffix = stripped.partition(':')
        heading = LOOKUP.get(label.lower().strip(' #_*:•-'))
        if heading:
            section, item, fresh = heading, None, True
            if not colon or not suffix.strip():
                continue
            stripped = suffix.strip()
        if section is None:
            unclassified.append({'line': line_number, 'text': stripped})
            continue
        bullet = bool(re.match(r'^[•*\-–]\s*|^\d+[.)]\s+', stripped))
        value = re.sub(r'^[•*\-–]\s*|^\d+[.)]\s+', '', stripped).strip()
        if not value:
            continue
        if item is None or (fresh and not bullet):
            item = {'company':'','title':'','dates':'','name':'','source_heading':'','bullets':[], 'source_ids':[]}
            sections[section].append(item)
        index = len(sections[section])-1
        sid = f'{master_id}:{section}[{index}].bullet[{len(item["bullets"])}]'
        sources[sid] = {'text':value,'line':line_number,'section':section,'master_id':master_id}
        item['source_ids'].append(sid)
        explicit = re.match(r'^(Company|Employer|Title|Role|Dates|Project|Name|Degree|Institution|Certification)\s*:\s*(.+)$',value,re.I)
        if explicit:
            key = {'employer':'company','role':'title','project':'name','degree':'name','institution':'company','certification':'name'}.get(explicit[1].lower(),explicit[1].lower())
            item[key] = explicit[2].strip()
        elif not bullet and not item['source_heading'] and section not in {'Skills','Summary'}:
            item['source_heading'] = value
        item['bullets'].append({'text':value,'source_ids':[sid],'change_type':'unchanged'})
        fresh = False
    for item in sections['Experience']:
        kind='internship' if re.search(r'\bintern(?:ship)?\b',item['title']+' '+item['source_heading'],re.I) else 'professional' if item['company'] and item['title'] else 'unknown'
        for sid in item['source_ids']:sources[sid]['employment_kind']=kind
    for item in sections['Internships']:
        for sid in item['source_ids']:sources[sid]['employment_kind']='internship'
    warnings=[]
    if not any(sections.values()):
        warnings.append('Section headings were not recognized. Add clear headings before generating a structured draft.')
    if unclassified:
        warnings.append('Unclassified header/contact text was retained as reference and omitted from the tailored content.')
    return {'sections':sections,'sources':sources,'unclassified':unclassified,'warnings':warnings,'version':2}
