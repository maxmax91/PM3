from PM3.model.pm3_protocol import ION
from PM3.model.process import Process
from tinydb import where
from tinydb.table import Table
import fcntl

def hidden_proc(x: str) -> bool:
    return x.startswith('__') and x.endswith('__')


class Pm3Table:
    def __init__(self, tbl: Table, lock_file: str):
        self.tbl = tbl
        self.lock_file = lock_file
        self.locked_file_descriptor = None
    
    def acquireLock(self):
        ''' acquire exclusive lock file access '''
        locked_file_descriptor = open(self.lock_file, 'w+')
        fcntl.lockf(locked_file_descriptor, fcntl.LOCK_EX)
        self.locked_file_descriptor = locked_file_descriptor

    def releaseLock(self):
        ''' release exclusive lock file access '''
        self.locked_file_descriptor.close()
        
    def locked_function():
        def wrapper(func):
            def inner(self, *args, **kwargs):
                self.acquireLock()
                print("locking")
                output = func(self, *args, **kwargs)
                self.releaseLock()
                print("unlocking")
                return output
            return inner
        return wrapper
    
    @locked_function()
    def next_id(self, start_from=None):
        if start_from:
            # Next Id start from specific id
            pm3_id = start_from
            while self.check_exist(pm3_id):
                pm3_id += 1
            return pm3_id
        else:
            if len(self.tbl.all()) > 0:
                return max([i['pm3_id'] for i in self.tbl.all()])+1
            else:
                return 1

    @locked_function()
    def check_exist(self, val, col='pm3_id'):
        return self.tbl.contains(where(col) == val)

    @locked_function()
    def select(self, proc, col='pm3_id'):
        return self.tbl.get(where(col) == proc.model_dump()[col])

    @locked_function()
    def delete(self, proc, col='pm3_id'):
        if self.select(proc, col):
            self.tbl.remove(where(col) == proc.model_dump()[col])
            return True
        else:
            return False

    @locked_function()
    def update(self, proc, col='pm3_id'):
        if self.select(proc, col):
            self.tbl.update(proc, where(col) == proc.model_dump()[col])
            return True
        else:
            return False

    @locked_function()
    def find_id_or_name(self, id_or_name, hidden=False) -> ION:
        if id_or_name == 'all':
            # Tutti (nascosti esclusi)
            out = ION('special',
                      id_or_name,
                      [Process(**i) for i in self.tbl.all() if not hidden_proc(i['pm3_name'])]
                      )
            return out

        elif id_or_name == 'ALL':
            # Proprio tutti (compresi i nascosti)
            out = ION('special', id_or_name, [Process(**i) for i in self.tbl.all()])
            return out

        elif id_or_name == 'hidden_only':
            # Solo i nascosti (nascosti esclusi)
            out = ION('special',
                      id_or_name,
                      [Process(**i) for i in self.tbl.all() if hidden_proc(i['pm3_name'])]
                      )
            return out

        elif id_or_name == 'autorun_only':
            # Tutti gli autorun (compresi i sospesi)
            out = ION('special',
                      id_or_name,
                      [Process(**i) for i in self.tbl.all() if i['autorun'] is True])
            return out
        elif id_or_name == 'autorun_enabled':
            # Gruppo di autorun non sospesi
            out = ION('special',
                      id_or_name,
                      [Process(**i) for i in self.tbl.all() if i['autorun'] is True and i['autorun_exclude'] is False])
            return out

        try:
            id_or_name = int(id_or_name)
        except ValueError:
            if self.check_exist(id_or_name, col='pm3_name'):
                p_data = self.tbl.get(where('pm3_name') == id_or_name)
                out = ION('pm3_name', id_or_name, [Process(**p_data), ])
            else:
                out = ION('pm3_name', id_or_name, [])

        else:
            if self.check_exist(id_or_name, col='pm3_id'):
                p_data = self.tbl.get(where('pm3_id') == id_or_name)
                out = ION('pm3_id', id_or_name, [Process(**p_data), ])
            else:
                out = ION('pm3_id', id_or_name, [])
        return out
