import os
import sys
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'caspian.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
