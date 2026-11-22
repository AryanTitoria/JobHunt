"""Search terms come from confirmed questionnaire answers."""
from .opportunities import infer_field

FIELD_TITLES = {
    'Computer Science': ['software engineer', 'data analyst', 'backend developer', 'frontend developer', 'QA engineer'],
    'Mechanical Engineering': ['mechanical engineer', 'manufacturing engineer'],
    'Electrical Engineering': ['electrical engineer', 'embedded engineer'],
    'Civil Engineering': ['civil engineer', 'structural engineer'],
    'Commerce / Finance': ['financial analyst', 'accountant'],
    'Marketing': ['marketing specialist', 'digital marketing'],
    'Design': ['UX designer', 'graphic designer'],
    'Healthcare': ['healthcare', 'nurse'], 'Education': ['teacher', 'educator'],
    'Law': ['legal associate', 'lawyer'], 'Data Science': ['data analyst', 'data scientist'],
}


def search_titles(preferences):
    from .education import education_field
    if preferences.search_scope in {'education','combined'}:
        field=education_field(preferences)
        educated=FIELD_TITLES.get(field) or ([field] if field else [])
        categories=[(FIELD_TITLES.get(category) or [category])[0] for category in preferences.preferred_categories]
        return list(dict.fromkeys(educated[:1]+preferences.titles+categories+educated[1:])) if preferences.search_scope=='combined' else educated
    if preferences.search_scope == 'roles' or not preferences.field_of_study:
        return preferences.titles or []
    field = preferences.field_of_study
    titles=FIELD_TITLES.get(field) or FIELD_TITLES.get(infer_field(field)) or ([field] if field else [])
    categories=[(FIELD_TITLES.get(category) or [category])[0] for category in preferences.preferred_categories]
    return list(dict.fromkeys(titles[:1]+categories+titles[1:]))
