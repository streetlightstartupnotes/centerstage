"""Optional local subtitle OCR. No face analysis or automatic identity inference."""
import queue
import re
import threading
import logging

import numpy as np


def prepare_caption_reader(directory):
    from rapidocr import RapidOCR
    reader = RapidOCR(params={
        'Global.model_root_dir': str(directory), 'Global.use_cls': False,
        'Global.log_level': 'error', 'EngineConfig.onnxruntime.intra_op_num_threads': 2,
        'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        'Det.limit_side_len': 960, 'Det.limit_type': 'max',
    })
    # Initialize lazy OCR models in the background; center analysis is already available.
    reader(np.full((200,640,3), 255, np.uint8))
    return reader


def _edit_distance(a, b):
    if abs(len(a)-len(b))>1: return 2
    previous=list(range(len(b)+1))
    for i, ca in enumerate(a, 1):
        current=[i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j]+1, current[-1]+1, previous[j-1]+(ca!=cb)))
        previous=current
    return previous[-1]


def read_names(rows, roster):
    """Return member names from a bracket only when every token is a known member.

    [OA] is one member. [MERCI, OA] is two. [VORA, All] is not VORA: an unresolved
    token means the line is not a clean member credit, so it names nobody.
    """
    known={n.upper():n for n in roster};found=[]
    normalize=lambda s:s.translate(str.maketrans({'0':'O','1':'I','|':'I'}))
    def resolve(token):
        token=token.strip()
        if not token: return None
        name=known.get(token)
        if name: return name
        matches=[v for k,v in known.items() if normalize(k)==normalize(token)]
        if len(matches)==1: return matches[0]
        # One insertion, deletion or substitution: [MERC] and [HMEKI] still name
        # MERCI and HIMEKI. Fragments shorter than four letters stay unresolved.
        if len(token)<4: return None
        folded=normalize(token)
        near=[v for k,v in known.items() if _edit_distance(normalize(k), folded)<=1]
        return near[0] if len(near)==1 else None
    for row in rows:
        if row.get('confidence',0)<.75:continue
        text=row.get('text','').strip().upper()
        groups=re.findall(r'\[([^\[\]]+)(?:\]|$)',text)
        if not groups and text in known:groups=[text]
        for group in groups:
            tokens=[resolve(token) for token in re.split(r'[,/&]',group)]
            if not tokens or any(token is None for token in tokens): continue
            for name in tokens:
                if name not in found: found.append(name)
    return found


def append_caption(meta, t, rows, hold=1.0):
    """Derive source-text hints from retained OCR, never person assignments.

    A credit lasts at most `hold` seconds and is cut at the next reading, so a
    name read at the start of a second does not stay on screen after the text changes.
    """
    names=read_names(rows,[r['name'] for r in meta.get('roster',[])])
    records=meta.setdefault('captions',[])
    t=round(float(t),3)
    if records and records[-1]['end']>t:
        records[-1]['end']=t
        if records[-1]['end']<=records[-1]['t']+1e-6: records.pop()
    if not names: return
    end=round(min(t+hold, meta['video']['duration']),3)
    if records and records[-1]['names']==names and t<=records[-1]['end']+1e-3:
        records[-1]['end']=max(records[-1]['end'], end)
        records[-1]['text']=[r['text'] for r in rows]
        return
    records.append({'t':t,'end':end,'names':names,'evidence':'printed_subtitle','text':[r['text'] for r in rows]})


def refresh_caption_hints(meta):
    meta['captions']=[]
    for item in meta.get('caption_text',[]):
        append_caption(meta,item['t'],item['rows'])


class CaptionWorker:
    def __init__(self,reader,job):
        self.reader=reader;self.job=job;self.queue=queue.Queue(maxsize=2);self.closed=False
        with job.lock:job.meta.update(caption_status='reading',captions=[],caption_text=[],caption_dropped=0,caption_engine='RapidOCR / PP-OCRv6 small')
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def submit(self,t,image):
        if self.closed:return
        try:self.queue.put_nowait((t,image))
        except queue.Full:
            with self.job.lock:self.job.meta['caption_dropped']+=1

    def run(self):
        try:
            while True:
                try:item=self.queue.get(timeout=.2)
                except queue.Empty:
                    if self.closed:break
                    continue
                if item is None:break
                t,image=item;result=self.reader(image)
                texts = result.txts if result.txts is not None else []
                scores = result.scores if result.scores is not None else []
                rows=[{'text':text,'confidence':float(score)} for text,score in zip(texts,scores) if np.isfinite(score)]
                with self.job.lock:
                    if rows:self.job.meta['caption_text'].append({'t':round(t,3),'rows':rows})
                    append_caption(self.job.meta,t,rows)
        except Exception:
            with self.job.lock:self.job.meta['caption_status']='unavailable'
        finally:
            self.closed=True
            with self.job.lock:
                if self.job.meta.get('caption_status') != 'unavailable':
                    self.job.meta['caption_status']='partial' if self.job.meta['caption_dropped'] else 'complete'
                try:self.job.save()
                except OSError:logging.exception('Failed to save optional caption hints')

    def close(self):
        if not self.closed:
            # Stop accepting work, drain at most two queued images, and persist
            # the final text even if OCR finishes after center analysis.
            self.closed=True
            self.thread.join(timeout=3)
        with self.job.lock:
            if self.job.meta.get('caption_status')=='reading':
                self.job.meta['caption_status']='partial' if self.thread.is_alive() or self.job.meta['caption_dropped'] else 'complete'
