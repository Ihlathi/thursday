"""Structured state is authoritative; semantic vectors are a derived ephemeral index."""
import json
from collections import deque
from .contracts import validate_def
from .memory import embed, similarity

class World:
    def __init__(self):
        self.system = None
        self.elements = {}
        self.index = {}
        self.revision = -1
        self.embedding_count = 0
        self.actions = deque(maxlen=8)
        self.task = None
        self.observations = deque(maxlen=8)
    def update(self, delta):
        validate_def('StateDelta', delta)
        if delta['revision'] < self.revision:
            return False
        self.revision = delta['revision']
        if 'system' in delta:
            self.system = delta['system']
        if delta.get('full'):
            ids = {e['id'] for e in delta.get('elements',[])}
            for eid in set(self.elements)-ids:
                self.elements.pop(eid,None); self.index.pop(eid,None)
        for eid in delta.get('removed_ids',[]):
            self.elements.pop(eid,None); self.index.pop(eid,None)
        for element in delta.get('elements',[]):
            eid=element['id']
            self.elements[eid]=element
            if element['sensitive']:
                self.index.pop(eid,None)
                continue
            text=' '.join(element[k] for k in ['role','name','description'])
            if self.index.get(eid, ('',))[0] != text:
                self.index[eid]=(text,embed(text))
                self.embedding_count += 1
        return True
    def search(self, query, limit=5):
        q=embed(query)
        hits=sorted(((similarity(q,v),eid) for eid,(_,v) in self.index.items()),reverse=True)
        return [self.public(self.elements[eid]) for score,eid in hits if score>0.05 and self.elements[eid]['visible']][:limit]
    @staticmethod
    def public(element):
        if element['sensitive']:
            return {'id':element['id'],'role':element['role'],'name':'[sensitive element]'}
        return {k:element[k] for k in ['id','role','name','description','enabled','visible','action_kind']}
    def context(self, query):
        return {'task':self.task, 'system':self.system, 'relevant_elements':self.search(query),
                'recent_actions':list(self.actions), 'observations':list(self.observations)}
