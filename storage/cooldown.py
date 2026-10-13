"""Persist access-restriction cooldowns across independent workflow runs."""
from datetime import datetime, timedelta, timezone

def retry_time(source,clock=None):
    value=source.get('retry_after')
    if not value: return None
    try: deadline=datetime.fromisoformat(value)
    except (TypeError,ValueError): return None
    if deadline.tzinfo is None: return None
    return value if deadline>(clock or datetime.now(timezone.utc)) else None

def after_restriction(config,clock=None):
    return ((clock or datetime.now(timezone.utc))+
            timedelta(hours=config.get('restriction_cooldown_hours',2))).isoformat()
