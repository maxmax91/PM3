
import gzip
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import shutil
import threading


def namer(name):
    return name + ".gz"

def rotator(source, dest):
    with open(source, 'rb') as f_in:
        with gzip.open(dest, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.remove(source)


class LogPipe(threading.Thread):

    def __init__(self, filename, level = logging.DEBUG):
        """Setup the object with a logger and a loglevel
        and start the thread
        """
        # nuovo logger
        from uuid import uuid4
        logger = logging.getLogger( str(uuid4()))
        # for testing
        # handler = TimedRotatingFileHandler(filename, when="S", interval=30, backupCount=20)
        handler = TimedRotatingFileHandler(filename, when="S", interval=30, backupCount=20) # can use also maxBytes
        logger.level = level
        handler.level = level
        handler.rotator = rotator
        handler.namer = namer

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