from logging.handlers import RotatingFileHandler
import threading, logging
from pydantic import BaseModel, PrivateAttr, field_validator, model_validator
from sqlalchemy import Tuple
from sqlmodel import Field, SQLModel
from typing import List, Mapping, Optional, Union
import subprocess as sp
import psutil
import os
from pathlib import Path
import pendulum
import signal

from sqlmodel import SQLModel
from PM3.model.pm3_protocol import KillMsg, alive_gone

# TODO: Trovare nomi milgiori


def on_terminate(proc):
    pass
    #print(proc.status())
    #print("process {} terminated with exit code {}".format(proc.pid, proc.returncode))


class ProcessStatusLight(BaseModel):
    pm3_id: int
    pm3_name: str
    cmdline: Union[list, str]
    cpu_percent: float
    create_time: Union[float, str]
    time_ago: str = ''
    cwd: Union[str, None]
    exe: str
    memory_percent: float
    name: str
    ppid: int
    pid: int
    status: str
    username: str
    cmd: str
    restart: int
    autorun: bool

    @field_validator('memory_percent')
    def memory_percent_formatter(cls, v):
        v = round(v, 2)
        return v

    @field_validator('cmdline')
    def cmdline_formatter(cls, v):
        if isinstance(v, list):
            v = ' '.join(v)
        return v

    @model_validator(mode='after')
    def time_ago_generator(self):
        create_time = pendulum.from_timestamp(self.create_time)
        time_ago = pendulum.now() - create_time
        self.time_ago = time_ago.in_words()

    @field_validator('create_time')
    def create_time_formatter(cls, v, values, **kwargs):
        if isinstance(v, float):
            v = pendulum.from_timestamp(v).astimezone().format('DD/MM/YYYY HH:mm:ss')
        return v


class ProcessStatus(BaseModel):
    cmdline: list
    connections: Union[list, None]
    cpu_percent: float
    cpu_times: list
    create_time: float
    cwd: Union[str, None]
    exe: str
    gids: list
    io_counters: Union[list, None]
    ionice: list
    memory_info: list
    memory_percent: float
    name: str
    open_files: Union[list, None]
    pid: int
    ppid: int
    status: str
    uids: list
    username: str

    cmd: str
    interpreter: str
    pm3_home: str
    pm3_name: str
    pm3_id: int
    shell: bool
    stdout: str
    stderr: str
    restart: int
    autorun: bool
    nohup: bool

class LogPipe(threading.Thread):

    def __init__(self, filename, level = logging.DEBUG):
        """Setup the object with a logger and a loglevel
        and start the thread
        """
        # nuovo logger
        from uuid import uuid4
        logger = logging.getLogger( str(uuid4()))
        handler = RotatingFileHandler(filename, maxBytes=1000*1000*30, backupCount=20)
        logger.level = level
        handler.level = level
        logger.addHandler( handler )

        threading.Thread.__init__(self)
        self.daemon = False
        self.level = level
        self.logger = logger
        self.fdRead, self.fdWrite = os.pipe()
        self.pipeReader = os.fdopen(self.fdRead)

        self.start()

    def fileno(self):
        """Return the write file descriptor of the pipe
        """
        return self.fdWrite

    def run(self):
        """Run the thread, logging everything.
        """
        for line in iter(self.pipeReader.readline, ''):
            self.logger.log(self.level, line.strip('\n'))

        self.pipeReader.close()

    def close(self):
        """Close the write end of the pipe.
        """
        os.close(self.fdWrite)


    # Utilizzata per mostrare i dati in formato tabellare

    pm3_name: str
    cmd: str
    cwd: str = Path.home().as_posix()
    pid: Union[int, None] = -1
    restart: Union[int, str] = ''
    running: bool = False
    autorun: Union[bool, str] = False

# a causa di un non allineamento tra SQLModel e pydanticV2
# bisogna usare un workaround per usare json_schema_extra.
# https://github.com/tiangolo/sqlmodel/discussions/780
# 1) schema_extra={"json_schema_extra": {'list': True}
# anzichè 
# 2) json_schema_extra={'list': True}
# appena verrà risolto 1) verrà sostituito con 2)

prop_list = {"json_schema_extra": {'list': True} }

