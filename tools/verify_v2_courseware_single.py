"""First real single lesson gate, before batch implementation."""
import sys,json,tempfile
from pathlib import Path
from threading import Event
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ykt.accounts import Accounts
from ykt.storage import read_json,write_json
from ykt.browser import open_browser
from ykt.downloader import verify_account,_fetch
from ykt.files import image_info
from ykt.courseware import extract_courseware
from ykt.quiz_pdf import write_pdf,validate_pdf,sha_file
R=Path(__file__).resolve().parents[1];o='https://changjiang.yuketang.cn';a=Accounts(R,o);row=a.get(read_json(R/'.local/v2_stage1/gui_live.json')['new_account_id']);site=a.site_dir(row)
task=read_json(R/'.local/v2_stage3/page_probe.json')['task'];stop=Event(); paths=[];proof=[]
with open_browser(site/'browser',print) as (ctx,p):
 verify_account(p,o,row['owner'],stop,print)
 resources=extract_courseware(p,o,task,stop,print)
 with tempfile.TemporaryDirectory(prefix='ykt_stage3_single_') as work:
  for i,r in enumerate(resources):
   data=_fetch(ctx,r,r['candidates'][0],o,stop);info=image_info(data);path=Path(work)/(str(i)+info['extension']);path.write_bytes(data);paths.append(path)
   proof.append(dict(page=r['page'],slide_id=r['slide_id'],sha256=sha_file(path),size=len(data)))
   if stop.wait(.15):break
  target=R/'.local/v2_stage3/single_complete.pdf';target.unlink(missing_ok=True)
  write_pdf(target,paths,stop,page_size=(841.889764,595.275591))
  assert validate_pdf(target,len(resources),stop,page_size=(841.889764,595.275591))
  from pypdf import PdfReader
  import hashlib
  pdf=PdfReader(target)
  assert all(hashlib.sha256(p['/Resources']['/XObject']['/Im0'].get_object().get_data()).hexdigest()==r['sha256'] for p,r in zip(pdf.pages,proof))
  write_json(R/'.local/v2_stage3/single_verified.json',dict(schema_version=1,pages=len(pdf.pages),sequence=proof,original_jpeg_bytes_match=True,scope='report_accessible_static_slides_sorted_by_original_page'))
  print('SINGLE_VERIFIED',len(pdf.pages),flush=True)
