import re
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.contrib.auth.validators import UnicodeUsernameValidator
from .models import Preferences


def split_values(value, maximum=20):
    return list(dict.fromkeys(item.strip()[:100] for item in value.split(',') if item.strip()))[:maximum]


class RegisterForm(UserCreationForm):
    username = forms.CharField(min_length=3, max_length=150, validators=[UnicodeUsernameValidator()],
        help_text='Use 3–150 characters: letters, numbers, or @ . + - _. An email address can also be your username.',
        widget=forms.TextInput(attrs={'autocomplete': 'username', 'autocapitalize': 'none'}))
    email = forms.EmailField(required=False, help_text='Optional. JobSearch does not send job digests.')
    class Meta:
        model = get_user_model()
        fields = ('username', 'email', 'password1', 'password2')

    def clean_username(self):
        name = self.cleaned_data['username'].lower()
        if get_user_model().objects.filter(username__iexact=name).exists():
            raise forms.ValidationError('This username is already taken.')
        return name


class ResumeForm(forms.Form):
    document_date = forms.DateField(required=False, label='Master resume date (optional)', widget=forms.DateInput(attrs={'type':'date'}), help_text='The date this version was prepared. Upload time is never used to settle conflicting facts.')
    resume = forms.FileField(label='Your resume', widget=forms.ClearableFileInput(attrs={'accept': '.pdf,.docx,.txt,.md'}))


CATEGORY_CHOICES = [(x,x) for x in ['Computer Science','Data Science','Commerce / Finance','Marketing','Design','Mechanical Engineering','Electrical Engineering','Civil Engineering','Healthcare','Education','Law']]


class PreferencesForm(forms.ModelForm):
    employment_types = forms.MultipleChoiceField(required=False, choices=[('full_time','Full-time'),('part_time','Part-time'),('contract','Contract'),('temporary','Temporary')], widget=forms.CheckboxSelectMultiple)
    preferred_categories = forms.MultipleChoiceField(required=False, label='Which work categories are you open to?', choices=CATEGORY_CHOICES, widget=forms.CheckboxSelectMultiple)
    excluded_titles_text = forms.CharField(required=False, label='Any roles you want to exclude?', help_text='Comma-separated titles, e.g. Sales Executive, Customer Support.')
    titles_text = forms.CharField(required=False, label='Which roles interest you?',
        help_text='Separate roles with commas, e.g. Backend Engineer, Data Analyst. Required when searching only selected roles.')
    locations_text = forms.CharField(required=False, label='Where would you like to work?',
        help_text='Countries or cities separated by commas. Use India for all Indian locations. Blank means any location; verify work eligibility.')
    class Meta:
        model = Preferences
        fields = ('career_stage', 'education_level', 'degree_name', 'education_major', 'graduation_year', 'field_of_study', 'years_experience', 'search_scope', 'titles_text', 'preferred_categories', 'employment_types', 'availability', 'excluded_titles_text',
                  'opportunity_type', 'work_arrangement', 'allow_remote', 'locations_text',
                  'include_unknown_experience', 'include_unknown_work_arrangement', 'ai_consent', 'fallback_consent', 'parser_ai_consent')
        labels = {'education_level':'What is your highest/current qualification?', 'degree_name':'What degree or course are you pursuing/completed?', 'education_major':'What is your education major/specialization?', 'graduation_year':'When did you graduate, or expect to graduate?', 'availability':'When can you start? (reference)', 'parser_ai_consent':'Use hosted AI to interpret unclear selected-job requirements and rank supported resume items', 'career_stage': 'What is your current career stage?',
                  'field_of_study': 'What field or industry do you want to work in?',
                  'years_experience': 'How many years of professional experience do you have?',
                  'search_scope': 'How broadly should we search?',
                  'opportunity_type': 'Are you looking for jobs, internships, or both?',
                  'work_arrangement': 'How would you like to work?',
                  'allow_remote': 'Include remote opportunities when choosing any arrangement',
                  'include_unknown_experience': 'Also show roles whose experience requirement is unstated',
                  'include_unknown_work_arrangement': 'Also show roles whose work arrangement is unstated',
                  'ai_consent': 'Enable hosted AI resume reviews after selecting a job',
                  'fallback_consent': 'Allow another configured AI provider if the first is unavailable'}
        help_texts = {'years_experience': 'Use 0 for a fresher with no professional experience. Degree duration and personal projects are not employment.',
                      'field_of_study': 'For example Computer Science, Mechanical Engineering, Finance, or Marketing. This is your search direction; it can differ from your resume.',
                      'search_scope': 'All roles searches your chosen field. Only selected roles narrows results to the role names you enter.',
                      'include_unknown_experience': 'Senior titles and stated experience requirements are still checked. An unstated requirement is not guaranteed to be suitable.',
                      'include_unknown_work_arrangement': 'Unstated arrangements are included only when you enable this. They are never assumed to be remote.',
                      'work_arrangement': 'Remote roles must also be open to your selected location or explicitly worldwide. Hybrid means a mix of office and remote work.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['titles_text'].initial = ', '.join(self.instance.titles)
            self.fields['locations_text'].initial = ', '.join(self.instance.locations)
            self.fields['excluded_titles_text'].initial = ', '.join(self.instance.excluded_titles)

    def clean_years_experience(self):
        years = self.cleaned_data['years_experience']
        if not 0 <= years <= 60:
            raise forms.ValidationError('Enter experience from 0 to 60 years.')
        return years

    def clean_graduation_year(self):
        value=self.cleaned_data.get('graduation_year')
        if value and not 1950 <= value <= 2100: raise forms.ValidationError('Enter a graduation year from 1950 to 2100.')
        return value

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('search_scope') == 'field' and not cleaned.get('field_of_study'):
            self.add_error('field_of_study', 'Enter the field you want to search.')
        if cleaned.get('search_scope') in {'education','combined'} and not (cleaned.get('education_major') or cleaned.get('degree_name')):
            self.add_error('education_major','Enter your degree or major for education-based recommendations.')
        if cleaned.get('search_scope') == 'roles' and not split_values(cleaned.get('titles_text', '')):
            self.add_error('titles_text', 'Enter at least one target role.')
        if cleaned.get('fallback_consent') and not cleaned.get('ai_consent'):
            self.add_error('fallback_consent', 'Enable hosted AI before allowing provider fallback.')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.titles = split_values(self.cleaned_data['titles_text'])
        instance.locations = split_values(self.cleaned_data['locations_text'])
        instance.excluded_titles = split_values(self.cleaned_data.get('excluded_titles_text', ''))
        instance.include_internships = instance.opportunity_type != 'jobs'
        if instance.work_arrangement == 'remote':
            instance.allow_remote = True
        instance.matching_policy_version = 0
        if commit: instance.save()
        return instance


class TailoringForm(forms.Form):
    use_ai = forms.BooleanField(required=False, label='Use optional AI to order supported items')
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        from .models import Resume
        self.fields['masters']=forms.ModelMultipleChoiceField(queryset=Resume.objects.filter(user=user),label='Choose master resumes (up to five)',widget=forms.CheckboxSelectMultiple)
        latest=Resume.objects.filter(user=user).first()
        if latest:self.fields['masters'].initial=[latest.pk]
    def clean_masters(self):
        masters=list(self.cleaned_data['masters'])
        if len(masters)>5:raise forms.ValidationError('Choose at most five master resumes.')
        if sum(len(master.text) for master in masters)>120000:raise forms.ValidationError('Choose a smaller set of master resumes (120,000 text characters maximum).')
        return masters
