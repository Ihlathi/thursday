from agent.memory import WorkingMemory, LongTermMemory
from agent.world import World
from agent.platform import element

def test_working_ttl_and_long_term_promotion(tmp_path):
    now=[0]; w=WorkingMemory(10,lambda:now[0]); w.add('user','hello')
    now[0]=9; assert w.read()
    now[0]=11; assert not w.read()
    path=tmp_path/'memory.db'; m=LongTermMemory(path)
    assert m.consider('I prefer large text')
    assert not m.consider('password: secret')
    assert not m.consider('Remember everything from my bank account')
    m.close(); m=LongTermMemory(path)
    assert m.retrieve('bigger text')==['I prefer large text']
    m.clear(); assert m.retrieve('text')==[]; m.close()

def test_semantic_index_deltas_coordinates_and_sensitive():
    w=World(); e=element(); w.update({'revision':1,'elements':[e],'full':True})
    assert w.search('show me stuff I bought recently')[0]['id']=='orders'
    count=w.embedding_count
    e=dict(e,bounds={'x':100,'y':10,'width':180,'height':40})
    w.update({'revision':2,'elements':[e]}); assert w.embedding_count==count
    w.update({'revision':3,'elements':[dict(e,name='New label')]}); assert w.embedding_count==count+1
    assert not w.update({'revision':1,'elements':[],'full':True})
    w.update({'revision':4,'elements':[dict(e,sensitive=True)]}); assert not w.search('orders')
    w.update({'revision':5,'removed_ids':['orders']}); assert not w.elements and not w.index
