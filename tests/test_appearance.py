import numpy as np
import pytest

from centerstage.appearance import GarmentLinker,garment_descriptor
from centerstage.scoring import CenterScorer


def pose():
    p=np.zeros((17,3),np.float32)
    p[[5,6,12,11]]=[[30,30,1],[70,30,1],[65,80,1],[35,80,1]]
    p[0]=[50,15,1]
    return p


def descriptor(color):
    image=np.full((100,100,3),color,np.uint8)
    return garment_descriptor(image,pose())


def observe(linker,ids,descriptors,start,shot,count=6):
    for i in range(count):
        linker.update([{'id':key,'garment':d} for key,d in zip(ids,descriptors)],start+i*.21,shot)


def test_descriptor_excludes_head_and_rejects_missing_or_contaminated_core():
    image=np.zeros((100,100,3),np.uint8);image[30:85]=[20,80,180]
    before=garment_descriptor(image,pose())
    image[:30]=[255,255,255]
    assert garment_descriptor(image,pose())==before
    bad=pose();bad[5,2]=.1
    assert garment_descriptor(image,bad) is None
    peer=pose();peer[0]=[50,55,1]
    assert garment_descriptor(image,pose(),[peer]) is None
    assert len(before)==120 and np.all(np.isfinite(before))


def test_multi_frame_cross_shot_association_and_later_contradiction():
    linker=GarmentLinker();red=descriptor([0,0,255])
    observe(linker,['a'],[red],0,0)
    observe(linker,['b'],[red],2,1,count=3)
    assert linker.links()=={}  # An isolated match doesn't establish continuity.
    observe(linker,['b'],[red],2.7,1)
    assert linker.links()['a']['group_id']==linker.links()['b']['group_id']
    assert linker.links()['a']['tentative'] is True
    observe(linker,['a','b'],[red,red],4.2,2,count=1)
    assert linker.links()=={} and linker.conflicts==1


def test_similar_uniforms_and_co_present_tracks_are_not_forced_together():
    linker=GarmentLinker();red=descriptor([0,0,255]);blue=descriptor([255,0,0])
    observe(linker,['a','b'],[red,red],0,0)
    observe(linker,['c'],[red],2,1)
    assert linker.links()=={}  # Two equally plausible candidates: reject.
    observe(linker,['d'],[blue],4,2)
    assert linker.links()=={}
    observe(linker,['e'],[None],6,3)
    assert linker.links()=={}


def test_audit_is_observational_and_explains_rejections():
    baseline=GarmentLinker();audited=GarmentLinker(audit=True)
    red=descriptor([0,0,255]);blue=descriptor([255,0,0])
    for linker in (baseline,audited):
        observe(linker,['a','b'],[red,red],0,0)
        observe(linker,['c'],[red],2,1)  # Ambiguous uniform, not a match.
        observe(linker,['d'],[blue],4,2)  # Dissimilar clothing.
        observe(linker,['e'],[None],6,3)
    assert baseline.links()==audited.links()=={}
    assert baseline.tracks==audited.tracks
    assert baseline.audit is None
    counts=audited.audit
    assert counts['ambiguous']>0 and counts['distance_rejected']>0
    assert counts['missing_descriptor']==6
    assert counts['match_attempts']==sum(counts[k] for k in (
        'no_candidate','distance_rejected','ambiguous','awaiting_votes','target_active','merges'))
    assert counts['observations']==sum(counts[k] for k in (
        'missing_descriptor','sample_throttled','gallery_samples','linked_gallery_frozen'))


def performer(key,x,nose=1):
    points=[[x,.3,1] for _ in range(17)]
    points[0]=[x,.2,nose]
    for i in (5,6):points[i]=[x,.35,1]
    for i in (11,12):points[i]=[x,.6,1]
    return dict(id=key,box=[x-.07,.1,x+.07,.9],confidence=.99,pose=points)


def test_orientation_contrast_selects_visible_focus_without_subtitles():
    people=[performer('focus',.3),performer('back1',.45,.1),performer('back2',.6,.1),performer('back3',.75,.1)]
    scorer=CenterScorer()
    assert scorer.update(people,0)[0]==['focus']
    assert scorer.reason=='orientation_contrast'
    for p in people:p['pose'][0][2]=.1
    scorer.update(people,.1)
    assert scorer.reason!='orientation_contrast'


def test_uniform_line_is_unknown_even_with_small_perspective_size_difference():
    people=[performer(str(i),x) for i,x in enumerate([.2,.35,.5,.65,.8])]
    for p in people:p['box'][1]=.4
    people[2]['box'][1]=.38
    scorer=CenterScorer();assert scorer.update(people,0)[0]==[]


