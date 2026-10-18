"""Sharing tests use disposable fixtures; no credentials, cloud or live archive writes."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import shared_archive as s
import shared_viewer as v


class SharedTests(unittest.TestCase):
    def test_publication_receive_and_incomplete_transfer_preserves_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, cloud, cache = root/'data', root/'cloud', root/'cache'
            day = '2026-10-07'
            name = 'snapshot-' + 'a'*32
            folder = data/day/name
            folder.mkdir(parents=True)
            s.write_json(folder/'index.json', {'status':'saved','revision':'a'*32,'stocks':[{'code':'005930'}]})
            s.write_json(data/day/'latest.json', {'folder':name,'revision':'a'*32})
            s.write_json(data/'notes'/day/'005930.json', {'text':'private note'})
            (data/'server.lock').write_text('must not copy')
            (data/'.env').write_text('must not copy')
            with patch.object(s, 'profiles', return_value={'groups':[],'names':{},'hero4':{}}):
                first = s.publish(cloud,data)
                second = s.publish(cloud,data)
            self.assertEqual(first,second)
            target, doc = s.receive(cloud,cache)
            self.assertTrue((target/'notes'/day/'005930.json').is_file())
            self.assertFalse((target/'.env').exists())
            self.assertFalse((target/'server.lock').exists())
            self.assertEqual(s.receive(cloud,cache)[0],target)
            bad = dict(doc,generation='b'*32)
            s.write_json(cloud/'snapshot.json',bad)
            (cloud/'day-2026-10-07.zip').write_bytes(b'partial')
            with self.assertRaises(ValueError):s.receive(cloud,cache)
            self.assertTrue((target/'_shared_ready.json').is_file())
            self.assertEqual(json.loads((cache/'last-ready.json').read_text())['folder'],target.name)

    def test_zip_traversal_and_modified_payload_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);packed=root/'bad.zip'
            with zipfile.ZipFile(packed,'w') as z:
                z.writestr('../outside','x')
                z.writestr('_bundle_manifest.json',json.dumps({'sha256':{'../outside':'x'}}))
            with self.assertRaises(ValueError):s.unpack_checked(packed,root/'safe')
            self.assertFalse((root/'outside').exists())
            (root/'good.json').write_text('good')
            s.zip_files(packed,[(root/'good.json','good.json')])
            s.unpack_checked(packed,root/'safe')
            self.assertEqual((root/'safe/good.json').read_text(),'good')

    def test_saved_chart_cache_never_requires_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            saved={'bars':[{'ts':'2026-10-07 09:00:00','open':100,'high':102,'low':99,'close':101,'volume':10}],
                   'raw':{'pages':[]},'fetched_at':'2026-10-07T09:01:00+09:00'}
            s.write_json(root/'chart_history/2026-10-07/005930.json',saved)
            s.write_json(root/'watchlist_history/2026-10-07/005930.json',saved)
            self.assertEqual(v.cached_history(root,'2026-10-07','005930','chart_history',240)['bars'],saved['bars'])
            record,raw=v.cached_minute(root,'2026-10-07','005930','Samsung')
            self.assertEqual(record['bars'],saved['bars'])
            with self.assertRaises(v.DataError):v.cached_history(root,'2026-10-07','000001','chart_history',240)


if __name__ == '__main__':unittest.main()
