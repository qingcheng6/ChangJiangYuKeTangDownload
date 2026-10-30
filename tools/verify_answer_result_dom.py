"""Local HTML boundary cases for the selector observed in the real report."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright,Error
from ykt.extractor import answer_for_item
from ykt.storage import write_json


def main():
    cases=[
        ('green_full','green','2/2','AB','AB','', 'AB'),
        ('green_spaces','green','2 / 2','AB','AB','', 'AB'),
        ('green_partial','green','1/2','AB','AB','', None),
        ('red_full','red','2/2','AB','AB','', None),
        ('unknown_color','gray','2/2','AB','AB','', None),
        ('green_class_red_color','green red','2/2','AB','AB','', None),
        ('green_status_only','green','2/2','全对',None,'', None),
        ('score_missing','green','','AB','AB','', None),
        ('score_invalid','green','NaN/NaN','AB','AB','', None),
        ('official_priority','red','0/2','AB','AB','<p>正确答案：C</p>', 'C'),
        ('hidden_official','green','2/2','AB','AB','<p style="display:none">正确答案：C</p>', 'AB'),
        ('hidden_result','green','2/2','AB','AB','', None),
        ('duplicate_result','green','2/2','AB','AB','', None),
    ]
    proof=dict(source='local_dom_fixture',cases={})
    with sync_playwright() as p:
        try:browser=p.chromium.launch(headless=True)
        except Error:browser=p.chromium.launch(channel='chrome',headless=True)
        try:
            page=browser.new_page()
            for label,cls,score,result,submitted,official,expected in cases:
                prefix='提交答案: ' if submitted else ''
                style='display:none' if label=='hidden_result' else ''
                duplicate='<span class="pr12 green">AB</span>' if label=='duplicate_result' else ''
                page.set_content('<style>.green {color:rgb(8,188,114)}.red {color:rgb(248,79,65)}</style>'
                    '<div class="slide-item"><div class="slide-img"></div>'+official+
                    '<section class="slide-exercise" style="'+style+'"><span>'+prefix+
                    '<span class="pr12 '+cls+'">'+result+'</span> 得分: '+score+
                    '</span>'+duplicate+'<span class="pl12">用时2秒</span></section></div>')
                decision=answer_for_item(page.locator('.slide-item'))
                assert decision['answer']==expected,(label,decision)
                proof['cases'][label]=dict(answer=decision['answer'],status=decision['status'])
        finally:browser.close()
    write_json(ROOT/'.local/answer_dual/dom_fixture_verified.json',proof)
    print('LOCAL_RESULT_DOM_CASES_PASS',len(cases))


if __name__=='__main__':main()
