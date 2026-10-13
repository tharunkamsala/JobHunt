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
