"""Explainable, versioned resume/JD comparison. Never a discovery gate."""
import hashlib
import json
import re
from datetime import date
from django.utils import timezone
from .job_parser import parse_job, DEGREES
from .resumes import SKILLS, contains, extract_skills
from .structured import structure_resume

VERSION = 1
WEIGHTS = {'required_skills': 35, 'preferred_skills': 10, 'evidence': 15,
           'experience': 20, 'education': 10, 'projects': 5, 'readability': 5}
STOP = {'the','and','with','for','from','that','this','will','your','our','you','are',
        'have','has','into','using','work','team','experience','skills','required'}
FORMS = {'built':'build','building':'build','developed':'develop','developing':'develop',
         'development':'develop','implemented':'implement','implementation':'implement',
         'designed':'design','designing':'design','maintained':'maintain',
         'automated':'automate','automation':'automate','analyzed':'analyze','analysis':'analyze'}


def signature(job, resume):
    return hashlib.sha256(json.dumps([VERSION, job.title, job.description,
        bool(job.description_complete), resume.text]).encode()).hexdigest()


def terms(text):
    return {FORMS.get(word, word.rstrip('s') if len(word)>4 else word)
            for word in re.findall(r'[a-z][a-z+#.]{2,}', text.lower()) if word not in STOP}


def _duration(text, structured):
    """Explicit professional claims or non-overlapping dated employment only."""
    evidence = []
    explicit = []
    for line in text.splitlines():
        if re.search(r'project|intern|coursework|university|college|student',line,re.I):
            continue
        match = re.search(r'\b(\d{1,2}(?:\.\d+)?)\+?\s+years?\s+(?:of\s+)?(?:(?:professional|commercial|industry|work)\s+)?experience',line,re.I)
        if match:
            explicit.append(float(match[1])); evidence.append(line.strip())
    if explicit:
        return max(explicit), evidence[:3], 'Explicit duration stated in this resume'
    intervals=[];year_only=False
    month_names={name.lower():index for index,name in enumerate(
        ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],1)}
    pattern=r'([A-Za-z]{3,9})\s+((?:19|20)\d{2})\s*[-–—]\s*(?:([A-Za-z]{3,9})\s+((?:19|20)\d{2})|(present|current|now))'
    for item in structured['sections']['Experience']:
        if any(structured['sources'][sid].get('employment_kind')=='internship' for sid in item['source_ids']):
            continue
        raw=' '.join(b['text'] for b in item['bullets'])
        match=re.search(pattern,raw,re.I)
        if not match:
            annual=re.search(r'\b((?:19|20)\d{2})\s*[-–—]\s*((?:19|20)\d{2}|present|current)\b',raw,re.I)
            if annual:
                today=timezone.now().date();start=(int(annual[1])+1)*12
                end=today.year*12+today.month if annual[2].lower() in {'present','current'} else int(annual[2])*12
                if end>=start:
                    intervals.append((start,end));evidence.append(annual[0]);year_only=True
            continue
        first=month_names.get(match[1][:3].lower())
        last=month_names.get((match[3] or '')[:3].lower())
        if not first or (not match[5] and not last):continue
        today=timezone.now().date()
        start=int(match[2])*12+first
        end=today.year*12+today.month if match[5] else int(match[4])*12+last
        if end>=start:
            intervals.append((start,end));evidence.append(match[0])
    if not intervals:return None, [], 'Professional duration cannot be established from the resume'
    merged=[]
    for start,end in sorted(intervals):
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else:merged.append((start,end))
    return round(sum(end-start for start,end in merged)/12,2), evidence[:4], ('Conservative lower bound from year-only employment dates; exact months unknown' if year_only else 'Estimated from explicit month/year employment dates; overlaps counted once')


