#!/usr/bin/env python3

import asyncio
from contextlib import asynccontextmanager
import os, sys
import time
from typing import Union

from fastapi import FastAPI, Request, requests
import uvicorn
from PM3.model.process import Process
from PM3.model.pm3_protocol import RetMsg, KillMsg, alive_gone
import logging
from collections import namedtuple
from configparser import ConfigParser
import dsnparse
import psutil
from pathlib import Path
from PM3.libs.pm3table import Pm3Table, ION
import threading
from sqlmodel import Field, SQLModel, create_engine

from PM3.libs.common import pm3_home_dir, config_file, config, backend_process_name, cron_checker_process_name, logger




if not os.path.isfile(config_file):
    logger.critical(f'Config file not found at {config_file}')
    sys.exit(1)

# creation of the database
pm3_db_name = Path(config['main_section'].get('pm3_db')).expanduser()

db = create_engine("sqlite://" + str(pm3_db_name))
logger_sqlalchemy = logging.getLogger('sqlalchemy.engine')
logger_sqlalchemy.setLevel(logging.DEBUG)



SQLModel.metadata.create_all(db)


ptbl = Pm3Table(db)
app = FastAPI()


# Processi avviati localmente con popen:
# key = pid
# value = processo Popen
local_popen_process = {}

def _resp(res: RetMsg) -> dict:
    if res.err:
        logging.error(res.msg)
    if res.warn:
        logging.warning(res.msg)
    return res.model_dump()


def _start_process(proc: Process, ion: ION) -> RetMsg:
    if proc.get_pid() > 0:
        # Already running
        msg = f'process {proc.pm3_name} (id={proc.pm3_id}) already running with pid {proc.pid}'
        return RetMsg(msg=msg, warn=True)
    elif proc.restart >= proc.max_restart:
        # Max request exceded
        msg = f'ERROR, process {proc.pm3_name} (id={proc.pm3_id}) exceded max_restart {proc.restart}/{proc.max_restart}'
        return RetMsg(msg=msg, err=True)
    else:
        try:
            p = proc.run()
            local_popen_process[proc.pid] = p
            if not ptbl.update(proc):
                # Update Error
                msg = f'Error updating {proc}'
                return RetMsg(msg=msg, err=True)
        except FileNotFoundError as e:
            #print(e)
            # File not found
            msg = f'File Not Found: {e.filename} {Path(proc.cwd, proc.cmd).as_posix()} ({ion.type}={ion.data})'
            return RetMsg(msg=msg, err=True)
        else:
            # OK, process started
            msg = f'process {proc.pm3_name} (id={proc.pm3_id}) started with pid {proc.pid}'
            return RetMsg(msg=msg, err=False)



def ps_proc_as_dict(ps_proc):
    '''
    Versione corretta di psutil.Process().as_dict()
    La versione originale non aggiorna i valori di CPU
    :param ps_proc:
    :return:
    '''
    ppad = ps_proc.as_dict()
    ppad['cpu_percent'] = ps_proc.cpu_percent(interval=0.1)
    return ppad

@app.get("/")
async def home():
    return "pm3 running"

@app.get("/ping")
async def pong():
    pid = os.getpid()
    payload = {'pid': pid}
    return _resp(RetMsg(msg=f'PONG! pid {pid}', err=False, payload=payload))

@app.post("/new")
@app.post("/new/rewrite")
async def new_process(request: Request):
    logging.debug(request.json() )
    proc = Process(**await request.json() )

    ret = ptbl._insert_process( proc, rewrite=True if 'rewrite' in request.url.path else False)

    if ret == 'ID_ALREADY_EXIST':
        msg = f'process with id={proc.pm3_id} already exist'
        return _resp(RetMsg(msg=msg, warn=True))
    elif ret == 'NAME_ALREADY_EXIST':
        msg = f'process with name={proc.pm3_name} already exist'
        return _resp(RetMsg(msg=msg, err=True))
    elif ret == 'OK':
        msg = f'process [bold]{proc.pm3_name}[/bold] with id={proc.pm3_id} was added'
        return _resp(RetMsg(msg=msg, err=False))
    else:
        msg = f'Strange Error :('
        return _resp(RetMsg(msg=msg, err=True))


