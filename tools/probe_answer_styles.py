"""Inspect visible result DOM/styles in an authorized report; no resource URLs."""
import sys
from pathlib import Path
from threading import Event

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ykt import selectors as S
from ykt.accounts import Accounts
from ykt.browser import open_browser
from ykt.downloader import verify_account
from ykt.extractor import extract_lesson
from ykt.storage import read_json,write_json


def main():
    accounts=Accounts(ROOT,'https://changjiang.yuketang.cn')
    account=next(row for row in accounts.rows if row['legacy'])
    task=read_json(ROOT/'.local/v2_stage3/page_probe.json')['task']
    with open_browser(accounts.site_dir(account)/'browser',lambda _:None) as (_,page):
        verify_account(page,accounts.origin,account['owner'],Event(),lambda _:None)
        result=extract_lesson(page,accounts.origin,task,Event(),lambda _:None)
        items=result['resources'][0]['frame'].locator(S.QUIZ_ITEMS)
        rows=[]
        for item in items.all():
            rows.append(item.evaluate("""e=>({text:e.innerText,nodes:[e,...e.querySelectorAll('*')]
              .filter(n=>n.getClientRects().length).map(n=>({tag:n.tagName,cls:n.className,
                text:n.innerText,color:getComputedStyle(n).color,background:getComputedStyle(n).backgroundColor,
                inline:n.getAttribute('style')}))})"""))
        write_json(ROOT/'.local/answer_dual/styles_probe.json',dict(source='live_browser',items=rows))
        for index,row in enumerate(rows):
            print('ITEM',index+1,[(n['tag'],n['cls'],n['text'],n['color'],n['background'])
                for n in row['nodes'] if n['cls'] and 'slide-img' not in str(n['cls']) and len(n['text'] or '')<160],flush=True)


if __name__=='__main__':main()
