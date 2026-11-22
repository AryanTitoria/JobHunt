"""Local document extraction; original binaries are never served or persisted."""
import hashlib
import io
import re
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

SKILLS = {
    'Python': ['python'], 'Java': ['java'], 'JavaScript': ['javascript', 'js', 'ecmascript'], 'TypeScript': ['typescript', 'ts'],
    'C++': ['c++'], 'C#': ['c#'], 'Go': ['golang', 'go language'], 'Rust': ['rust'], 'SQL': ['sql'],
    'PostgreSQL': ['postgresql', 'postgres'], 'MySQL': ['mysql'], 'MongoDB': ['mongodb'],
    'Redis': ['redis'], 'Kafka': ['kafka'], 'Docker': ['docker'], 'Kubernetes': ['kubernetes', 'k8s'],
    'AWS': ['aws', 'amazon web services'], 'Azure': ['azure'], 'GCP': ['gcp', 'google cloud'],
    'React': ['react', 'reactjs'], 'Next.js': ['next.js', 'nextjs'], 'Node.js': ['node.js', 'nodejs'],
    'Django': ['django'], 'Flask': ['flask'], 'FastAPI': ['fastapi'], 'Spring': ['spring'],
    'HTML': ['html'], 'CSS': ['css'], 'Git': ['git'], 'Linux': ['linux'], 'REST APIs': ['rest api', 'rest apis', 'restful api', 'restful apis'],
    'GraphQL': ['graphql'], 'gRPC': ['grpc'], 'Terraform': ['terraform'], 'CI/CD': ['ci/cd', 'cicd'],
    'Machine Learning': ['machine learning'], 'Deep Learning': ['deep learning'],
    'PyTorch': ['pytorch'], 'TensorFlow': ['tensorflow'], 'Pandas': ['pandas'], 'NumPy': ['numpy'],
    'Data Analysis': ['data analysis', 'data analytics'], 'Statistics': ['statistics'],
    'Excel': ['excel'], 'Power BI': ['power bi', 'powerbi'], 'Tableau': ['tableau'],
    'Figma': ['figma'], 'UX Design': ['ux design', 'user experience'], 'UI Design': ['ui design'],
    'Product Management': ['product management'], 'Agile': ['agile', 'scrum'],
    'Project Management': ['project management'], 'Communication': ['communication'],
    'Digital Marketing': ['digital marketing'], 'SEO': ['seo', 'search engine optimization'],
    'Content Writing': ['content writing', 'copywriting'], 'Sales': ['sales'],
    'Accounting': ['accounting'], 'Bookkeeping': ['bookkeeping'], 'Financial Analysis': ['financial analysis'],
    'Auditing': ['auditing'], 'Tally': ['tally'], 'Taxation': ['taxation'],
    'Nursing': ['nursing'], 'Patient Care': ['patient care'], 'Clinical Research': ['clinical research'],
    'Teaching': ['teaching'], 'Curriculum Development': ['curriculum development'],
    'Recruitment': ['recruitment', 'recruiting'], 'Human Resources': ['human resources'],
    'Customer Service': ['customer service'], 'Hospitality': ['hospitality'],
    'Food Safety': ['food safety'], 'Cooking': ['cooking', 'culinary'],
    'AutoCAD': ['autocad'], 'SolidWorks': ['solidworks'], 'Civil Engineering': ['civil engineering'],
    'Electrical Engineering': ['electrical engineering'], 'Mechanical Engineering': ['mechanical engineering'],
    'Supply Chain': ['supply chain'], 'Logistics': ['logistics'], 'Legal Research': ['legal research'],
    'Quality Assurance': ['quality assurance', 'qa'], 'Testing': ['testing', 'selenium', 'pytest'],
}


def contains(text, term):
    return bool(re.search(r'(?<![\w])' + re.escape(term) + r'(?![\w])', text, re.I))


def extract_skills(text):
    found = [name for name, aliases in SKILLS.items() if any(contains(text, alias) for alias in aliases)]
    # Keep arbitrary disciplines usable: also read explicitly labelled skill lines.
    for line in text.splitlines():
        label = re.search(r'(?:^|[.;])\s*(?:technical\s+)?(?:skills|technologies|competencies)\s*:\s*(.*)', line, re.I)
        if label:
            for item in re.split(r'[,;|]', label.group(1)):
                item = item.strip(' .•-')
                if 2 <= len(item) <= 40 and item.casefold() not in {s.casefold() for s in found}:
                    found.append(item)
    return found[:60]


