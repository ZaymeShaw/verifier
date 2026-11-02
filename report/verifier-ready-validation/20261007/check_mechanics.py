"""Reproduce integrity blind spots in a disposable git repo only."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

out=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='ready-mechanics-') as directory:
    root=Path(directory)
    def git(*args):
        return subprocess.run(['git',*args],cwd=root,check=True,capture_output=True,text=True).stdout
    git('init','-q')
    (root/'file.txt').write_text('original\n')
    git('add','file.txt')
    git('-c','user.name=Experiment','-c','user.email=experiment@localhost','commit','-qm','fixture')
    (root/'file.txt').write_text('already dirty\n')
    before=git('status','--porcelain','-uall')
    first=hashlib.sha256((root/'file.txt').read_bytes()).hexdigest()
    (root/'file.txt').write_text('modified again by reviewer\n')
    after=git('status','--porcelain','-uall')
    second=hashlib.sha256((root/'file.txt').read_bytes()).hexdigest()
    review=root/'review.json';meta=root/'meta.json'
    review.write_text('{"findings":[{"severity":"blocking"}]}')
    meta.write_text(json.dumps({'review_sha256':hashlib.sha256(review.read_bytes()).hexdigest()}))
    review.write_text('{"findings":[]}')
    changed_only_review_valid=json.loads(meta.read_text())['review_sha256']==hashlib.sha256(review.read_bytes()).hexdigest()
    meta.write_text(json.dumps({'review_sha256':hashlib.sha256(review.read_bytes()).hexdigest()}))
    changed_both_valid=json.loads(meta.read_text())['review_sha256']==hashlib.sha256(review.read_bytes()).hexdigest()
    result={'porcelain':{'before':before,'after':after,'scope_valid_by_spec':before==after,'contents_actually_changed':first!=second},
            'co_writable_review_hash':{'changed_only_review_valid':changed_only_review_valid,'changed_review_and_meta_valid':changed_both_valid},
            'boundary':'disposable fixture; demonstrates content-audit and authenticity limits, not a claim that the agent will tamper'}
    (out/'mechanics-results.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
