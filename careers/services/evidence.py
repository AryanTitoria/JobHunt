"""Conservative wording checks; unsupported AI proposals keep original wording."""
import re

GROUPS = [
    {'assist','assisted','assisting','support','supported','supporting','helped'},
    {'build','built','building'}, {'develop','developed','developing','development'},
    {'implement','implemented','implementing','implementation'},
    {'report','reports','reporting'}, {'script','scripts','scripting'},
    {'automate','automated','automating','automation'},
    {'reduce','reduced','reducing','decrease','decreased','lowered'},
    {'maintain','maintained','maintaining','maintenance'},
    {'design','designed','designing'}, {'test','tests','tested','testing'},
    {'collaborate','collaborated','collaborating','collaboration'},
]
CANON={word:sorted(group)[0] for group in GROUPS for word in group}
FUNCTION={'a','an','the','to','of','for','and','in','on','with','using','by','through','as','that','which','was','were','is','are','at','from'}


def grounded_rephrase(proposed, original):
    if not isinstance(proposed,str) or not proposed.strip():return False
    if proposed.strip()==original.strip():return True
    # Rewording metrics/dates/links is too easy to subtly change. Preserve them.
    if re.search(r'\d|https?://|www\.', original+proposed):return False
    if len(proposed)>max(100,len(original)*1.8):return False
    if re.search(r'\b(?:expert|certified|architected|spearheaded|owned|led|directed|supervised|managed)\b',proposed,re.I):
        first=re.match(r'\s*([A-Za-z]+)',proposed)
        if not first or not re.match(r'\s*'+re.escape(first[1])+r'\b',original,re.I):return False
    def tokens(text):
        return {CANON.get(word,word) for word in re.findall(r'[a-z][a-z+#.]*',text.lower()) if word not in FUNCTION}
    old,new=tokens(original),tokens(proposed)
    # Content words must all be traceable. Do not turn a detailed claim into a
    # different claim by discarding most of its qualifiers.
    return bool(new) and new.issubset(old) and len(new)>=max(1,round(len(old)*.65))


def identity_sources(masters):
    """Identity is copied locally from master headers, never invented by a model."""
    from .structured import structure_resume
    result={'name':{'text':'','source_ids':[]},'contact':[]};sources={};conflicts=[]
    names=[]
    for index,master in enumerate(masters,1):
        mid=f'M{index}'
        lines=structure_resume(master.text,mid)['unclassified']
        for row in lines[:12]:
            text=row['text']
            contacts=re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://[^\s|]+|(?<!\w)\+?\d[\d ()-]{7,}\d',text)
            for value in contacts:
                sid=f'{mid}:Identity.contact[{len(sources)}]'
                sources[sid]={'text':value,'line':row['line'],'section':'Identity','master_id':mid}
                if not any(item['text']==value for item in result['contact']):
                    result['contact'].append({'text':value,'source_ids':[sid]})
            if row is lines[0] and re.fullmatch(r'[^\W\d_]+(?:[ .\'-]+[^\W\d_]+){1,4}',text,re.UNICODE) and not re.search(r'engineer|developer|resume|curriculum|student|analyst|designer|manager|profile',text,re.I):
                sid=f'{mid}:Identity.name'
                sources[sid]={'text':text,'line':row['line'],'section':'Identity','master_id':mid}
                names.append({'text':text,'source_ids':[sid]})
    distinct={item['text'].casefold() for item in names}
    if len(distinct)==1 and names:result['name']=names[0]
    elif len(distinct)>1:
        conflicts.append({'field':'Candidate name','resolution':'Omitted; user resolution needed',
            'values_found':[{'source':item['source_ids'][0],'value':item['text']} for item in names]})
        result['contact']=[]
    for kind in ['email','phone']:
        candidates=[item for item in result['contact'] if ('email' if '@' in item['text'] else 'link' if item['text'].startswith('http') else 'phone')==kind]
        if len({item['text'] for item in candidates})>1:
            conflicts.append({'field':'Candidate '+kind,'resolution':'Conflicting values omitted; choose the correct version', 'values_found':[{'source':item['source_ids'][0],'value':item['text']} for item in candidates]})
            result['contact']=[item for item in result['contact'] if item not in candidates]
    return result,sources,conflicts