def profile_from_text(text):
    from .opportunities import infer_field
    from .structured import structure_resume
    structured = structure_resume(text)
    skills = extract_skills(text)
    years = [int(n) for n in re.findall(r'\b(\d{1,2})\+?\s+years?\s+(?:of\s+)?experience', text, re.I)]
    education = [line.strip() for line in text.splitlines() if re.search(r'\b(bachelor|master|b\.tech|b\.e\.|degree|university|college|diploma)\b', line, re.I)]
    titles = infer_titles(text, skills)
    stage = 'student' if re.search(r'\b(?:final[- ]year|currently (?:pursuing|enrolled)|undergraduate student|student)\b', text, re.I) else 'graduate' if not years else 'experienced'
    return {'core_skills': skills, 'target_titles': titles, 'field_of_study': (infer_field('\n'.join(education)) or infer_field(text)),
            'career_stage': stage, 'years_experience': min(max(years, default=0), 60),
            'structure': structured, 'education': education[:4], 'method': 'document extraction',
            'notice': 'Resume sections and skills are reference data for selected-job advice; they never fill or override search answers.'}


def infer_titles(text, skills):
    # Favor an actual role stated near the beginning of the resume.
    known_roles = ['software engineer', 'software developer', 'backend engineer', 'frontend engineer',
                   'data engineer', 'data analyst', 'machine learning engineer', 'ux designer',
                   'graphic designer', 'financial analyst', 'accountant', 'registered nurse',
                   'nurse', 'teacher', 'marketing analyst', 'digital marketing specialist',
                   'product manager', 'civil engineer', 'mechanical engineer', 'recruiter', 'chef']
    opening = '\n'.join(text.splitlines()[:8])
    found = [role.title() for role in known_roles if contains(opening, role)]
    if found:
        return found[:4]
    groups = [({'Nursing', 'Patient Care'}, ['Registered Nurse', 'Nurse']),
              ({'Accounting', 'Auditing', 'Financial Analysis'}, ['Accountant', 'Financial Analyst']),
              ({'Digital Marketing', 'SEO', 'Content Writing'}, ['Marketing Analyst', 'Digital Marketing Specialist']),
              ({'Teaching', 'Curriculum Development'}, ['Teacher', 'Educator']),
              ({'UX Design', 'UI Design', 'Figma'}, ['UX Designer', 'Product Designer']),
              ({'Python', 'Java', 'C++', 'Django', 'React'}, ['Software Engineer', 'Software Developer']),
              ({'Data Analysis', 'Excel', 'Power BI'}, ['Data Analyst']),
              ({'Cooking', 'Food Safety'}, ['Chef', 'Cook'])]
    for group, titles in groups:
        if set(skills) & group:
            return titles
    return []


def extract_upload(upload):
    if upload.size > settings.MAX_RESUME_BYTES:
        raise ValidationError('Please upload a file smaller than 5 MB.')
    content = upload.read(settings.MAX_RESUME_BYTES + 1)
    if len(content) > settings.MAX_RESUME_BYTES:
        raise ValidationError('Please upload a file smaller than 5 MB.')
    suffix = Path(upload.name).suffix.lower()
    try:
        if suffix in {'.txt', '.md'}:
            text = content.decode('utf-8-sig')
        elif suffix == '.pdf':
            if not content.startswith(b'%PDF'):
                raise ValueError('not a PDF')
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted or len(reader.pages) > 15:
                raise ValidationError('Use an unencrypted resume with no more than 15 pages.')
            text = '\n'.join(page.extract_text() or '' for page in reader.pages)
        elif suffix == '.docx':
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > 1500 or sum(e.file_size for e in entries) > 15_000_000:
                    raise ValidationError('This document is too complex. Export a simpler PDF or TXT file.')
            from docx import Document
            doc = Document(io.BytesIO(content))
            text = '\n'.join([p.text for p in doc.paragraphs] +
                              [cell.text for table in doc.tables for row in table.rows for cell in row.cells])
        else:
            raise ValidationError('Supported files: PDF, DOCX, TXT, and Markdown.')
    except ValidationError:
        raise
    except Exception:
        raise ValidationError('The file could not be read. Try exporting your resume to TXT or a text-based PDF.') from None
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text).strip()
    if len(text) < 80:
        raise ValidationError('Not enough text was found. Scanned PDFs need OCR first; try a TXT export.')
    if len(text) > 60_000:
        raise ValidationError('The resume is too long. Keep it below 60,000 characters.')
    return text, hashlib.sha256(text.encode()).hexdigest(), profile_from_text(text)


def redacted_text(text):
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[email removed]', text)
    text = re.sub(r'(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)', '[phone removed]', text)
    text = re.sub(r'https?://\S+', '[link removed]', text)
    return text[:18_000]
