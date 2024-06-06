from configparser import ConfigParser
from pathlib import Path


#pm3_home_dir = config['main_section'].get('pm3_home_dir')
pm3_home_dir = Path('~/.pm3').expanduser()
config_file = f'{pm3_home_dir}/config.ini'

config = ConfigParser()
config.read(config_file)

backend_process_name = config['backend'].get('name') or '__backend__'
cron_checker_process_name = config['cron_checker'].get('name') or '__cron_checker__'
