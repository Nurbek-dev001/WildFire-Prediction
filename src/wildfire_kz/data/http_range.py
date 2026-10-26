"""Bounded read-only HTTP range file for public, immutable scientific objects."""
import io
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import requests


class HTTPRangeFile(io.RawIOBase):
    def __init__(self,url,size,etag=None):
        self.url=url;self.size=int(size);self.etag=etag;self.position=0
        self.blocks=OrderedDict();self.session=requests.Session();self.block_size=65536

    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        self.position=offset if whence==0 else self.position+offset if whence==1 else self.size+offset
        if self.position<0:raise ValueError('Negative file offset')
        return self.position

    def read(self,size=-1):
        if size<0:size=self.size-self.position
        size=min(size,self.size-self.position)
        if size<=0:return b''
        if size>32*1024**2:raise MemoryError('Refuse unbounded global raster read')
        lo=self.position;hi=lo+size
        first=lo//self.block_size;last=(hi-1)//self.block_size
        missing=[i for i in range(first,last+1) if i not in self.blocks]
        if missing:
            start=missing[0]*self.block_size;end=min((missing[-1]+1)*self.block_size,self.size)-1
            def fetch(bounds):
                left,right=bounds
                headers={'Range':f'bytes={left}-{right}'}
                if self.etag:headers['If-Match']=self.etag
                # Independent sessions avoid sharing mutable session state across
                # threads; HDF5 itself is accessed only on the calling thread.
                response=requests.get(self.url,headers=headers,timeout=(15,45))
                response.raise_for_status()
                if (response.status_code!=206 or len(response.content)!=right-left+1
                        or response.headers.get('Content-Range')!=f'bytes {left}-{right}/{self.size}'):
                    raise ValueError('Provider ignored or truncated HTTP range')
                return response.content
            if end-start>524288:
                spans=[(left,min(left+262144-1,end)) for left in range(start,end+1,262144)]
                with ThreadPoolExecutor(max_workers=8) as pool:
                    payload=b''.join(pool.map(fetch,spans))
            else:
                payload=fetch((start,end))
            for number in range(missing[0],missing[-1]+1):
                offset=number*self.block_size-start
                self.blocks[number]=payload[offset:offset+self.block_size]
        result=b''.join(self.blocks[i] for i in range(first,last+1))[lo-first*self.block_size:hi-first*self.block_size]
        self.position=hi
        for i in range(first,last+1):self.blocks.move_to_end(i)
        while len(self.blocks)>128:self.blocks.popitem(last=False)
        return result

    def readinto(self,buffer):
        data=self.read(len(buffer));buffer[:len(data)]=data;return len(data)

    def close(self):
        self.session.close();self.blocks.clear();super().close()
