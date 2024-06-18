from configparser import ConfigParser
from pathlib import Path
import logging
import PM3.model.errors as PM3_errors
from PM3.model.process_log_config import ProcessLogConfig

#pm3_home_dir = config['main_section'].get('pm3_home_dir')
pm3_home_dir = Path('~/.pm3').expanduser()
config_file = Path(f'{pm3_home_dir}/config.ini')

if not config_file.is_file():
    print(f"Config file not found at path {config_file}! Exiting...")
    exit(PM3_errors.CONFIG_FILE_NOT_FOUND)

config = ConfigParser()
config.read(config_file)


# TODO: better to write it better
section_logs = config['logs']
log_config = ProcessLogConfig( **section_logs )

backend_process_name = config['backend'].get('name') or '__backend__'
cron_checker_process_name = config['cron_checker'].get('name') or '__cron_checker__'

logger : logging.Logger = logging.getLogger("PM3")
logging.basicConfig(encoding='utf-8', level=logging.DEBUG)