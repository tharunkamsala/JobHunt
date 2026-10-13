from protego import Protego

def test_explicit_allow_overrides_root_disallow():
    policy=Protego.parse('User-agent: *\nDisallow: /\nAllow: /careers\nAllow: /careerhub/explore/jobs\n')
    assert policy.can_fetch('https://example.com/careers?query=software','NewGradJobHunter')
    assert policy.can_fetch('https://example.com/careerhub/explore/jobs/123','NewGradJobHunter')
    assert not policy.can_fetch('https://example.com/private','NewGradJobHunter')
