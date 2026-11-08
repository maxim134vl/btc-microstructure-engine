"""Small portable extended-attribute adapter for archival metadata only."""
import os, sys, ctypes, base64

def _darwin():
    lib=ctypes.CDLL(None,use_errno=True)
    lib.listxattr.argtypes=[ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int]
    lib.listxattr.restype=ctypes.c_ssize_t
    lib.getxattr.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_int]
    lib.getxattr.restype=ctypes.c_ssize_t
    lib.setxattr.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_int]
    lib.setxattr.restype=ctypes.c_int
    return lib

def _checked(n,path):
    if n<0:
        e=ctypes.get_errno();raise OSError(e,os.strerror(e),str(path))
    return n

def attributes(path):
    if hasattr(os,'listxattr'):
        return {k:base64.b64encode(os.getxattr(path,k,follow_symlinks=False)).decode()
                for k in os.listxattr(path,follow_symlinks=False)}
    if sys.platform!='darwin':raise RuntimeError('Extended-attribute API unavailable')
    lib=_darwin();p=os.fsencode(path)
    n=_checked(lib.listxattr(p,None,0,1),path)
    if not n:return {}
    buf=ctypes.create_string_buffer(n)
    got=_checked(lib.listxattr(p,buf,n,1),path);result={}
    for name in buf.raw[:got].split(b'\0'):
        if not name:continue
        size=_checked(lib.getxattr(p,name,None,0,0,1),path)
        if size:
            value=ctypes.create_string_buffer(size)
            count=_checked(lib.getxattr(p,name,value,size,0,1),path)
            raw=value.raw[:count]
        else:raw=b''
        result[os.fsdecode(name)]=base64.b64encode(raw).decode()
    return result

def restore_attributes(path,values):
    for name,value in values.items():
        raw=base64.b64decode(value)
        if hasattr(os,'setxattr'):os.setxattr(path,name,raw,follow_symlinks=False)
        elif sys.platform=='darwin':
            lib=_darwin();buf=ctypes.create_string_buffer(raw)
            _checked(lib.setxattr(os.fsencode(path),os.fsencode(name),buf,len(raw),0,1),path)
        else:raise RuntimeError('Extended-attribute API unavailable')
