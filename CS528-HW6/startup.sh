#!/bin/bash
set -euo pipefail
mkdir -p /opt/cs528-hw6
exec > >(tee -a /var/log/cs528-hw6.log /dev/console) 2>&1

# Upload a failure marker even when dependency installation/bootstrap fails.
finish() {
  code=$?
  trap - EXIT
  HW6_EXIT_CODE="$code" /usr/bin/python3 - <<'PY'
import json,os,urllib.request,urllib.parse
def metadata(key):
    r=urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/'+key,headers={'Metadata-Flavor':'Google'})
    return urllib.request.urlopen(r,timeout=15).read().decode()
try:
    token=json.loads(metadata('instance/service-accounts/default/token'))['access_token']
    bucket=metadata('instance/attributes/hw6-bucket')
    run=metadata('instance/attributes/hw6-run')
    prefix='cs528-hw6/runs/'+run+'/'
    def upload(name,data,kind):
        url='https://storage.googleapis.com/upload/storage/v1/b/'+bucket+'/o?uploadType=media&ifGenerationMatch=0&name='+urllib.parse.quote(prefix+name,safe='')
        req=urllib.request.Request(url,data=data,method='POST',headers={'Authorization':'Bearer '+token,'Content-Type':kind})
        urllib.request.urlopen(req,timeout=60).read()
    upload('startup.log',open('/var/log/cs528-hw6.log','rb').read(),'text/plain')
    if os.environ['HW6_EXIT_CODE']!='0':
        upload('failure.json',json.dumps({'status':'failed','exit_code':int(os.environ['HW6_EXIT_CODE'])}).encode(),'application/json')
except Exception as e:
    print('Could not upload final bootstrap status:',type(e).__name__,flush=True)
PY
  exit "$code"
}
trap finish EXIT
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip
/usr/bin/python3 - <<'PY'
import hashlib,io,json,pathlib,tarfile,urllib.request,urllib.parse
def metadata(key):
    r=urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/'+key,headers={'Metadata-Flavor':'Google'})
    return urllib.request.urlopen(r,timeout=15).read().decode()
token=json.loads(metadata('instance/service-accounts/default/token'))['access_token']
uri=metadata('instance/attributes/hw6-source')
expected=metadata('instance/attributes/hw6-sha256')
bucket,name=uri[5:].split('/',1)
url='https://storage.googleapis.com/storage/v1/b/'+bucket+'/o/'+urllib.parse.quote(name,safe='')+'?alt=media'
req=urllib.request.Request(url,headers={'Authorization':'Bearer '+token})
data=urllib.request.urlopen(req,timeout=120).read()
if hashlib.sha256(data).hexdigest()!=expected: raise RuntimeError('Source checksum mismatch')
root=pathlib.Path('/opt/cs528-hw6')
with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
    for member in archive.getmembers():
        if not member.isfile() or '/' in member.name or member.name.startswith('.'):
            raise RuntimeError('Unexpected source archive member')
        (root/member.name).write_bytes(archive.extractfile(member).read())
(root/'run-id').write_text(metadata('instance/attributes/hw6-run'))
(root/'source-sha256').write_text(expected)
PY
cd /opt/cs528-hw6
python3 -m venv .venv
.venv/bin/pip install --disable-pip-version-check -r requirements.txt
.venv/bin/pip freeze > installed-requirements.txt
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
export HW6_SOURCE_SHA256="$(cat source-sha256)"
.venv/bin/python -u run_models.py --cloud-run "$(cat run-id)" --output /opt/cs528-hw6/output
