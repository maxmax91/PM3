import os
from time import sleep
from typing import Generator, List

from sqlmodel import Session
from PM3.model.process import Process, ION

from sqlalchemy import Engine

from sqlmodel import select, insert
from sqlalchemy.sql.expression import func

import fcntl

def is_hidden_proc(x: str) -> bool:
    return x.startswith('__') and x.endswith('__')




class Pm3Table:
    def __init__(self, tbl: Engine):
        self.tbl = tbl
    
    def next_id(self):
        with Session(self.tbl, expire_on_commit=False) as session:
            result = session.scalar(select(func.max(Process.pm3_id))) 
            return result + 1

    def select_all(self) -> Generator[Process, None, None]:
        with Session(self.tbl, expire_on_commit=False) as session:
            for row in session.exec( select(Process) ):
                yield row

    def select_many(self, val, col=Process.pm3_id) -> Generator[Process, None, None]:
        with Session(self.tbl, expire_on_commit=False) as session:
            for row in session.exec( select(Process).where(col == val) ):
                yield row
            
    def select_one(self, val, col=Process.pm3_id) -> Process:
        with Session(self.tbl) as session:
            results = session.exec(select(Process).where(col == val))
            return results.one_or_none()

    def delete(self, proc: Process):
        with Session(self.tbl, expire_on_commit=False) as session:
            result = session.exec( select(Process).where(Process.pm3_id == proc.pm3_id) ).one_or_none()
            if result is not None:
                session.delete(result)
                session.commit()
                return True
            else:
                return False

    def update_pid(self, proc: Process, pid: int):
        if proc.pid == pid:
            print("Same pid.")
            return

        with Session(self.tbl, expire_on_commit=False) as session:
            session.merge(proc)
            proc.pid = pid
            session.commit()


    def update(self, proc: Process):
        if self.select_one(proc.pm3_id, Process.pm3_id):
            with Session(self.tbl, expire_on_commit=False) as session:
                session.add(proc)
                session.commit()
                return True
        else:
            return False

    def update_pid(self, proc: Process, pid: int):
        with Session(self.tbl, expire_on_commit=False) as session:
            session.merge(proc)
            proc.pid = pid
            session.commit()

    def find_id_or_name(self, id_or_name, hidden=False) -> "ION":
        if id_or_name == 'all':
            # Tutti (nascosti esclusi)
            out = ION(type='special',
                    data=id_or_name,
                    proc=[i for i in self.select_all() if not is_hidden_proc(i.pm3_name)]
                    )
            return out

        elif id_or_name == 'ALL':
            # Proprio tutti (compresi i nascosti)
            out = ION(type='special', data=id_or_name, proc=[i for i in self.select_all()])
            return out
        elif id_or_name == 'hidden_only':
            # Solo i nascosti (nascosti esclusi)
            out = ION(type='special',
                    data=id_or_name,
                    proc=[i for i in self.select_all() if is_hidden_proc(i.pm3_name)]
                    )
            return out

        elif id_or_name == 'autorun_only':
            # Tutti gli autorun (compresi i sospesi)
            out = ION(type='special',
                    data=id_or_name,
                    proc=[i for i in self.select_all() if i.autorun is True])
            return out
        elif id_or_name == 'autorun_enabled':
            # Gruppo di autorun non sospesi
            out = ION(type='special',
                    data=id_or_name,
                    proc=[i for i in self.select_all() if i.autorun is True and i.autorun_exclude is False])
            return out

        try:
            id_or_name = int(id_or_name) 
        except ValueError: # it's a name
            if p := self.select_one(id_or_name, col=Process.pm3_name):
                out = ION(type='pm3_name', data=id_or_name,  proc=[p, ])
            else:
                out = ION(type='pm3_name', data=id_or_name, proc=[])
                
        else:
            if p_data := self.select(id_or_name, col=Process.pm3_id):
                out = ION(type='pm3_id', data=id_or_name, proc=[Process(p_data), ])
            else:
                out = ION(type='pm3_id', data=id_or_name, proc=[])
        return out


    def _insert_process(self, proc: Process, rewrite=False):
        proc.pm3_id = self.next_id() if proc.pm3_id is None else proc.pm3_id

        name_list = self.select(Process.pm3_name, proc.pm3_name)
        id_list = self.select(Process.pm3_id, proc.pm3_id)

        if name_list is not None:
            if not rewrite:
                proc.pm3_name = f'{proc.pm3_name}_{proc.pm3_id}'

        if id_list is not None:
            
            if rewrite:
                # replace the record
                self.tbl.delete().where( Process.pm3_id == proc.pm3_id)
                self.tbl.insert().values( [ proc ] )
                return 'OK'
            return 'ID_ALREADY_EXIST'
        elif name_list is not None:
            return 'NAME_ALREADY_EXIST'
        else:
            with Session(self.tbl, expire_on_commit=False) as session:
                session.begin()
                try:
                    session.add(proc)
                except:
                    session.rollback()
                    raise
                else:
                    session.commit()
            return 'OK'