def _local_kill(proc ):
    p : Process = local_popen_process[proc.pid]
    local_pid = p.pid
    #p.kill()
    Process.kill_proc_tree(local_pid)
    for i in range(5):
        _ = p.poll()
        if not proc.is_running:
            break
        time.sleep(1)
    else:
        return KillMsg(msg='OK', alive=[alive_gone(pid=local_pid),], warn=True)
    # Elimino l'elemento dal dizionario
    _ = local_popen_process.pop(local_pid, None)
    return KillMsg(msg='OK', gone=[alive_gone(pid=local_pid), ])

def _interal_poll():
    for local_pid, p in local_popen_process.items():
        p.poll()

async def _interal_poll_thread():
    # Interrogazione ciclica dei processi avviati da PM3
    # i processi contenuti in local_popen_process
    # vanno periodicamente interrogati
    while True:
        try:
            # Do some work here
            logger.debug('Interrogazione')
            _interal_poll()
            await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.debug('Interrogation thread stopping')
            break


@app.get("/stop/{id_or_name}")
@app.get("/restart/{id_or_name}")
@app.get("/rm/{id_or_name}")
async def stop_and_rm_process(id_or_name):
    logging.debug(f"Stopping process {id_or_name}")
    resp_list = []
    ion = ptbl.find_id_or_name(id_or_name)
    if len(ion.proc) == 0:
        msg = f'process {ion.type}={ion.data} not found'
        resp_list.append(_resp(RetMsg(msg=msg, err=True)))

    for proc in ion.proc:
        if proc.pid in local_popen_process:
            # Processi attivati da os.getpid() vanno trattati con popen
            ret = _local_kill(proc)
            logging.debug(f'local kill process {proc}')
        else:
            ret = proc.kill()
            logging.debug(f'simple kill process {proc}')

        if ret.msg == 'OK':
            proc.autorun_exclude = True
            ptbl.update(proc)
            for pk in ret.gone:
                msg = f'process {proc.pm3_name} (id={proc.pm3_id}) with pid {pk.pid} was killed'
                resp_list.append(_resp(RetMsg(msg=msg, err=False)))
        
        elif ret.warn:
            for pk in ret.alive:
                msg = f'process {proc.pm3_name} (id={proc.pm3_id}) with pid {pk.pid} still alive'
                resp_list.append(_resp(RetMsg(msg=msg, warn=True)))
            if len(ret.alive) == 0:
                msg = f'process {proc.pm3_name} (id={proc.pm3_id}) not running'
                resp_list.append(_resp(RetMsg(msg=msg, warn=True)))
        else:
            msg = f'strange Error'
            resp_list.append(_resp(RetMsg(msg=msg, warn=True)))

        if request.path.startswith('/rm/'):
            if not ptbl.delete(proc):
                msg = f'error updating {proc}'
                resp_list.append(_resp(RetMsg(msg=msg, err=True)))
            else:
                msg = f'process {proc.pm3_name} (id={proc.pm3_id}) removed'
                resp_list.append(_resp(RetMsg(msg=msg, err=False)))

    if request.path.startswith('/restart/'):
        resp_list += start_process(id_or_name)['payload']

    ret_msg = RetMsg(msg='', payload=resp_list)

    return _resp(ret_msg)

@app.get("/ls/{id_or_name}")
async def ls_process(id_or_name: Union [str,int]):
    payload = []
    ion = ptbl.find_id_or_name(id_or_name)
    for proc in ion.proc:
        # Aggiorno lo stato dei processi
        _interal_poll()
        # Trick for update pid
        pid = proc.get_pid()
        logger.debug(f"Updating pid from {proc.pid} to {pid}")
        ptbl.update_pid(proc, pid)

        payload.append(proc)
    return RetMsg(msg='OK', err=False, payload=payload).model_dump()

@app.get("/ps/{id_or_name}")
async def pstatus(id_or_name: Union [str,int]):
    procs = []
    ion = ptbl.find_id_or_name(id_or_name)
    for proc in ion.proc:
        # Trick for update pid
        if id_or_name == 0 and proc.pid != os.getpid():
            proc.pid = os.getpid()
        ptbl.update(proc)  # Aggiorno anche il database
        procs.append(proc)

    payload = []
    for proc in procs:
        if proc.pid > 0:
            payload.append({**proc.model_dump(), **ps_proc_as_dict(psutil.Process(proc.pid))})

            # Children process
            for ps_proc in psutil.Process(proc.pid).children(recursive=True):
                payload.append({**proc.model_dump(), **ps_proc_as_dict(ps_proc)})

    return _resp(RetMsg(msg='OK', err=False, payload=payload))

