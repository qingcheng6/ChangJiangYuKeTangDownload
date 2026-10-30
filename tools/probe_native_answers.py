"""Inspect authorized quiz DOM; never persist image URLs or credentials."""
import sys
from urllib.parse import urlsplit
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
    a=Accounts(ROOT,'https://changjiang.yuketang.cn')
    row=next(r for r in a.rows if r['legacy'])
    task=read_json(ROOT/'.local/v2_stage3/page_probe.json')['task']
    with open_browser(a.site_dir(row)/'browser',lambda _:None) as (context,page):
        verify_account(page,a.origin,row['owner'],Event(),lambda _:None)
        result=extract_lesson(page,a.origin,task,Event(),lambda _:None)
        frame=result['resources'][0]['frame']
        items=frame.locator(S.QUIZ_ITEMS)
        proof=dict(schema_version=1,task=task,pages=result['pages'],items=[])
        for i in range(items.count()):
            item=items.nth(i)
            proof['items'].append(item.evaluate("""e=>({text:e.innerText,
               nodes:[e,...e.querySelectorAll('*')].map(n=>({tag:n.tagName,cls:n.className,
                 text:n.children.length===0?n.textContent:null,role:n.getAttribute('role')}))})"""))
        write_json(ROOT/'.local/answers/dom_probe.json',proof)
        print('QUIZ_DOM_INSPECTED',len(proof['items']),flush=True)
        for i,item in enumerate(proof['items'][:3]):
            print('ITEM',i+1,item['text'],flush=True)
        items.nth(0).locator(S.QUIZ_IMAGE_REGION).click(timeout=10000)
        detail=frame.locator('body').evaluate("""e=>({text:e.innerText,
          nodes:[...e.querySelectorAll('*')].filter(n=>n.children.length===0&&n.textContent.trim())
            .map(n=>({tag:n.tagName,cls:typeof n.className==='string'?n.className:'',text:n.textContent.trim().slice(0,500)}))})""")
        write_json(ROOT/'.local/answers/detail_probe.json',dict(schema_version=1,detail=detail))
        print('AFTER_OPEN',detail['text'],flush=True)
        extra=frame.locator(S.REPORT_VIEW).evaluate("""e=>{
          const s=e.__vue__?._setupState;const val=x=>x?.__v_isRef?x.value:x;
          return {showSwiper:val(s.showSwiper),showHorizontalView:val(s.showHorizontalView),
            visibleContainers:[...document.querySelectorAll('[class]')].filter(x=>x.getClientRects().length&&
              /swiper|viewer|modal|dialog|problem|answer/.test(x.className)).map(x=>({tag:x.tagName,cls:x.className,text:x.innerText?.slice(0,300)}))};}""")
        extra['pages']=[dict(path=urlsplit(p.url).path) for p in context.pages]
        extra['parent_text']=page.locator('body').inner_text()
        write_json(ROOT/'.local/answers/viewer_probe.json',dict(schema_version=1,detail=extra))
        page.screenshot(path=str(ROOT/'.local/answers/viewer.png'),full_page=True)
        print('VIEWER_FLAGS',extra['showSwiper'],extra['showHorizontalView'],len(context.pages),flush=True)
        # Normal navigation resets the image viewer; inspect the native exercise
        # result click separately instead of invoking internal application code.
        result=extract_lesson(page,a.origin,task,Event(),lambda _:None)
        frame=result['resources'][0]['frame']
        target=frame.locator(S.QUIZ_ITEMS).nth(0).locator('section.slide-exercise')
        extra=target.evaluate("""e=>({cursor:getComputedStyle(e).cursor,
          vnodeProps:Object.keys(e.__vnode?.props||{}),parentProps:Object.keys(e.parentElement.__vnode?.props||{})})""")
        target.click(timeout=10000)
        extra['text']=frame.locator('body').inner_text()
        write_json(ROOT/'.local/answers/result_click_probe.json',dict(schema_version=1,detail=extra))
        page.screenshot(path=str(ROOT/'.local/answers/result_clicked.png'),full_page=True)
        print('AFTER_RESULT_CLICK',extra['text'][-3000:],flush=True)


if __name__=='__main__':main()
