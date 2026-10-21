"""Interpretable visual-center baseline. Scores are NOT calibrated probabilities."""
import math
from .annotations import label_at


from .config import get_config

def create_scorer():
    """Only the scorer implementing the live center-ID contract is supported."""
    config = get_config()
    if config.scoring.use_enhanced_scoring:
        raise ValueError('Enhanced scoring is experimental and not supported by the live pipeline')
    return CenterScorer()


class CenterScorer:
    def __init__(self):
        self.scores = {}
        self.current = ()
        self.candidate = ()
        self.candidate_since = 0.0
        self.previous_time = None
        self.face_count = 0
        self.reason = 'geometry'

    def update(self, people, timestamp):
        self.reason='geometry'
        dt = .067 if self.previous_time is None else max(.001, timestamp - self.previous_time)
        self.previous_time = timestamp
        if not people:
            self.current = self.candidate = ()
            self.face_count=0
            return [], "unknown"
        heights = [p["box"][3] - p["box"][1] for p in people]
        max_height = max(heights)
        fronts = [p["box"][3] for p in people]
        front = max(fronts)
        def torso_x(person):
            points=[person['pose'][i][0] for i in (5,6,11,12) if person['pose'][i][2]>=.5]
            return sum(points)/len(points) if len(points)>=3 else (person['box'][0]+person['box'][2])/2
        anchors={p['id']:torso_x(p) for p in people}
        xs = sorted(anchors.values())
        group_x = xs[len(xs)//2] if len(xs) % 2 else (xs[len(xs)//2-1] + xs[len(xs)//2])/2
        closeup = sorted(heights)[len(heights)//2] > .68
        max_area = max((p["box"][2]-p["box"][0])*h for p,h in zip(people,heights))
        alpha = 1 - math.exp(-dt/.16)
        live = {p["id"] for p in people}
        self.scores = {k:v for k,v in self.scores.items() if k in live}
        for p, height in zip(people, heights):
            # An outstretched arm changes the detection box center, not the
            # dancer's position. Prefer visible shoulders/hips as a body anchor.
            x = anchors[p['id']]
            size = min(1, height/max(max_height, .01))
            foreground = max(0, 1 - (front-p["box"][3])/max(max_height*.45, .08))
            anchor=.15*group_x+.85*.5 if closeup else .5*group_x+.5*.5
            central = max(0, 1-abs(x-anchor)/.5)
            visibility = sum(k[2] >= .45 for k in p["pose"])/17
            # Foreground height and formation geometry are proxies, not stage depth.
            area=math.sqrt(max(0,(p["box"][2]-p["box"][0])*height)/max(max_area,.001))
            # In close-ups, the frame center and visible body area carry more
            # evidence than clipped leg height. Wide shots retain front-row cues.
            raw = (.30*area+.10*foreground+.45*central+.15*visibility) if closeup else (.25*size+.30*foreground+.35*central+.10*visibility)
            old = self.scores.get(p["id"], raw)
            score = old + alpha*(raw-old)
            self.scores[p["id"]] = score
            p["score"] = round(score, 4)
            p["features"] = {"size":round(size,3), "foreground":round(foreground,3), "central":round(central,3), "visibility":round(visibility,3),"body_x":round(x,3)}
        ranked = sorted(people, key=lambda p:p["score"], reverse=True)
        first = ranked[0]
        proposal = ()
        if first["score"] >= .67 and first["confidence"] >= .5:
            if len(ranked) == 1 or first["score"]-ranked[1]["score"] >= .065:
                proposal = (first["id"],)
            else:
                second = ranked[1]
                ax=anchors[first['id']]
                bx=anchors[second['id']]
                separated=abs(ax-bx)>.16
                symmetric=abs((ax+bx)/2-group_x)<.13
                same_front=abs(first["box"][3]-second["box"][3])<.08
                above_rest=len(ranked)==2 or second["score"]-ranked[2]["score"]>.09
                # Equal-height rows have no pair-specific foreground evidence.
                pair_height=min(p["box"][3]-p["box"][1] for p in (first,second))
                foreground_lead=len(ranked)==2 or (
                    pair_height>1.12*max(p["box"][3]-p["box"][1] for p in ranked[2:]) or
                    min(first["box"][3],second["box"][3])-max(p["box"][3] for p in ranked[2:])>.05)
                if separated and symmetric and same_front and above_rest and foreground_lead and second["score"]>.75:
                    proposal=tuple(sorted((first["id"],second["id"])))
        # Pose landmark visibility supplies orientation contrast only, never identity.
        # A lone forward-facing performer among turned-away dancers can be the
        # visual focus even when choreography places them off the frame center.
        facing=[p for p in people if p['pose'][0][2]>.75]
        turned=[p for p in people if p['pose'][0][2]<.4]
        if (len(people)>=4 and len(facing)==1 and len(turned)==len(people)-1
                and facing[0]['score']>=.65 and facing[0]['confidence']>=.65
                and all(facing[0]['pose'][i][2]>.65 for i in (5,6,11,12))):
            proposal=(facing[0]['id'],)
            self.reason='orientation_contrast'
        # Near-uniform front-facing lines have no unique foreground lead.
        if (len(people)>=5 and not closeup and len(facing)==len(people)
                and max(fronts)-min(fronts)<.06 and max(heights)/max(min(heights),.01)<1.35):
            proposal=()
            self.reason='uniform_line'
        # Don't let a tall box enclosing multiple foreground heads win by area.
        if len(proposal)==1:
            winner=next(p for p in people if p['id']==proposal[0])
            if all(winner['pose'][i][2]>.6 for i in (11,12)):
                hip_y=max(winner['pose'][11][1],winner['pose'][12][1])
                x1,y1,x2,y2=winner['box']
                occluders=[p for p in people if p is not winner and p['pose'][0][2]>.5
                    and x1<p['pose'][0][0]<x2 and hip_y<p['pose'][0][1]<y2]
                if len(occluders)>=2:
                    proposal=()
                    self.reason='foreground_occlusion'
        proposal=self._count_faces(people, proposal, anchors)
        # Timing is resolved by CenterWindow, with bounded lookahead. Keeping
        # the previous winner here would put stale labels on a new formation.
        centers = list(proposal)
        self.face_count=len(centers)
        return centers, "dual" if len(centers)==2 else "single" if centers else "uncertain"

    def _count_faces(self, people, proposal, anchors):
        """Count visible faces in the visual center. A body box is not a person count."""
        if self.reason in ('uniform_line', 'foreground_occlusion'):
            return ()
        faced={p['id']:p for p in people if p['pose'][0][2]>=.55}
        if self.reason!='orientation_contrast':
            proposal=tuple(i for i in proposal if i in faced)
            if not proposal:
                ranked=sorted(faced.values(), key=lambda p:p['score'], reverse=True)
                if (ranked and ranked[0]['score']>=.67 and ranked[0]['confidence']>=.5
                        and (len(ranked)==1 or ranked[0]['score']-ranked[1]['score']>=.065)):
                    proposal=(ranked[0]['id'],)
                    self.reason='visible_face'
        pair=self._face_pair(faced, anchors)
        if pair and set(proposal)<=set(pair) and len(proposal)<=1:
            self.reason='face_pair'
            return pair
        return proposal

    @staticmethod
    def _face_pair(faced, anchors):
        """Two forward faces sharing the front-center count as two C positions."""
        ranked=sorted(faced.values(), key=lambda p:p['score'], reverse=True)
        if len(ranked)<2: return None
        first,second=ranked[0],ranked[1]
        if first['score']<.62 or second['score']<.62 or first['score']-second['score']>.14:
            return None
        if abs(anchors[first['id']]-anchors[second['id']])>.22: return None
        if abs(first['box'][3]-second['box'][3])>.10: return None
        heights=[p['box'][3]-p['box'][1] for p in (first,second)]
        if min(heights)<.75*max(heights): return None
        midpoint=(anchors[first['id']]+anchors[second['id']])/2
        if abs(midpoint-.5)>.18: return None
        rest=ranked[2:]
        if rest:
            ahead=min(first['box'][3],second['box'][3])-max(p['box'][3] for p in rest)
            clearer=min(first['score'],second['score'])-max(p['score'] for p in rest)
            if ahead<=.04 or clearer<=.05: return None
        return tuple(sorted((first['id'],second['id'])))


class CenterWindow:
    """Confirm sustained proposals without erasing their last frames.

    Evidence must belong to one contiguous run in one shot. Future samples
    establish a new run; already observed samples confirm its tail. Unknown
    proposals are never filled and the previous winner is never carried over.
    """
    def __init__(self, horizon=.3, minimum_duration=.15):
        self.horizon=horizon
        self.minimum_duration=minimum_duration
        self.pending=[]
        self.recent=[]

    @staticmethod
    def _same(a,b):
        return (a['shot']==b['shot'] and tuple(a['centers'])==tuple(b['centers'])
                and abs(a['end']-b['t'])<1e-5)

    def _emit(self):
        first=self.pending[0]
        start,end=first['t'],first['end']
        count=1
        previous=first
        for frame in reversed(self.recent):
            if not self._same(frame,previous):break
            start=frame['t'];count+=1;previous=frame
        previous=first
        for frame in self.pending[1:]:
            if frame['t']-first['t']>self.horizon+1e-5 or not self._same(previous,frame):break
            end=frame['end'];count+=1;previous=frame
        stable=bool(first['centers']) and count>=2 and end-start>=self.minimum_duration-1e-5
        raw=self.pending.pop(0)
        result=dict(raw)
        result['centers']=list(raw['centers']) if stable else []
        result['state']='dual' if len(result['centers'])==2 else 'single' if result['centers'] else 'uncertain'
        self.recent.append(raw)
        self.recent=[f for f in self.recent if raw['end']-f['t']<=self.horizon+1e-5]
        return result

    def feed(self,frame):
        result=[]
        if self.pending and frame['shot']!=self.pending[-1]['shot']:
            result.extend(self.finish())
        self.pending.append(frame)
        while self.pending and frame['t']-self.pending[0]['t']>=self.horizon-1e-5:
            result.append(self._emit())
        return result

    def finish(self):
        result=[]
        while self.pending:result.append(self._emit())
        self.recent=[]
        return result


def rescore_frames(frames):
    """Recompute center identity from stored poses. One scorer per shot."""
    window=CenterWindow()
    scorer=CenterScorer()
    shot=None
    emitted=[]
    for frame in frames:
        if frame['shot']!=shot:
            emitted.extend(window.finish())
            scorer=CenterScorer()
            shot=frame['shot']
        centers,state=scorer.update(frame['people'], frame['t'])
        proposal=dict(frame)
        proposal['centers']=list(centers)
        proposal['state']=state
        proposal['reason']=scorer.reason
        emitted.extend(window.feed(proposal))
    emitted.extend(window.finish())
    return emitted


def totals(frames, until=None):
    result = {}
    unknown = 0.0
    for f in frames:
        end = f["end"] if until is None else min(f["end"], until)
        dt = max(0, end-f["t"])
        if not dt: continue
        identities = set(f['centers'])
        if not f["centers"]:
            unknown += dt
        for identity in sorted(identities):
            row = result.setdefault(identity, {"id":identity,"seconds":0.0,"equivalent_seconds":0.0})
            row["seconds"] += dt
            row["equivalent_seconds"] += dt/len(identities)
    return sorted(result.values(), key=lambda x:-x["seconds"]), unknown


def named_totals(frames, labels, until=None, annotations=()):
    """Merge supported names within their evidence intervals; count duplicates once."""
    # One accounting implementation for the live API and both export formats.
    from .statistics import center_statistics
    result = center_statistics(frames, labels, annotations, until)
    rows = [{key: row[key] for key in ('name', 'seconds', 'equivalent_seconds', 'track_count')}
            for row in result['rows'] if row['named']]
    return rows, {'seconds': result['unbound'], 'equivalent_seconds': sum(
        row['equivalent_seconds'] for row in result['rows'] if not row['named'])}