@app.get("/reset/{id_or_name}")
async def reset(id_or_name: Union [str,int]):
    resp_list = []
    ion = ptbl.find_id_or_name(id_or_name)
    for proc in ion.proc:
        proc.reset()
        if not ptbl.update(proc):
            msg = f'Error updating {proc}'
            resp_list.append(_resp(RetMsg(msg=msg, err=True)))
        else:
            msg = f'process {proc.pm3_name} (id={proc.pm3_id}) reset'
            resp_list.append(_resp(RetMsg(msg=msg, err=False)))
    return _resp(RetMsg(msg='', payload=resp_list))

@app.get("/start/{id_or_name}")
async def start_process(id_or_name: Union [str,int]):
    resp_list = []
    ion = ptbl.find_id_or_name(id_or_name)
    if len(ion.proc) == 0:
        msg = f'process {ion.type}={ion.data} not found'
        resp_list.append(_resp(RetMsg(msg=msg, err=True)))

    for proc in ion.proc:
        resp_list.append(_resp(_start_process(proc, ion)))
    return _resp(RetMsg(msg='', payload=resp_list))

def _make_fake_backend(pid, cwd):
    proc = Process(cmd=config['backend'].get('cmd'),
                   interpreter=config['main_section'].get('main_interpreter'),
                   pm3_name=backend_process_name,
                   pm3_id=0,
                   shell=False,
                   nohup=True,
                   stdout=f'{pm3_home_dir}/{backend_process_name}.log',
                   stderr=f'{pm3_home_dir}/{backend_process_name}.err',
                   pid=pid,
                   cwd=cwd,
                   restart=1,
                   max_restart=100000)
    return proc

def _make_cron_checker():
    proc = Process(cmd=config['cron_checker'].get('cmd'),
                   interpreter=config['main_section'].get('main_interpreter'),
                   pm3_name=cron_checker_process_name,
                   pm3_id=-1,
                   shell=False,
                   nohup=True,
                   stdout=f'{pm3_home_dir}/{cron_checker_process_name}.log',
                   stderr=f'{pm3_home_dir}/{cron_checker_process_name}.err',
                   max_restart=100000
                   )
    return proc


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_interal_poll_thread())
    yield
    # Add any logs or commands before shutting down.
    print('It is shutting down...')

app = FastAPI(lifespan=lifespan)


def main():
    my_pid = os.getpid()
    my_cwd = os.getcwd()
    url = config['backend'].get('url')
    dsn = dsnparse.parse(url)

    # __backend__ process
    ion_backend = ptbl.find_id_or_name(backend_process_name)
    if len(ion_backend.proc) == 0:
        # Se il processo non e' in lista lo credo in modo artificiale
        proc_backend = _make_fake_backend(my_pid, my_cwd)
        pid = proc_backend.get_pid()
        ptbl._insert_process(proc_backend)
    else:
        proc_backend = ion_backend.proc[0]
        proc_backend.pid = my_pid
        proc_backend.cwd = my_cwd
        pid = proc_backend.get_pid()
        if my_pid != pid:
            raise Exception("Che è successo? Gestire")
        ptbl.update(proc_backend)


    # __cron_checker__ process
    ion_cron = ptbl.find_id_or_name(cron_checker_process_name)
    if len(ion_cron.proc) == 0:
        proc_cron = _make_cron_checker()
        ptbl._insert_process(proc_cron)
    else:
        proc_cron = ion_cron.proc[0]

    ret_m = _resp(_start_process(proc_cron, ion_cron))
    if ret_m['err'] is True:
        print(ret_m)

    # Autorun
    ion = ptbl.find_id_or_name('autorun_enabled')
    for proc in ion.proc:
        proc.is_running
        ret_m = _resp(_start_process(proc, ion))
        if ret_m['err'] is True:
            print(ret_m)

    # Threads
    #t1 = threading.Thread(target=_interal_poll_thread)
    #t1.start()


    print(f'running on pid: {my_pid}')
    
    uvicorn.run("PM3.app:app", host=dsn.host, port=dsn.port, reload=True)
    # il reloader non fa ricaricare correttamente il backend! perchè ci sono i threads
    # ricaricare a mano

if __name__ == '__main__':
    main()
