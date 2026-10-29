"""Manual recovery after observed HTTP401; no credential or security automation."""
import sys,time
from pathlib import Path
from threading import Event
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ykt.accounts import Accounts
from ykt.browser import open_browser,navigate
from ykt.downloader import verify_account
from ykt.storage import read_json,write_json

def main():
 a=Accounts(ROOT,'https://changjiang.yuketang.cn');row=a.get(read_json(ROOT/'.local/v2_stage1/gui_live.json')['new_account_id']);base=ROOT/'.local/v2_stage4';proof=dict(schema_version=1,observed_student_catalog_http=401,stage='waiting_manual_login')
 with open_browser(a.site_dir(row)/'browser',lambda _:None) as (_,page):
  navigate(page,a.origin+'/v2/web/index',Event(),lambda _:None,retries=0)
  write_json(base/'first_account_relogin.json',proof);print('FIRST_ACCOUNT_MANUAL_LOGIN_WINDOW_READY',flush=True)
  deadline=time.monotonic()+600
  while not (base/'first_logged_in.signal').exists():
   if (base/'deliver_with_limits.signal').exists() or time.monotonic()>deadline:
    proof.update(stage='not_completed',verified=False,reason='manual_login_not_completed');break
   time.sleep(.25)
  else:
   verify_account(page,a.origin,row['owner'],Event(),lambda _:None)
   proof.update(stage='complete',verified=True,same_owner_after_relogin=True)
 proof['context_closed']=True;write_json(base/'first_account_relogin.json',proof)
if __name__=='__main__':main()