def report(job, resume):
    jd=parse_job(job.title,job.location,job.description,job.remote)
    structured=structure_resume(resume.text)
    candidate=extract_skills(resume.text)
    sources=structured['sources']
    rows=[]
    required=list(dict.fromkeys(jd['required_skills']))
    preferred=[skill for skill in dict.fromkeys(jd['preferred_skills']) if skill not in required]
    all_skills=list(dict.fromkeys(required+preferred))
    evidence_rows=[]
    def support(skill):
        aliases=SKILLS.get(skill,[skill])
        found=[]
        for sid,row in sources.items():
            text=row['text']
            if re.search(r'no experience|not familiar|never used|want to learn|plan to learn',text,re.I):
                continue
            if any(contains(text,alias) for alias in aliases):
                kind=row.get('employment_kind')
                strength=1.0 if kind=='professional' else .85 if row['section'] in {'Projects','Internships'} or kind=='internship' else .6
                found.append({'source_id':sid,'text':text,'section':row['section'],'strength':strength})
        if not found:
            for line in resume.text.splitlines():
                if re.search(r'@|https?://',line):continue
                if any(contains(line,alias) for alias in aliases) and not re.search(r'no experience|not familiar|never used|want to learn|plan to learn',line,re.I):
                    found.append({'source_id':'','text':line.strip(),'section':'Unclassified','strength':.4})
        return sorted(found,key=lambda row:row['strength'],reverse=True)
    skill_evidence={skill:support(skill) for skill in all_skills}
    def component(key,label,fit,reason,evidence=None):
        rows.append({'key':key,'label':label,'weight':WEIGHTS[key],
            'applicable':fit is not None,'percent':round(100*fit) if fit is not None else None,
            'earned':round(WEIGHTS[key]*fit,2) if fit is not None else 0,
            'reason':reason,'evidence':(evidence or [])[:5]})
    for key,label,skills in [('required_skills','Required skills',required),('preferred_skills','Preferred skills',preferred)]:
        matches=[skill for skill in skills if skill_evidence[skill]]
        component(key,label,len(matches)/len(skills) if skills else None,
            f'{len(matches)} of {len(skills)} extracted {label.lower()} supported by this resume' if skills else 'Not clearly stated in the supplied job description',
            [skill+': '+skill_evidence[skill][0]['text'] for skill in matches])
    proof=[max((r['strength'] for r in skill_evidence[skill]),default=0) for skill in required or all_skills]
    component('evidence','Relevant work and project evidence',sum(proof)/len(proof) if proof else None,
        'Named skills have more support when demonstrated in employment, internships or projects; a list alone is weaker evidence',
        [skill_evidence[s][0]['text'] for s in required if skill_evidence[s]])
    years,year_evidence,year_note=_duration(resume.text,structured)
    need=jd['experience'];minimum=need['minimum']
    if need['unknown']:
        fit=None;reason='The job experience requirement is unknown; not scored'
    elif minimum==0:
        fit=1.0 if years is None or need['maximum'] is None or years<=need['maximum'] else .6
        reason='Entry-level/internship requirement; professional employment is not required' if fit==1 else 'Resume exceeds the stated experience range; verify suitability'
    elif years is None:
        fit=0;reason=year_note+'; no professional-duration evidence was found for '+need['label']
    else:
        fit=min(1,years/minimum)
        reason=f'Resume indicates {years:g} professional years; job asks for {need["label"]}. '+year_note
    component('experience','Professional experience',fit,reason,year_evidence)
    levels={'school':1,'diploma':2,'bachelor':3,'master':4,'doctorate':5}
    qualifications=[q for q in jd['qualifications'] if not q['preferred']]
    edu_text='\n'.join(b['text'] for item in structured['sections']['Education'] for b in item['bullets'])
    candidate_level=max((levels[level] for level,pattern in DEGREES.items() if re.search(pattern,edu_text or resume.text,re.I)),default=0)
    required_level=min((levels[level] for q in qualifications for level in q['levels']),default=0)
    edu_fit=min(1,candidate_level/required_level) if required_level else None
    from .opportunities import infer_field
    required_field=next((infer_field(q['text']) for q in qualifications if infer_field(q['text'])), '')
    candidate_field=infer_field(edu_text)
    if edu_fit and required_field:
        if candidate_field and candidate_field!=required_field:edu_fit*=.35
        elif not candidate_field:edu_fit*=.65
    if edu_fit and re.search(r'pursuing|expected|currently studying',edu_text,re.I) and not re.search(r'pursuing|student|enrolled|intern',job.description+' '+job.title,re.I):
        edu_fit*=.7
    component('education','Education and qualification evidence',edu_fit,
        'Compares stated degree level and recognizable field. Specialization, equivalence and completion still require verification' if required_level else 'No clear required degree level; not scored',
        [edu_text[:600]] if edu_text else [])
    projects=structured['sections']['Projects']
    relevant_projects=sum(any(any(contains(b['text'],alias) for alias in SKILLS.get(skill,[skill])) for b in item['bullets'] for skill in all_skills) for item in projects)
    project_relevant=bool(need['internship'] or need['entry'] or re.search(r'projects?|portfolio',job.description,re.I))
    component('projects','Relevant projects',min(1,relevant_projects/2) if project_relevant else None,
        f'{relevant_projects} source-backed project(s) mention relevant skills' if project_relevant else 'Projects not a stated focus of this role; not scored')
    section_count=sum(bool(items) for items in structured['sections'].values())
    chars=len(resume.text.strip())
    readable=.4*min(1,chars/500)+.4*min(1,section_count/4)+.2*(1 if '\ufffd' not in resume.text else .2)
    component('readability','Text readability and section structure',readable,
        f'{section_count} recognizable sections and {chars} text characters. Text checks cannot reproduce an employer ATS or judge visual layout')
    total=sum(row['weight'] for row in rows if row['applicable'])
    sufficient=bool(required or preferred or required_level or (minimum is not None and not need['inferred_from_title']))
    score=round(100*sum(row['earned'] for row in rows)/total) if sufficient and total else None
    known=sum(row['applicable'] for row in rows)
    confidence='higher' if known>=5 and job.description_complete else 'partial'
    matched=[skill for skill in all_skills if skill_evidence[skill]]
    missing=[skill for skill in all_skills if not skill_evidence[skill]]
    return {'version':VERSION,'signature':signature(job,resume),'score':score,'confidence':confidence,
        'resume_id':str(resume.pk),'resume_name':resume.filename,'matched_skills':matched,'missing_skills':missing,
        'components':rows,'skill_evidence':skill_evidence,'professional_years':years,
        'unknowns':[row['label']+': '+row['reason'] for row in rows if not row['applicable']],
        'summary':'Evidence-based resume/JD compatibility estimate. Unknown criteria are excluded and remaining weights are normalized.',
        'disclaimer':'Not an employer ATS result or hiring probability. Similar resumes can legitimately receive similar scores; compare the evidence breakdown.',
        'partial_description':not job.description_complete}