class Process(SQLModel, table=True):
    # Struttura vera del processo
    pm3_id: Optional[int] = Field(primary_key=True, default=None, schema_extra=prop_list )  # None significa che deve essere assegnato da next_id()
    pm3_name: str = Field(schema_extra=prop_list)
    cmd: str = Field(schema_extra=prop_list)
    cwd: Optional[str] = Field(default= Path.home().as_posix() , schema_extra=prop_list)
    pid: Optional[int] = Field(default=-1, schema_extra=prop_list)
    pm3_home: Optional[str] = Path('~/.pm3/').expanduser().as_posix()
    restart: int = Field(default=-1, description="How many time, maximum, the process should be restarted.")
    shell: bool = False
    autorun: bool = Field(default=False)
    interpreter: str = ''
    stdout: str = ''
    stderr: str = ''
    nohup: bool = False
    max_restart: Optional[int] = 1000
    autorun_exclude : bool = False

    @property
    def autorun_status(self) -> str:
        if self.autorun is False:
            return '[red]disabled[/red]'
        elif self.autorun and self.autorun_exclude:
            return '[yellow]suspended[/yellow]'
        elif self.autorun and not self.autorun_exclude:
            return '[green]enabled[/green]'

    @property
    def is_running(self) -> bool:
        # Fromatting running
        return True if self.get_pid() > 0 else False
    
    @property
    def restart_status(self) -> str:
        # Formatting restart
        n_restart = self.restart if self.restart > 0 else 0
        return f"{n_restart}/{self.max_restart}"

    @property
    def pid_status(self):
        if self.autorun is True and self.pid == -1: # check this things
            return f'[red]!!![/red]'
        elif self.autorun is False and self.pid == -1:
            return f'[gray]-[/gray]'
        else:
            return str(self.pid)

    @model_validator(mode='after')
    def _formatter(self) -> "Process":
        # pm3_name

        self.pm3_name = self.pm3_name or self.cmd.split(" ")[0]
        self.pm3_name = self.pm3_name.replace(' ', '_').replace('./', '').replace('/', '')

        # stdout
        logfile = f"{self.pm3_name}_{self.pm3_id}.log"
        self.stdout = self.stdout or Path(self.pm3_home, 'log', logfile).as_posix()

        # stderr
        errfile = f"{self.pm3_name}_{self.pm3_id}.err"
        self.stderr = self.stderr or Path(self.pm3_home, 'log', errfile).as_posix()

        return self

    def get_pid(self) -> int:
        """Return the PID or -1 if not running."""

        if self.pid is not None and self.pid > 0:

            try:
                # Verifico che il pid esita ancora
                ps = self.ps(full=True)
                # Verifico che il pid appartenga all'UID corrente
                ps_cwd = ps.cwd()
            except psutil.ZombieProcess:
                return -1
            except psutil.NoSuchProcess:
                return -1
            except psutil.AccessDenied:
                return -1
                

            if Path(self.cwd) == Path(ps_cwd):
                # Minimal check for error in pid
                return ps.pid
            return -1
        else:
            return -1

    def ps(self, full=False):
        if full:
            return psutil.Process(self.pid)
        else:
            return ProcessStatus(**psutil.Process(self.pid).as_dict())

    @staticmethod
    def kill_proc_tree(pid, sig=signal.SIGTERM, include_parent=True,
                       timeout=5, on_terminate=on_terminate):
        """Kill a process tree (including grandchildren) with signal
        "sig" and return a (gone, still_alive) tuple.
        "on_terminate", if specified, is a callback function which is
        called as soon as a child terminates.
        """
        parent = psutil.Process(pid)
        # Kill Parent and Children
        children = parent.children(recursive=True)
        if include_parent:
            children.append(parent)

        for p in children:
            try:
                p.send_signal(sig)
            except psutil.NoSuchProcess:
                pass
        try:
            gone, alive = psutil.wait_procs(children, timeout=timeout,
                                            callback=on_terminate)
        except psutil.NoSuchProcess:
            gone = [alive_gone(pid=pid),]
            alive = []

        return (gone, alive)

    def kill(self):
        if self.pid is None or self.pid == -1:
            return KillMsg(msg='NOT RUNNING', warn=True)
        try:
            psutil.Process(self.pid)
        except psutil.NoSuchProcess:
            return KillMsg(msg='NO SUCH PROCESS', warn=True)

        gone, alive = self.kill_proc_tree(self.pid)
        if len(alive) > 0:
            return KillMsg(msg='OK', alive=alive, gone=gone, warn=True)
        else:
            self.pid = -1
            return KillMsg(msg='OK', alive=alive, gone=gone)

    def run(self):
        #fErrHandler = RotatingFileHandler(self.stderr, maxBytes=1000*1000*10, backupCount=5)
        #fout = LogPipe(self.stderr)
        #ferr = LogPipe(self.stdout)
        fout = open(self.stdout, 'a')
        ferr = open(self.stderr, 'a')
        if isinstance(self.cmd, list):
            cmd = self.cmd
        elif isinstance(self.cmd, str):
            cmd = self.cmd.split(' ')
        else:
            return False

        if Path(self.interpreter).is_file():
            cmd.insert(0, self.interpreter)

        if self.nohup:
            # print("starting with nohup")
            if 'nohup' not in cmd[0]:
                cmd.insert(0, '/usr/bin/nohup')
            # print('detach', cmd)
            p = sp.Popen(cmd,
                         cwd=self.cwd,
                         shell=self.shell,
                         stdout=fout,
                         stderr=ferr,
                         bufsize=0,
                         preexec_fn=os.setpgrp)
        else:
            print("starting w/o nohup")
            p = sp.Popen(cmd,
                         cwd=self.cwd,
                         shell=self.shell,
                         stdout=fout,
                         stderr=ferr,
                         bufsize=0)
        self.pid = p.pid
        self.restart += 1
        self.autorun_exclude = False
        return p

    def reset(self):
        self.restart = 0



# id or Name schema
class ION(BaseModel):
    type: str
    data: Union[str, int]
    proc: List[Process]