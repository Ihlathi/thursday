"""Separate working and persistent preference memories; fully local vectors."""
import hashlib
import json
import math
import re
import sqlite3
import time
from collections import Counter, deque
from pathlib import Path

# Transparent, small synonym layer + stable feature hashing. Replaceable embedder.
SYNONYMS = {'bought':'purchase', 'purchased':'purchase', 'purchases':'purchase',
            'orders':'purchase', 'order':'purchase', 'shopping':'purchase',
            'returns':'purchase', 'recently':'recent', 'larger':'large',
            'bigger':'large', 'volume':'sound', 'audio':'sound'}

def embed(text, dimensions=256):
    words = [SYNONYMS.get(w, w) for w in re.findall(r'[a-z0-9]+', text.lower())]
    counts = Counter(words)
    vector = [0.0] * dimensions
    for word, count in counts.items():
        i = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], 'big') % dimensions
        vector[i] += count
    norm = math.sqrt(sum(x*x for x in vector)) or 1
    return [x/norm for x in vector]

def similarity(a,b):
    return sum(x*y for x,y in zip(a,b))

def sensitive(text):
    return bool(re.search(r'password|secret|token|api.?key|ssn|credit.?card|\b\d{9,}\b|[\w.+-]+@[\w.-]+', text, re.I))

class WorkingMemory:
    def __init__(self, ttl=1800, clock=time.monotonic):
        self.ttl, self.clock = ttl, clock
        self.items = deque(maxlen=24)
        self.last = clock()
    def read(self):
        if self.clock() - self.last > self.ttl:
            self.clear()
        return list(self.items)
    def add(self, role, text):
        self.read()
        self.items.append({'role':role, 'text':text[:2000]})
        self.last = self.clock()
    def clear(self):
        self.items.clear()
        self.last = self.clock()

class LongTermMemory:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        path.chmod(0o600)
        self.db.execute('CREATE TABLE IF NOT EXISTS memory (text TEXT PRIMARY KEY, vector TEXT, created REAL)')
    def consider(self, text):
        # Promote only explicit accessibility preferences, not arbitrary history.
        if sensitive(text) or len(text) > 500:
            return False
        if not re.fullmatch(r'(?:remember(?: that)? )?i prefer (?:large text|high contrast|spoken responses|reduced motion)[.!]?', text.strip(), re.I):
            return False
        self.db.execute('INSERT OR REPLACE INTO memory VALUES (?,?,?)', (text,json.dumps(embed(text)),time.time()))
        self.db.commit()
        return True
    def retrieve(self, query, limit=3):
        q=embed(query)
        scored=[(similarity(q,json.loads(v)),t) for t,v in self.db.execute('SELECT text,vector FROM memory')]
        return [t for score,t in sorted(scored,reverse=True)[:limit] if score>0.05]
    def clear(self):
        self.db.execute('DELETE FROM memory')
        self.db.commit()
    def close(self):
        self.db.close()
