import pytest
from models import Job
from filters.eligibility import classify
@pytest.mark.parametrize('title,loc,desc,expected',[
 ('Software Engineer I','Seattle, WA','Minimum 1 year of experience building software.','Strong Match'),
 ('Senior Software Engineer','United States','New graduate welcome','Not Eligible'),
 ('Software Engineer','India','Entry level software role','Not Eligible'),
 ('Software Engineer','United States','Minimum 5 years of experience','Not Eligible'),
 ('Software Engineer','United States','3 years preferred; new graduate role','Strong Match'),
 ('Software Engineer','United States','Build software systems','Needs Review'),
 ('Software Intern','United States','Computer science students','Not Eligible'),
 ('Software Engineer','India; United States','Entry level','Strong Match'),
])
def test_rules(title,loc,desc,expected):
 assert classify(Job('Test','1',title,loc,'https://example.com/jobs/1',desc)).classification==expected

@pytest.mark.parametrize('title',[
 'Software Development Engineer II','SDE 2','SDE-2','SDE II','Software Engineer 2',
 'Software Engineer II','Software Engineer III','SWE II','Software Developer II',
 'Software Engineer, Level 2','Senior Software Engineer','Data Engineer',
 'Applied Scientist','Hardware Engineer','Product Manager',
])
def test_exclude_other_families_and_levels(title):
 assert classify(Job('Amazon','1',title,'United States','https://example.com/1','New graduate, software development.')).classification=='Not Eligible'

@pytest.mark.parametrize('title',[
 'Software Development Engineer I','SDE I','SDE 1','Software Engineer I',
 'Software Engineer – New College Grad','Software Developer','SWE',
])
def test_allow_sde_titles(title):
 assert classify(Job('Microsoft','1',title,'United States','https://example.com/1','Entry level software development.')).classification=='Strong Match'

def test_only_requested_companies_configured():
 import json
 from pathlib import Path
 configs=json.loads((Path(__file__).resolve().parents[1]/'config/companies.json').read_text())
 assert {c['name'] for c in configs if not c['name'].startswith('Greenhouse:')}=={'Microsoft','Amazon','NVIDIA'}
 assert all(c.get('strict_new_grad_year')==2027 and c.get('software_only') is False for c in configs if c['name'].startswith('Greenhouse:'))

@pytest.mark.parametrize('title,description,eligible',[
 ('Software Engineer - New Grad 2027','Build software systems.',True),
 ('Data Engineer','Seeking new graduates graduating between December 2026 and June 2027.',True),
 ('Software Engineer','You must graduate in 2027.',True),
 ('Software Engineer - New Grad 2026','Copyright 2027.',False),
 ('Software Engineer - New Grad','Build systems in 2027.',False),
 ('Software Engineer','Entry level role. Copyright 2027.',False),
 ('Software Engineer','New graduates from the class of 2026.',False),
 ('Software Engineer','2027 graduates are not eligible.',False),
 ('Software Engineer II - New Grad 2027','Build software.',False),
 ('Software Intern 2027','Graduating in 2027.',False),
 ('Accountant - New Grad 2027','Entry level role.',False),
])
def test_strict_2027_new_grad(title,description,eligible):
 j=Job('Greenhouse: Databricks','1',title,'United States','https://example.com/1',description)
 classify(j,software_only=False,strict_new_grad_year=2027)
 assert (j.classification!='Not Eligible') is eligible
