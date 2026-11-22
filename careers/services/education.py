"""Education and role answers are independent, explicit search inputs."""
import re
from .opportunities import infer_field,field_related


def education_field(preferences):
    text=preferences.education_major+' '+preferences.degree_name
    field=infer_field(text)
    if not field and re.search(r'\b(?:bca|mca|bsc cs|b\.sc cs|btech cse|b\.tech cse)\b',text,re.I): field='Computer Science'
    return field or preferences.education_major.strip()


def education_related(job,preferences):
    field=education_field(preferences)
    return bool(field) and field_related(job,field)


def employment_type(job):
    label=job.title+'\n'+job.location
    label+='\n'+'\n'.join(line for line in job.description.splitlines() if re.search(r'job type|employment type|employment:|schedule:',line,re.I))
    if re.search(r'part[- ]time',label,re.I): return 'part_time'
    if re.search(r'full[- ]time',label,re.I): return 'full_time'
    if re.search(r'\bcontract(?:or)?\b',label,re.I): return 'contract'
    if re.search(r'\btemporary\b',label,re.I): return 'temporary'
    return 'unknown'
