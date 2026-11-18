import hashlib, json
from datetime import datetime, timezone
from app.config import RULE_VERSION

def digest(raw, context, packages=None):
    material=raw + json.dumps(context,ensure_ascii=False,sort_keys=True).encode() + RULE_VERSION.encode()
    if packages:
        material+=json.dumps(packages,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(material).hexdigest()

def make_manifest(source_digest, source, elapsed):
    return {'run_id':source_digest[:16], 'sha256':source_digest, 'rule_version':RULE_VERSION,
            'source':source, 'generated_at':datetime.now(timezone.utc).isoformat(),
            'elapsed_ms':round(elapsed*1000,3), 'timezone':'Asia/Shanghai'}
