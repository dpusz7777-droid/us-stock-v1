# -*- coding: utf-8 -*-
import os
import sys

if 'API_DEMO_HOMEPATH' not in os.environ:
    home_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.environ['API_DEMO_HOMEPATH'] = home_path
    sys.path.append(home_path)