def test_foreground_people_inside_tall_detection_do_not_create_a_center():
    center=performer('rear',.5);center['box']=[.3,.05,.7,.99]
    others=[performer('front1',.43),performer('front2',.57)]
    for p in others:
        p['box'][1]=.72;p['pose'][0][1]=.8
    scorer=CenterScorer();result=scorer.update([center,*others],0)
    assert result[0]==[] and scorer.reason=='foreground_occlusion'


def test_two_forward_faces_in_front_count_as_two_centers():
    left=performer('a',.44); right=performer('b',.56); back=performer('c',.5)
    for person in (left,right):
        person['box']=[person['box'][0],.08,person['box'][2],.98]
    back['box']=[.42,.4,.58,.62]
    scorer=CenterScorer()
    centers,state=scorer.update([left,right,back],0)
    assert centers==['a','b'] and state=='dual' and scorer.face_count==2


def test_a_body_without_a_visible_face_is_not_counted_as_center():
    person={'id':'a','box':[.3,.1,.7,.95],'confidence':.99,'pose':[[.5,.2,.1]]+[[.5,.5,.99]]*16}
    scorer=CenterScorer()
    assert scorer.update([person],0)==([],'uncertain')
    assert scorer.face_count==0


def test_member_credit_names_only_the_sole_visible_center():
    from centerstage.annotations import annotations_from_member_credits
    def frame(t, track, nose=.9):
        person=performer(track,.5,nose)
        return dict(t=t,end=t+.5,shot=1,people=[person],centers=[track])
    frames=[frame(0,'1-1'),frame(.5,'1-1'),frame(1,'1-2',.05),frame(1.5,'1-2',.05)]
    captions=[{'t':0,'end':1,'names':['OA']},{'t':1,'end':2,'names':['MERCI']}]
    roster=[{'name':'OA'},{'name':'MERCI'}]
    notes=annotations_from_member_credits(frames,captions,roster)
    assert {(n['track_id'],n['name']) for n in notes}=={('1-1','OA')}
    assert notes[0]['start']==0 and notes[0]['end']==1
    frames[2]['people'][0]['pose'][0][2]=.9
    frames[3]['people'][0]['pose'][0][2]=.9
    notes=annotations_from_member_credits(frames,captions,roster)
    assert {n['name'] for n in notes}=={'OA','MERCI'}


def test_one_track_keeps_each_credit_in_its_own_interval():
    from centerstage.annotations import annotations_from_member_credits
    def frame(t, nose=.9):
        person=performer('1-1',.5,nose)
        return dict(t=t,end=t+.5,shot=1,people=[person],centers=['1-1'])
    frames=[frame(0),frame(.5),frame(1),frame(1.5)]
    captions=[{'t':0,'end':1,'names':['VORA']},{'t':1,'end':2,'names':['OA']}]
    notes=annotations_from_member_credits(frames,captions,[{'name':'VORA'},{'name':'OA'}])
    assert [(n['name'], n['start'], n['end']) for n in notes]==[('VORA',0,1),('OA',1,2)]


def test_a_name_follows_the_same_person_onto_the_next_track():
    from centerstage.annotations import annotations_from_member_credits
    frames=[
        dict(t=0,end=.5,shot=1,people=[performer('1-1',.5)],centers=['1-1']),
        dict(t=.5,end=1,shot=1,people=[performer('1-2',.52)],centers=['1-2']),
    ]
    notes=annotations_from_member_credits(frames,[{'t':0,'end':.5,'names':['OA']}],[{'name':'OA'}])
    assert {(n['track_id'], n['name']) for n in notes}=={('1-1','OA'),('1-2','OA')}
    frames[1]['people']=[performer('1-2',.9)]
    notes=annotations_from_member_credits(frames,[{'t':0,'end':.5,'names':['OA']}],[{'name':'OA'}])
    assert {(n['track_id'], n['name']) for n in notes}=={('1-1','OA')}


def test_a_credit_name_stays_with_the_same_center_after_the_line_leaves():
    from centerstage.annotations import annotations_from_member_credits
    frames=[dict(t=i/2,end=i/2+.5,shot=1,people=[performer('1-1',.5)],centers=['1-1']) for i in range(4)]
    notes=annotations_from_member_credits(frames,[{'t':0,'end':.5,'names':['OA']}],[{'name':'OA'},{'name':'MERCI'}])
    assert [(n['name'], n['start'], n['end']) for n in notes]==[('OA',0,2)]
    notes=annotations_from_member_credits(frames,[{'t':0,'end':.5,'names':['OA']},{'t':1,'end':2,'names':['MERCI']}],[{'name':'OA'},{'name':'MERCI'}])
    assert [(n['name'], round(n['start'],3), round(n['end'],3)) for n in notes]==[('OA',0,1),('MERCI',1,2)]
