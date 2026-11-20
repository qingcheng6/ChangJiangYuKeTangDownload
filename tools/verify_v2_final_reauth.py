"""User-driven platform logout/relogin; never inputs credentials or deletes cookies."""
import sys,time,uuid
from pathlib import Path
from threading import Event
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ykt.accounts import Accounts
from ykt.browser import open_browser,NeedsHuman,ensure_login
from ykt.downloader import verify_account
from ykt.scanner import scan
from ykt.storage import read_json,write_json

def main():
 a=Accounts(ROOT,'https://changjiang.yuketang.cn');known=read_json(ROOT/'.local/v2_stage4/second_account.json');row=a.get(known['account_id']);old=a.get(known['previous_id']);stop=Event();base=ROOT/'.local/v2_stage4'
 proof=dict(schema_version=1,old_owner=old['owner'],second_owner=row['owner'],different_platform_owners=row['owner']!=old['owner'])
 def record(stage):proof['stage']=stage;write_json(base/'reauth_verified.json',proof);print('REAUTH_STAGE',stage,flush=True)
 def wait_for(name):
  deadline=time.monotonic()+1800
  while not (base/name).exists():
   if time.monotonic()>deadline:raise RuntimeError('Manual test timed out')
   time.sleep(.25)
 with open_browser(a.site_dir(row)/'browser',print) as (_,page):
  verify_account(page,a.origin,row['owner'],stop,print)
  try:verify_account(page,a.origin,old['owner'],stop,lambda _:None)
  except NeedsHuman:proof['wrong_owner_download_blocked']=True
  else:raise AssertionError('Wrong owner was not rejected')
  cache=a.site_dir(row)/'courses.json';before=cache.read_bytes()
  try:scan(page,a.origin,cache,stop,lambda _:None,expected_owner=old['owner'])
  except NeedsHuman:proof['wrong_owner_scan_blocked']=True
  else:raise AssertionError('Wrong owner scan was not rejected')
  assert cache.read_bytes()==before;proof['wrong_owner_cache_unchanged']=True
  record('ready_manual_logout');wait_for('logged_out.signal')
  try:ensure_login(page,a.origin,stop,print,timeout_ms=3000)
  except NeedsHuman:proof['logged_out_requires_human']=True
  else:raise AssertionError('Page still authenticated after reported logout')
  record('waiting_manual_relogin');wait_for('relogged_in.signal')
  verify_account(page,a.origin,row['owner'],stop,print);proof['same_second_owner_after_relogin']=True
  marker='ykt_stage4_'+uuid.uuid4().hex
  page.evaluate('(key)=>localStorage.setItem(key,"local-isolation-test")',marker)
  record('relogin_verified')
 with open_browser(a.site_dir(old)/'browser',print) as (_,page):
  verify_account(page,a.origin,old['owner'],stop,print)
  assert page.evaluate('(key)=>localStorage.getItem(key)',marker) is None
  proof['old_session_owner_preserved']=True;proof['local_storage_isolated']=True
 with open_browser(a.site_dir(row)/'browser',print) as (_,page):
  verify_account(page,a.origin,row['owner'],stop,print)
  assert page.evaluate('(key)=>localStorage.getItem(key)',marker)=='local-isolation-test'
  page.evaluate('(key)=>localStorage.removeItem(key)',marker);proof['persistent_second_session_verified']=True
 record('complete')
if __name__=='__main__':main()
