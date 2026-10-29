import sys,json
from pathlib import Path
from threading import Event
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ykt.accounts import Accounts
from ykt.storage import read_json,write_json
from ykt.browser import open_browser,wait_condition,navigate
from ykt.downloader import verify_account
from ykt.extractor import ReportWatch,_wait_state
from ykt import selectors as S
R=Path(__file__).resolve().parents[1]; o='https://changjiang.yuketang.cn'; a=Accounts(R,o)
row=a.get(read_json(R/'.local/v2_stage1/gui_live.json')['new_account_id']); site=a.site_dir(row)
c=read_json(site/'courses.json'); historic=read_json(next((R/'.local/phase3_output/雨课堂习题下载').glob('任务清单_*.json')))
l=next(x for x in historic['lessons'].values() if x['status']=='no_images'); course=next(x for x in c['courses'] if x['id']==l['course_id']); lesson=next(x for x in course['lessons'] if x['id']==l['lesson_id']); task=dict(course_id=course['id'],course_name=course['name'],lesson=lesson)
stop=Event()
with open_browser(site/'browser',print) as (ctx,p):
 verify_account(p,o,row['owner'],stop,print)
 with ReportWatch(p,o,lesson['courseware_id']) as w:
  navigate(p,o+S.REPORT_PATH.format(course_id=course['id'],courseware_id=lesson['courseware_id'],lesson_id=lesson['id']),stop,print)
  wait_condition(p,S.REPORT_FRAME_READY,stop)
  f=p.locator(S.REPORT_IFRAME).element_handle().content_frame(); state=_wait_state(p,f,w,course['id'],stop)
  info=f.locator(S.REPORT_VIEW).evaluate('''e=>({text:e.innerText,html:e.outerHTML.replace(/https?:[^"\\s<>]+/g,'[url]').slice(0,19000),keys:Object.keys(e.__vue__?._setupState||{}), counts:{img:e.querySelectorAll('img').length,canvas:e.querySelectorAll('canvas').length,video:e.querySelectorAll('video').length},links:[...e.querySelectorAll('a,button')].map(x=>({tag:x.tagName,text:x.textContent,download:x.hasAttribute('download')}))})''')
  info['resource_shapes']=[dict(index=i,page=state['slides'][i]['page'],data=item.evaluate(S.QUIZ_RESOURCE_DATA),html=item.evaluate('''e=>e.outerHTML.replace(/https?:[^"\\s<>]+/g,'[url]').slice(0,3500)''')) for i,item in enumerate(f.locator(S.QUIZ_ITEMS).all()) if len(item.evaluate(S.QUIZ_RESOURCE_DATA)['resources'])!=1]
  for shape in info['resource_shapes']:
   shape['data']['resources']=[{'candidate_count':len(r['candidates'])} for r in shape['data']['resources']]
  info['last_slide']=f.locator(S.REPORT_VIEW).evaluate('''e=>{const x=e.__vue__._setupState.lessonTimelineSlides;const a=x?.__v_isRef?x.value:x;return a.slice(-2).map(s=>({keys:Object.keys(s),id:s.id,index:s.index,type:s.type,visible:s.visible,cover:!!s.cover,video:!!s.video,url:!!s.url}))}''')
  info['preview']=f.locator(S.REPORT_VIEW).evaluate('''e=>{const s=e.__vue__._setupState;const v=x=>x?.__v_isRef?x.value:x;return {tabs:v(s.tabOptions),previewCount:v(s.swiperList)?.length,preview:v(s.swiperList)?.map(x=>({id:String(x.id),page:x.index})),horizontal:v(s.hasHorizontalBtn)}}''')
  info['outer_text']=p.locator('body').inner_text()[:5000]
  info['state']={k:v for k,v in state.items() if k!='slides'}; info['slides']=[{k:v for k,v in x.items() if k!='cover'} for x in state['slides']]
  p.pdf(path=str(R/'.local/v2_stage3/math_native_print.pdf'),print_background=True,landscape=True)
  write_json(R/'.local/v2_stage3/math_probe.json',dict(schema_version=1,task=task,info=info))
  print(json.dumps({k:v for k,v in info.items() if k not in ('html','text','slides','keys')},ensure_ascii=False),flush=True)
