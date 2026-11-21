import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from context_check import inspect
from long_job import run
try:
    import pymupdf
except ImportError:
    pymupdf=None


class ContextTest(unittest.TestCase):
    def test_senses_cross_page_and_empty_scope(self):
        rows=[{'id':'heading','source':'Gear #4 — Transparency','target':'维度 4 — 透明度'},
              {'id':'gear','source':'landing gear','target':'起落架'},
              {'id':'a','source':'may occur a few times','target':'可能发生数次，'},
              {'id':'b','source':'over all systems of this kind','target':'按全部同型系统合计。'}]
        rules=[{'id':'heading','source_pattern':r'Gear\s*#\s*4','required_target':['维度 4']},
               {'id':'qualifier','source_pattern':'all systems','groups':[['a','b']],'required_target':['全部同型系统合计']}]
        self.assertEqual(inspect(rows,rules)['status'],'PASS')
        rows[0]['target']='4号车';rows[-1]['target']='以及考虑同型系统。'
        self.assertEqual([r['status'] for r in inspect(rows,rules)['checks']],['REVIEW','REVIEW'])
        self.assertEqual(inspect(rows,[{'id':'none','source_pattern':'unrelated','required_target':['abc']}])['checks'][0]['status'],'UNMEASURED')


@unittest.skipUnless(pymupdf,'Requires PDF parser')
class LongJobTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.db=self.root/'job.sqlite'; self.pdf=self.root/'source.pdf'
        self.inv=self.root/'inventory.jsonl';self.settings=self.root/'settings.json'
        with pymupdf.open() as doc:
            for i in range(3):doc.new_page().insert_text((40,40),str(i))
            doc.save(self.pdf)
        self.rows=[{'id':str(i),'page':i,'role':'body','source':f'Heading {i}'} for i in range(1,4)]
        self.inv.write_text('\n'.join(map(json.dumps,self.rows)),encoding='utf8')
        self.settings.write_text('{}',encoding='utf8')
        self.init=dict(pdf=self.pdf,inventory=self.inv,settings=self.settings,pages_per_batch=2)
    def call(self,cmd,**kw):return run(Namespace(command=cmd,db=self.db,**kw))
    def test_resume_retry_and_integrity_guards(self):
        key=self.call('init',**self.init)['job']
        self.assertEqual(self.call('init',**self.init)['job'],key)
        with self.assertRaises(ValueError):self.call('export',output=self.root/'export')
        path=self.root/'next'
        self.call('next',output=path)
        batch=json.loads(path.read_text(encoding='utf8'));self.assertEqual(batch['following']['id'],'3')
        good={'job':key,'batch':1,'results':[{'id':str(i),'action':'translated','target':'案例'} for i in (1,2)]}
        def submit(receipt):
            p=self.root/'receipt';p.write_text(json.dumps(receipt),encoding='utf8')
            return self.call('commit',input=p)
        for change in [dict(good,job='wrong'),dict(good,results=good['results'][::-1]),
                       dict(good,results=good['results'][:1]),dict(good,results=[good['results'][0]]*2)]:
            with self.assertRaises(ValueError):submit(change)
        self.assertEqual(self.call('status')['committed'],0)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('INSERT INTO receipts VALUES(1,?)',('interrupted write',))
            db.rollback()
        self.assertEqual(submit(good)['next_batch'],2)
        with ThreadPoolExecutor(2) as pool:
            states=list(pool.map(lambda _:self.call('commit',input=self.root/'receipt'),range(2)))
        self.assertEqual([v['committed'] for v in states],[1,1])
        with self.assertRaises(ValueError):submit(dict(good,results=[dict(good['results'][0],target='改'),good['results'][1]]))
        last={'job':key,'batch':2,'results':[{'id':'3','action':'preserved','target':'identifier','basis':'source identifier'}]}
        self.assertEqual(submit(last)['status'],'CONTENT_ASSEMBLED')
        output=self.root/'export';self.call('export',output=output)
        self.assertEqual([json.loads(x)['id'] for x in output.read_text(encoding='utf8').splitlines()],['1','2','3'])
        with self.assertRaises(FileExistsError):self.call('export',output=output)
        self.settings.write_text('{"new":true}',encoding='utf8')
        with self.assertRaises(ValueError):self.call('status')
    def test_missing_page_and_unrelated_database(self):
        original=self.inv.read_bytes()
        self.inv.write_text(json.dumps(self.rows[0]),encoding='utf8')
        with self.assertRaises(ValueError):self.call('init',**self.init)
        self.inv.write_bytes(original)
        with closing(sqlite3.connect(self.db)) as db:db.execute('CREATE TABLE user_data (id)')
        with self.assertRaises(ValueError):self.call('init',**self.init)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT name FROM sqlite_master').fetchall(),[('user_data',)])
