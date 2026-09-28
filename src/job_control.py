"""Linux runner cancellation, using pidfds to avoid signaling recycled PIDs."""
import os
from pathlib import Path
import signal
import time
import select


def runner_handles(root,job_id,script):
    handles=[]
    try:
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():continue
            fd=None
            try:
                fd=os.pidfd_open(int(entry.name))
                args=(entry/'cmdline').read_bytes().decode().strip('\0').split('\0')
                if (str(script) in args and '--execute' in args and '--workspace' in args
                    and args[args.index('--execute')+1]==job_id
                    and Path(args[args.index('--workspace')+1]).resolve()==root):
                    handles.append((int(entry.name),fd));fd=None
            except (ProcessLookupError,FileNotFoundError,PermissionError,IndexError,UnicodeError):pass
            finally:
                if fd is not None:os.close(fd)
        return handles
    except BaseException:
        for _,fd in handles:os.close(fd)
        raise


def terminate(handles):
    """Stop runner descendants too (e.g. an encoder), without signaling the worker."""
    descendants=[];parents={pid for pid,_ in handles}
    try:
        for _ in range(8):
            added=set()
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit() or int(entry.name) in parents:continue
                fd=None
                try:
                    fd=os.pidfd_open(int(entry.name))
                    stat=(entry/'stat').read_text().rsplit(')',1)[1].split()
                    if int(stat[1]) in parents:
                        descendants.append((int(entry.name),fd));fd=None;added.add(int(entry.name))
                except (ProcessLookupError,FileNotFoundError,PermissionError):pass
                finally:
                    if fd is not None:os.close(fd)
            if not added:break
            parents.update(added)
        for sig in (signal.SIGTERM,signal.SIGKILL):
            for _,fd in handles+descendants:
                try:signal.pidfd_send_signal(fd,sig)
                except ProcessLookupError:pass
            if sig==signal.SIGTERM:time.sleep(.3)
        for _,fd in handles+descendants:
            select.select([fd],[],[],2)
    finally:
        for _,fd in descendants:os.close(fd)
