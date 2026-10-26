"""Range integrity matters: prevent wrong bytes being accepted as predictor data."""
import numpy as np
import pytest
from wildfire_kz.data.http_range import HTTPRangeFile


class Response:
    status_code=206
    def __init__(self,body,start,end,total):
        self.content=body[start:end+1]
        self.headers={'Content-Range':f'bytes {start}-{end}/{total}'}
    def raise_for_status(self):pass


def test_random_access_matches_source_and_keeps_object_condition(monkeypatch):
    source=np.random.default_rng(42).integers(0,256,1024*1024,dtype=np.uint8).tobytes()
    calls=[]
    def fetch(url,headers,timeout):
        assert headers['If-Match']=='"fixed-etag"'
        start,end=map(int,headers['Range'][6:].split('-'))
        calls.append((start,end))
        return Response(source,start,end,len(source))
    monkeypatch.setattr('wildfire_kz.data.http_range.requests.get',fetch)
    with HTTPRangeFile('https://public.example/source',len(source),'"fixed-etag"') as f:
        for start,size in [(10,100),(65000,2000),(120000,700000),(65000,2000)]:
            f.seek(start)
            assert f.read(size)==source[start:start+size]
        assert len(f.blocks)<=128
    assert all(end-start+1<=524288 for start,end in calls)


@pytest.mark.parametrize('failure',['ignored_range','wrong_range','truncated'])
def test_rejects_provider_range_corruption(monkeypatch,failure):
    def fetch(url,headers,timeout):
        r=Response(b'x'*100000,0,65535,100000)
        if failure=='ignored_range':r.status_code=200
        elif failure=='wrong_range':r.headers['Content-Range']='bytes 1-65536/100000'
        else:r.content=r.content[:-1]
        return r
    monkeypatch.setattr('wildfire_kz.data.http_range.requests.get',fetch)
    with HTTPRangeFile('https://public.example/source',100000) as f:
        with pytest.raises(ValueError,match='range'):f.read(10)
