from importlib import import_module
import json, os
from subprocess import run
from types import SimpleNamespace as Namespace
import unittest
unittest.TestLoader.sortTestMethodsUsing = None
from datetime import datetime

module_name = 'PM3'
module_run = f'python -m {module_name}'

test_process_name = 'test_process_name'
"""With this variable set to False, if a daemon is already running,
the test are stopped. This is to prevent a unwanted execution."""
run_anyway_if_deamon_running = True

# test dei comandi

def shell(command, **kwargs):
    """
    Execute a shell command capturing output and exit code.

    This is a better version of ``os.system()`` that captures output and
    returns a convenient namespace object.
    """
    completed = run(command, shell=True, capture_output=True, check=False, **kwargs)

    return Namespace(
        exit_code=completed.returncode,
        stdout=completed.stdout.decode(),
        stderr=completed.stderr.decode(),
    )

def dump_and_read_json(self):
    file_name = "test0dump_" + datetime.now().strftime("%d%m%Y-%H%M%S.%f") + ".json"
    result = shell(f"{module_run}.cli dump --file " + file_name)

    self.assertEqual( result.exit_code , 0)

    # deve esserci il nome del file
    assert os.path.exists(file_name)

    with open(file_name) as f:
        return json.loads( f.read())

def print_and_assert(cmd: str) -> int:
    """Print stdout and stderr of the command.
    Return the exit code."""
    result = shell(cmd)
    print("stdout: \n" + result.stdout)
    print("stderr: \n" + result.stderr)
    return result.exit_code

class TestShell(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        """Another daemon already running?"""
        if run_anyway_if_deamon_running:
            return # bypass daemon check (for debugging)

        self.test_file_1 = "test_dump_1" + datetime.now().strftime("%d%m%Y-%H%M%S.%f") + ".json"
        self.test_file_2 = "test_dump_1" + datetime.now().strftime("%d%m%Y-%H%M%S.%f") + ".json"

        result = shell(f"{module_run}.cli ping")
        if (result.exit_code == 0):
            print("""Another daemon already running! Another active instance!
                  ps: take care! With test all tasks will be purged.""")
            exit(-1)
            


    def test_01_main_module(self):
        """
        Importa modulo per verificare che sia installato correttamente.
        """
        import_module(f"{module_name}")

    def test_02_ping_fail(self):
        """Ping deve fallire perchè il backend deve essere non attivo durante i test.
        Se questo test fallice, uccidere il processo in esecuzione."""
        assert print_and_assert(f"{module_run}.cli ping") != 0

    def test_03_async_daemon_start(self):
        """Ora attiviamo il demone con start"""
        if not run_anyway_if_deamon_running:
            return # do not start the daemon
        
        self.assertEqual( print_and_assert(f"{module_run}.cli daemon start") , 0)

    def test_04_ping_success(self):
        """Ora ping ritorna 0 perchè il demone è attivo."""
        self.assertEqual( print_and_assert(f"{module_run}.cli ping") , 0)

    def test_05_dump(self):
        # facciamo un dump per backup
        self.assertEqual( print_and_assert(f"{module_run}.cli dump --file test_dump_" + datetime.now().strftime("%d%m%Y-%H%M%S.%f") + ".json") , 0)
    
    def test_06_dump_stdout(self):
        # facciamo un dump per backup
        self.assertEqual( print_and_assert(f"{module_run}.cli dump") , 0)

    def test_07_pre_test_add_process(self):
        """ora di sicuro l'aggiunta deve andare e buon fine
        """
        self.assertEqual( print_and_assert(f"{module_run}.cli new {test_process_name}") , 0)

    def test_08_purge_process(self):
        result = shell(f"{module_run}.cli rm all") # rimuovi ma non ti interessare del risultato
        self.assertEqual( result.exit_code , 0)

    def test_09_dump_test_purged(self):
        # facciamo un dump per backup
        # contolliamo poi che il file esista!
        if len(dump_and_read_json(self)) != 0:
            assert False

    def test_10_test_add_process(self):
        self.assertEqual( print_and_assert(f"{module_run}.cli new {test_process_name}") , 0) # ora di sicuro l'aggiunta deve andare e buon fine

    def test_11_remove_process_success(self):
        self.assertEqual( print_and_assert(f"{module_run}.cli rm {test_process_name}") , 0) # e di nuovo rimuovi e accertati che l'exit code sia 0
        self.assertNotEqual( print_and_assert(f"{module_run}.cli rm {test_process_name}") , 0 ) # e di nuovo rimuovi e accertati che l'exit code sia diverso 0

    def test_12_test_add_again_process(self):
        # ora di sicuro l'aggiunta deve andare e buon fine
        self.assertEqual( print_and_assert(f'{module_run}.cli new "sleep 100" --name {test_process_name}') , 0)

    def test_13_test_start(self):
        self.assertEqual( print_and_assert(f"{module_run}.cli start {test_process_name}") , 0)

    def test_14_test_start_again(self):
        """Ritorna un exit status diverso da zero perchè era già attivo."""
        self.assertNotEqual(print_and_assert(f"{module_run}.cli start {test_process_name}"), 0)

    def test_15_test_stop(self):
        """Ritorna correttamente e ferma il processo."""
        self.assertEqual( print_and_assert(f"{module_run}.cli stop {test_process_name}") , 0)

    def test_16_test_stop(self):
        """Deve ritornare un errore perchè il processo era già fermo."""
        self.assertNotEqual(f"{module_run}.cli stop {test_process_name}", 0)

    def test_17_test_ls(self):
        self.assertEqual(print_and_assert(f"{module_run}.cli ls") , 0)

    def test_18_test_ls(self):
        self.assertEqual(print_and_assert(f"{module_run}.cli ls -j") , 0)

    def test_19_test_ls(self):
        self.assertEqual(print_and_assert(f"{module_run}.cli ls -l") , 0)

    def test_20_dump(self):
        # facciamo un dump per backup
        if len(dump_and_read_json(self)) != 1:
            assert False

    def test_21_test_pid_changed(self):
        out = shell(f"{module_run}.cli ls {test_process_name} -j")
        pid_prev = json.loads(out.stdout)[0].get('pid')

        shell(f"{module_run}.cli restart {test_process_name}")

        out = shell(f"{module_run}.cli ls {test_process_name} -j")
        pid_curr = json.loads(out.stdout)[0].get('pid')

        self.assertNotEqual(pid_prev, pid_curr)

    def test_22_async_daemon_stop(self):
        self.assertEqual( print_and_assert(f"{module_run}.cli daemon stop") , 0)

    def test_24_async_daemon_restart(self):
        """Riavvio il demone. I processi rimangono memorizzati."""
    pass