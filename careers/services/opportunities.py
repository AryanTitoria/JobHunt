"""Experience eligibility and resume-independent field internships."""
import re

INTERN = r'\b(?:intern|internship|internships|co[- ]?op)\b'
SENIOR = r'\b(?:senior|sr\.?|staff|principal|lead|architect|director|head|manager|sde\s*(?:ii|iii|iv|[234])|(?:engineer|developer)\s*(?:ii|iii|iv|[234]))\b'
ENTRY = r'\b(?:fresher|freshers|entry[- ]level|new[- ]grad|recent graduate|graduate(?: trainee)?|junior|trainee|apprentice|sde\s*(?:i|1))\b'
NUM = r'(?:\d{1,2}|zero|one|two|three|four|five|six|seven|eight|nine|ten)'
NUMBERS = {name: i for i, name in enumerate(['zero','one','two','three','four','five','six','seven','eight','nine','ten'])}

FIELDS = {
 'Computer Science': {
   'aliases': r'\b(?:computer science|computer engineering|information technology|information systems|software engineering|cse|b\.?\s*tech\s+(?:cs|it)|b\.?\s*e\.?\s+(?:cs|it))\b',
   'roles': r'\b(?:software|programming|developer|development engineer|frontend|front[- ]end|backend|back[- ]end|full[- ]?stack|web development|machine learning|artificial intelligence|data science|data engineer|data analyst|business intelligence|cybersecurity|information security|devops|sde|quality assurance|qa engineer|test engineer|systems engineer|network engineer|it support)\b',
   'exclude': r'\b(?:sales|recruitment|recruiter|human resources|marketing|accounting|business development|graphic design)\b'},
 'Mechanical Engineering': {'aliases': r'\bmechanical engineering\b', 'roles': r'\b(?:mechanical|manufacturing|cad|solidworks)\b'},
 'Electrical Engineering': {'aliases': r'\b(?:electrical|electronics|ece)\b', 'roles': r'\b(?:electrical|electronics|embedded|vlsi|hardware)\b'},
 'Civil Engineering': {'aliases': r'\bcivil engineering\b', 'roles': r'\b(?:civil|structural|construction)\b'},
 'Commerce / Finance': {'aliases': r'\b(?:commerce|accounting|finance|b\.?com|financial)\b', 'roles': r'\b(?:accounting|finance|financial|audit|tax)\b'},
 'Marketing': {'aliases': r'\b(?:marketing|business administration|bba|mba)\b', 'roles': r'\b(?:marketing|sales|business development|content|seo)\b'},
 'Design': {'aliases': r'\b(?:design|fine arts|visual communication)\b', 'roles': r'\b(?:design|ux|ui|visual|creative)\b'},
 'Healthcare': {'aliases': r'\b(?:nursing|medicine|medical|healthcare|pharmacy)\b', 'roles': r'\b(?:nursing|clinical|medical|pharmacy|healthcare)\b'},
 'Education': {'aliases': r'\b(?:education|teaching|b\.?ed)\b', 'roles': r'\b(?:teaching|education|curriculum|tutor)\b'},
 'Law': {'aliases': r'\b(?:law|llb|legal studies)\b', 'roles': r'\b(?:law|legal|litigation|compliance)\b'},
 'Data Science': {'aliases': r'\b(?:data science|statistics|mathematics)\b', 'roles': r'\b(?:data science|data analyst|analytics|machine learning|statistics)\b'},
}


def infer_field(text):
    for name, patterns in FIELDS.items():
        if re.search(patterns['aliases'], text, re.I):
            return name
    return ''


def field_internship(job, field):
    if not field or not re.search(INTERN, job.title, re.I):
        return False
    return field_related(job, field)


def field_related(job, field):
    if not field:
        return False
    definition = FIELDS.get(field)
    if definition is None:
        canonical = infer_field(field)
        definition = FIELDS.get(canonical)
    if definition:
        if definition.get('exclude') and re.search(definition['exclude'], job.title, re.I):
            return False
        return bool(re.search(definition['roles'], job.title, re.I) or
                    re.search(definition['aliases'], job.description, re.I))
    words = [w for w in re.findall(r'[a-z]{3,}', field.lower()) if w not in {'major','degree','bachelor','master','engineering'}]
    return bool(words) and all(re.search(r'\b' + re.escape(w) + r'\b', job.title + '\n' + job.description, re.I) for w in words)


def number(value):
    return int(value) if value.isdigit() else NUMBERS[value.lower()]


