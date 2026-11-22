"""Public job text parsing. Unstated or conflicting requirements remain unknown."""
import re
from functools import lru_cache

VERSION = 3
COUNTRIES = {'india': ['india','indian','ind'], 'united states':['united states','usa','u.s.','us only'],
 'united kingdom':['united kingdom','uk only','u.k.'], 'canada':['canada','canadian'],
 'germany':['germany'], 'australia':['australia'], 'singapore':['singapore']}
DEGREES = {'school':r'\b(?:high school|secondary school|12th)\b', 'diploma':r'\bdiploma\b',
 'bachelor':r'\b(?:bachelor[’\x27]?s?|b\.?tech|b\.?e\.?|b\.?sc|undergraduate degree)\b',
 'master':r'\b(?:master[’\x27]?s?|m\.?tech|m\.?sc|mba|postgraduate degree)\b',
 'doctorate':r'\b(?:ph\.?d|doctorate|doctoral)\b'}


def clauses(text):
    preferred=False
    for line in re.split(r'[\n;]+|[.!?](?!\d)',text):
        line=line.strip(' •:-\t')
        if not line: continue
        header=re.match(r'^(preferred qualifications|preferred requirements|nice.to.have|desirable|bonus skills)\b\s*:?(.*)',line,re.I)
        if header:
            preferred=True
            line=header[2].strip()
            if not line: continue
        elif re.match(r'^(minimum|basic|required|essential) (?:qualifications|requirements|skills)\b',line,re.I):
            preferred=False
        optional=preferred or bool(re.search(r'\b(?:preferred|desirable|nice.to.have|bonus|ideally)\b',line,re.I))
        yield line, optional


def remote_details(title, location, description, remote_flag=False):
    label=title+' '+location
    lines=[line for line,_ in clauses(description) if re.search(r'\bremote|work from home|hybrid|on.site|in.office|workplace|work arrangement',line,re.I) or re.search(r'\b(?:candidates?|applicants?)\b.*(?:resid|based|locat|eligib|from)|\b(?:must|need to|have to)\s+(?:be|reside|live|work)\b|\b(?:residents|residency|open to)\b',line,re.I)]
    evidence='\n'.join(lines)[:6000]
    all_text=label+'\n'+evidence
    modes=set()
    if re.search(r'\bhybrid\b',label,re.I) or re.search(r'(?:work(?:ing)? (?:model|arrangement)|workplace|position is)\s*[:=-]?\s*hybrid',evidence,re.I): modes.add('hybrid')
    if remote_flag or re.search(r'\b(?:remote|worldwide|anywhere|work from home)\b',label,re.I) or re.search(r'(?:fully remote|100% remote|remote[- ](?:only|first)|this (?:role|position) is remote|work from home)',evidence,re.I): modes.add('remote')
    if re.search(r'\b(?:on[- ]?site|in[- ]office|work from office)\b',label,re.I) or re.search(r'(?:work(?:ing)? (?:model|arrangement)|workplace)\s*[:=-]?\s*(?:on[- ]?site|office)',evidence,re.I): modes.add('onsite')
    # A hybrid role can contain remote days; hybrid is the explicit arrangement.
    mode='hybrid' if 'hybrid' in modes else next(iter(modes)) if len(modes)==1 else 'unknown'
    restrictions=[];excluded=[]
    for line in [location]+lines:
        if line==location or re.search(r'only|must|based in|resid|eligib|within|located in|open to|remote (?:in|from)|work from home (?:in|from)|hiring in',line,re.I):
            for name,aliases in COUNTRIES.items():
                if any(re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',line,re.I) for alias in aliases):
                    negative=any(re.search(r'(?:except|excluding|not in|not available (?:in|to)|not open to)[^.;]{0,45}'+re.escape(alias)+r'(?!\w)',line,re.I) for alias in aliases)
                    (excluded if negative else restrictions).append(name)
    restrictions=list(dict.fromkeys(restrictions))
    worldwide=bool(re.search(r'\b(?:worldwide|anywhere in the world|globally|global remote)\b',all_text,re.I))
    # Explicit country restrictions take precedence over global marketing claims.
    unrestricted=worldwide and not restrictions
    return {'mode':mode,'excluded_countries':list(dict.fromkeys(excluded)),'countries':restrictions,'worldwide':unrestricted,'evidence':lines[:8],
            'confidence':'high' if mode!='unknown' else 'unknown','unknown':mode=='unknown',
            'note':'Remote country eligibility is unstated; verify with the employer.' if mode=='remote' and not restrictions and not unrestricted else ''}


@lru_cache(maxsize=128)
def parse_job(title,location,description,remote_flag=False):
    from .resumes import extract_skills
    from .opportunities import experience_details
    from types import SimpleNamespace
    job=SimpleNamespace(title=title,location=location,description=description,remote=remote_flag)
    required,preferred,qualifications,responsibilities=[],[],[],[]
    for line,optional in clauses(description):
        skills=extract_skills(line)
        bucket=preferred if optional else required
        for skill in skills:
            if skill not in bucket: bucket.append(skill)
        levels=[level for level,pattern in DEGREES.items() if re.search(pattern,line,re.I)]
        if levels:
            qualifications.append({'text':line,'levels':levels,'preferred':optional,'evidence':line})
        if re.search(r'\b(?:build|develop|design|maintain|analyse|analyze|support|implement|collaborate|manage)\b',line,re.I):
            responsibilities.append(line)
    required=[skill for skill in required if skill not in preferred or any(not opt and skill in extract_skills(line) for line,opt in clauses(description))]
    return {'required_skills':required[:40],'preferred_skills':preferred[:30],'keywords':list(dict.fromkeys(required+preferred))[:40],
            'responsibilities':responsibilities[:12],'qualifications':qualifications[:12],
            'experience':experience_details(job),'work':remote_details(title,location,description,remote_flag),
            'version':VERSION,'method':'rules'}
