#!/usr/bin/env python3
from intent_postprocess import postprocess_intent
ctx={'current_datetime':'2026-08-28T17:00:00+09:00','timezone':'Asia/Seoul'}
cases=[
 ('광화문역에서 카페 갈래',
  {'companions':['friend'],'start_time_period':None,'end_time':None,'end_time_period':None,'transport_mode':'auto'},
  {'companions':[]}),
 ('7시에 홍대에서 친구 만나야 해. 그 전에 카페 갈래',
  {'companions':['friend'],'start_time_period':None,'end_time':'19:00','end_time_period':None,'transport_mode':'auto'},
  {'companions':[]}),
 ('성수에서 2~3시간 놀고 싶고 저녁쯤 잠실 가야 해',
  {'companions':[],'start_time_period':'evening','end_time':None,'end_time_period':None,'transport_mode':'auto'},
  {'start_time_period':None,'end_time_period':'evening'}),
 # guards: explicit current companion must remain
 ('친구랑 광화문역에서 카페 갈래',
  {'companions':['friend'],'start_time_period':None,'end_time':None,'end_time_period':None,'transport_mode':'auto'},
  {'companions':['friend']}),
 ('7시에 친구 만나야 해. 그 전에 혼자 카페 갈래',
  {'companions':['solo'],'start_time_period':None,'end_time':'19:00','end_time_period':None,'transport_mode':'auto'},
  {'companions':['solo']}),
 ('저녁에 성수에서 놀고 싶어',
  {'companions':[],'start_time_period':'evening','end_time':None,'end_time_period':None,'transport_mode':'auto'},
  {'start_time_period':'evening','end_time_period':None}),
 ('오후에 강남에서 약속 있어. 그 전에 카페 갈래',
  {'companions':[],'start_time_period':'pm','end_time':None,'end_time_period':None,'transport_mode':'auto'},
  {'start_time_period':None,'end_time_period':'pm'}),
]
for i,(text,pred,expected) in enumerate(cases,1):
    got,changes=postprocess_intent(text,ctx,pred)
    for k,v in expected.items():
        assert got.get(k)==v,(i,k,got.get(k),v,changes)
    print(f'[{i}/{len(cases)}] OK | {text} | changes={len(changes)}')
print('V1.3 FIX1 LOCAL POSTPROCESS TESTS: PASS')