def experience_details(job):
    from .job_parser import clauses
    text=(job.description or '').replace('–','-').replace('—','-')
    groups={'required':[],'preferred':[],'internships':[],'projects':[],'education':[]}
    ranges,minimums=[],[]
    numeric=r'(?:\d{1,2}(?:\.\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten)'
    def num(value): return float(value) if re.fullmatch(r'\d+(?:\.\d+)?',value) else NUMBERS[value.lower()]
    for line,optional in clauses(text):
        if not re.search(r'\b(?:experience|exp|years?|yrs?|months?|fresher)\b',line,re.I): continue
        if re.search(r'\b(?:our team|our company|combined|collectively|founded|established|we have)\b',line,re.I): continue
        education=bool(re.search(numeric+r'\s*[- ]?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:university|college|academic|formal|education|study|studies|degree|bachelor|master|diploma)',line,re.I))
        if education:
            original=line
            education_pattern=numeric+r'\s*[- ]?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:university|college|academic|formal|education|study|studies|degree|bachelor|master|diploma)\b'
            without_education=re.sub(education_pattern,'',line,flags=re.I)
            if re.search(numeric+r'\s*\+?\s*(?:years?|yrs?|months?)\b',without_education,re.I) and re.search(r'\bexperience\b',without_education,re.I):
                groups['education'].append(original)
                line=without_education;education=False
        internship=bool(re.search(r'(?<!non-)(?<!non )\binternship(?:s)?\s+(?:work\s+)?experience|experience (?:in|from|through) (?:an? |previous )?internship',line,re.I))
        project=bool(re.search(r'(?:personal|academic|university|college|coursework|side) projects?|classwork',line,re.I))
        group='preferred' if optional else 'education' if education else 'internships' if internship else 'projects' if project else 'required'
        groups[group].append(line)
        if group!='required': continue
        if not re.search(r'\b(?:experience|exp)\b',line,re.I): continue
        for match in re.finditer(r'\b('+numeric+r')\s*(?:-|to)\s*('+numeric+r')\s*(years?|yrs?|months?)\b',line,re.I):
            divisor=12 if match[3].lower().startswith('month') else 1
            ranges.append((num(match[1])/divisor,num(match[2])/divisor))
        cleaned=re.sub(r'\b'+numeric+r'\s*(?:-|to)\s*'+numeric+r'\s*(?:years?|yrs?|months?)\b','',line,flags=re.I)
        for match in re.finditer(r'\b('+numeric+r')\s*\+?\s*(years?|yrs?|months?)\b',cleaned,re.I):
            minimums.append(num(match[1])/(12 if match[2].lower().startswith('month') else 1))
    low=max([pair[0] for pair in ranges]+minimums,default=None)
    high=min([pair[1] for pair in ranges],default=None)
    conflict=low is not None and high is not None and high<low
    if conflict: low=high=None
    internship=bool(re.search(INTERN,job.title,re.I))
    senior=bool(re.search(SENIOR,job.title,re.I))
    entry=bool(re.search(ENTRY,job.title,re.I) or re.search(r'\b(?:no (?:prior |previous |professional |work )?experience (?:is )?(?:required|necessary)|freshers? (?:can apply|welcome|eligible))\b',text,re.I))
    inferred=low is None and (internship or entry) and not conflict
    if inferred: low=0
    def fmt(value): return f'{value:g}'
    label=(f'{fmt(low)}–{fmt(high)} years' if high is not None else f'{fmt(low)}+ years') if low is not None else 'Experience unknown'
    if inferred: label='Entry level · years unstated'
    return {'minimum':low,'maximum':high,'internship':internship,'senior':senior,'entry':entry,
            'label':label,'categories':groups,'confidence':'unknown' if low is None else 'medium' if inferred else 'high',
            'inferred_from_title':inferred,'conflict':conflict,'unknown':low is None}


def experience_eligibility(job, preferences):
    detail = experience_details(job)
    years = preferences.years_experience
    if detail['senior'] and years < 3:
        return False, 'Senior/lead role excluded for your experience level', detail
    if detail['minimum'] is not None and years < detail['minimum']:
        return False, f"Requires {detail['label']}; your profile has {years} years", detail
    if detail['maximum'] is not None and years > detail['maximum']:
        return False, f"Outside the stated {detail['label']} experience range", detail
    if detail['minimum'] is None and not preferences.include_unknown_experience:
        return False, 'Experience requirement is unstated; excluded by your preference', detail
    return True, ('Fresher/entry-level eligibility' if years == 0 else f"Experience compatible: {detail['label']}"), detail
